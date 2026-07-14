"""Transactional administrative credentials, tariffs, and safe config values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from app.config import Settings
from app.db.connections import (
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_readonly,
    open_write,
    validate_database_pair,
)
from app.services.admin_auth import hash_password, validate_new_password, verify_password
from app.services.backups import create_backup_pair
from app.services.employee import (
    EMPLOYEES_CONFIG_KEY,
    MAX_EMPLOYEES,
    EmployeeProfileError,
    EmployeeRecord,
    decode_employee_config,
    encode_employee_config,
    validate_employee_full_name,
)
from app.services.penalty_rates import (
    PENALTY_MANUAL_RATES_KEY,
    PENALTY_RATE_MODE_KEY,
    PENALTY_RATE_MODES,
    PenaltyRateConfigurationError,
    encode_manual_rates,
    get_penalty_settings,
)


BUSY_MESSAGE = "База сейчас занята другим сотрудником. Повторите позже."
UNCERTAIN_MESSAGE = (
    "Не удалось подтвердить результат записи. Обновите настройки и проверьте данные."
)
EDITABLE_CONFIG_KEYS = frozenset({"expiring_soon_days", "deposit_amount_minor"})
ACCESS_MODE_PASSWORD = "password"
ACCESS_MODE_ACKNOWLEDGEMENT = "acknowledgement"
ADMIN_ACCESS_MODES = frozenset({ACCESS_MODE_PASSWORD, ACCESS_MODE_ACKNOWLEDGEMENT})
MAX_MONEY_VALUE = 10_000_000


class AdminValidationError(ValueError):
    pass


class AdminConflictError(RuntimeError):
    pass


class AdminBusyError(RuntimeError):
    pass


class AdminNetworkError(RuntimeError):
    pass


class AdminWriteError(RuntimeError):
    pass


class AdminWriteUncertainError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AdminWriteResult:
    repeated: bool
    backup_created: bool
    warning: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repeated": self.repeated,
            "backup_created": self.backup_created,
            "warning": self.warning,
        }


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AdminValidationError("Время операции должно содержать часовой пояс.")
    return value.isoformat(timespec="seconds")


def _operation_id(value: object) -> str:
    if not isinstance(value, str):
        raise AdminValidationError("Неверный идентификатор операции.")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise AdminValidationError("Неверный идентификатор операции.") from exc


def _employee(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdminValidationError("Не удалось определить сотрудника.")
    normalized = " ".join(value.split())
    if len(normalized) > 128:
        raise AdminValidationError("Имя сотрудника слишком длинное.")
    return normalized


def _integer(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise AdminValidationError(f"Поле «{label}» должно быть целым числом.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AdminValidationError(f"Поле «{label}» должно быть целым числом.") from exc
    if str(value).strip() != str(result):
        raise AdminValidationError(f"Поле «{label}» должно быть целым числом.")
    if not minimum <= result <= maximum:
        raise AdminValidationError(
            f"Поле «{label}» должно быть от {minimum} до {maximum}."
        )
    return result


def get_admin_password_hash(settings: Settings) -> str | None:
    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            row = connection.execute(
                "SELECT password_hash FROM admin_credentials WHERE id = 1"
            ).fetchone()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    return None if row is None else str(row["password_hash"])


def is_admin_configured(settings: Settings) -> bool:
    return get_admin_password_hash(settings) is not None


def get_admin_access_mode(settings: Settings) -> str:
    """Read the access mode, defaulting old databases to password mode."""
    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            row = connection.execute(
                "SELECT value FROM config WHERE key = 'admin_access_mode'"
            ).fetchone()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    if row is None:
        return ACCESS_MODE_PASSWORD
    mode = str(row["value"])
    if mode not in ADMIN_ACCESS_MODES:
        raise AdminWriteError("Режим доступа к настройкам повреждён.")
    return mode


def _backup_after_commit(
    connection: sqlite3.Connection,
    settings: Settings,
    *,
    operation_id: str,
    occurred_at: datetime,
) -> tuple[bool, str | None]:
    try:
        create_backup_pair(
            connection,
            settings,
            operation_id=operation_id,
            occurred_at=occurred_at,
        )
    except Exception:
        return (
            False,
            "Настройки сохранены, но резервную копию создать не удалось. "
            "Сообщите администратору.",
        )
    return True, None


def _existing_operation(
    connection: sqlite3.Connection, operation_id: str, action: str
) -> bool:
    row = connection.execute(
        "SELECT action FROM archive.log WHERE operation_id = ?", (operation_id,)
    ).fetchone()
    if row is None:
        return False
    if str(row["action"]) != action:
        raise AdminConflictError("Идентификатор операции уже использован.")
    return True


def _write_password(
    settings: Settings,
    *,
    operation_id: object,
    new_password: object,
    current_password: object | None,
    employee: object,
    occurred_at: datetime,
    initial: bool,
) -> AdminWriteResult:
    normalized_operation = _operation_id(operation_id)
    normalized_employee = _employee(employee)
    timestamp = _timestamp(occurred_at)
    password_hash = hash_password(validate_new_password(new_password))
    action = "admin.password.created" if initial else "admin.password.changed"
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            if _existing_operation(connection, normalized_operation, action):
                connection.rollback()
                return AdminWriteResult(True, False, None)
            row = connection.execute(
                "SELECT password_hash FROM admin_credentials WHERE id = 1"
            ).fetchone()
            if initial:
                if row is not None:
                    raise AdminConflictError("Административный пароль уже создан.")
                connection.execute(
                    "INSERT INTO admin_credentials(id, password_hash, changed_at) VALUES(1, ?, ?)",
                    (password_hash, timestamp),
                )
            else:
                if row is None:
                    raise AdminConflictError("Административный пароль ещё не создан.")
                if not verify_password(current_password, row["password_hash"]):
                    raise AdminValidationError("Текущий административный пароль неверен.")
                connection.execute(
                    "UPDATE admin_credentials SET password_hash = ?, changed_at = ? WHERE id = 1",
                    (password_hash, timestamp),
                )
            connection.execute(
                """INSERT INTO archive.log(
                       log_id, operation_id, occurred_at, employee, action,
                       contract_id, cell_number, changes_json
                   ) VALUES(?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (
                    str(uuid4()),
                    normalized_operation,
                    timestamp,
                    normalized_employee,
                    action,
                    json.dumps({"password_changed": True}, sort_keys=True),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT 1 FROM archive.log WHERE operation_id = ? AND action = ?",
                (normalized_operation, action),
            ).fetchone()
            if saved is None:
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
            backup_created, warning = _backup_after_commit(
                connection,
                settings,
                operation_id=normalized_operation,
                occurred_at=occurred_at,
            )
            return AdminWriteResult(False, backup_created, warning)
    except (AdminValidationError, AdminConflictError, AdminWriteUncertainError):
        raise
    except DatabaseUnavailableError as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {"opening", "begin", "transaction"}:
            raise AdminBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminWriteError("Пароль не сохранён. Изменения отменены.") from exc


def create_admin_password(
    settings: Settings,
    *,
    operation_id: object,
    password: object,
    employee: object,
    occurred_at: datetime,
) -> AdminWriteResult:
    return _write_password(
        settings,
        operation_id=operation_id,
        new_password=password,
        current_password=None,
        employee=employee,
        occurred_at=occurred_at,
        initial=True,
    )


def change_admin_password(
    settings: Settings,
    *,
    operation_id: object,
    current_password: object,
    new_password: object,
    employee: object,
    occurred_at: datetime,
) -> AdminWriteResult:
    return _write_password(
        settings,
        operation_id=operation_id,
        new_password=new_password,
        current_password=current_password,
        employee=employee,
        occurred_at=occurred_at,
        initial=False,
    )


def get_admin_settings(settings: Settings) -> dict[str, Any]:
    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            config_rows = connection.execute(
                "SELECT key, value FROM config WHERE key IN (?, ?) ORDER BY key",
                tuple(sorted(EDITABLE_CONFIG_KEYS)),
            ).fetchall()
            tariff_rows = connection.execute(
                """SELECT height_mm, period_from_days, period_to_days,
                          price_per_day_minor
                   FROM tariffs
                   ORDER BY height_mm, period_from_days"""
            ).fetchall()
            template_rows = connection.execute(
                """SELECT template_id, document_type, display_name,
                          relative_file_name, required_placeholders_json, is_active
                   FROM document_templates
                   ORDER BY document_type, display_name, template_id"""
            ).fetchall()
            employee_row = connection.execute(
                "SELECT value FROM config WHERE key = ?", (EMPLOYEES_CONFIG_KEY,)
            ).fetchone()
            penalty = get_penalty_settings(connection)
    except PenaltyRateConfigurationError as exc:
        raise AdminWriteError(str(exc)) from exc
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    try:
        config = {str(row["key"]): int(row["value"]) for row in config_rows}
    except (TypeError, ValueError) as exc:
        raise AdminWriteError("Обязательные настройки отсутствуют или повреждены.") from exc
    if set(config) != EDITABLE_CONFIG_KEYS:
        raise AdminWriteError("Обязательные настройки отсутствуют или повреждены.")
    try:
        employees = decode_employee_config(
            None if employee_row is None else employee_row["value"]
        )
    except EmployeeProfileError as exc:
        raise AdminWriteError(str(exc)) from exc
    templates = []
    for row in template_rows:
        try:
            placeholders = json.loads(str(row["required_placeholders_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise AdminWriteError("Список полей одного из шаблонов повреждён.") from exc
        if not isinstance(placeholders, list) or not all(
            isinstance(item, str) for item in placeholders
        ):
            raise AdminWriteError("Список полей одного из шаблонов повреждён.")
        file_name = str(row["relative_file_name"])
        file_present = (
            Path(file_name).name == file_name
            and file_name.casefold().endswith(".docx")
            and (paths.directory / "templates" / file_name).is_file()
        )
        templates.append(
            {
                "template_id": row["template_id"],
                "document_type": row["document_type"],
                "display_name": row["display_name"],
                "relative_file_name": file_name,
                "required_placeholders": placeholders,
                "file_present": file_present,
                "is_active": bool(row["is_active"]),
            }
        )
    return {
        "config": config,
        "tariffs": [dict(row) for row in tariff_rows],
        "templates": templates,
        "employees": [
            employee.to_dict()
            for employee in sorted(employees, key=lambda item: item.full_name.casefold())
        ],
        "penalty": penalty,
        "access_mode": get_admin_access_mode(settings),
    }


def _validate_config(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != EDITABLE_CONFIG_KEYS:
        raise AdminValidationError(
            "Разрешено изменять только порог истечения и сумму залога."
        )
    return {
        "expiring_soon_days": _integer(
            value["expiring_soon_days"],
            "Порог истечения",
            minimum=1,
            maximum=365,
        ),
        "deposit_amount_minor": _integer(
            value["deposit_amount_minor"],
            "Сумма залога",
            minimum=0,
            maximum=MAX_MONEY_VALUE,
        ),
    }


def update_admin_access_mode(
    settings: Settings,
    *,
    payload: object,
    employee: object,
    occurred_at: datetime,
) -> AdminWriteResult:
    if not isinstance(payload, dict) or set(payload) != {"operation_id", "access_mode"}:
        raise AdminValidationError("Переданы неизвестные или неполные данные режима доступа.")
    operation_id = _operation_id(payload["operation_id"])
    mode = payload["access_mode"]
    if not isinstance(mode, str) or mode not in ADMIN_ACCESS_MODES:
        raise AdminValidationError("Выберите один из двух режимов доступа.")
    employee_name = _employee(employee)
    timestamp = _timestamp(occurred_at)
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            action = "admin.access.updated"
            if _existing_operation(connection, operation_id, action):
                connection.rollback()
                return AdminWriteResult(True, False, None)
            if mode == ACCESS_MODE_PASSWORD and connection.execute(
                "SELECT 1 FROM admin_credentials WHERE id = 1"
            ).fetchone() is None:
                raise AdminConflictError("Сначала создайте общий административный пароль.")
            old_row = connection.execute(
                "SELECT value FROM config WHERE key = 'admin_access_mode'"
            ).fetchone()
            old_mode = ACCESS_MODE_PASSWORD if old_row is None else str(old_row["value"])
            connection.execute(
                """INSERT INTO config(key, value, updated_at, updated_by)
                   VALUES('admin_access_mode', ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value=excluded.value, updated_at=excluded.updated_at,
                       updated_by=excluded.updated_by""",
                (mode, timestamp, employee_name),
            )
            connection.execute(
                """INSERT INTO archive.log(
                       log_id, operation_id, occurred_at, employee, action,
                       contract_id, cell_number, changes_json
                   ) VALUES(?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (
                    str(uuid4()), operation_id, timestamp, employee_name, action,
                    json.dumps(
                        {"access_mode": {"old": old_mode, "new": mode}},
                        sort_keys=True,
                    ),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT value FROM config WHERE key = 'admin_access_mode'"
            ).fetchone()
            if saved is None or str(saved["value"]) != mode:
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
            backup_created, warning = _backup_after_commit(
                connection,
                settings,
                operation_id=operation_id,
                occurred_at=occurred_at,
            )
            return AdminWriteResult(False, backup_created, warning)
    except (AdminValidationError, AdminConflictError, AdminWriteUncertainError):
        raise
    except DatabaseUnavailableError as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {"opening", "begin", "transaction"}:
            raise AdminBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminWriteError("Режим доступа не сохранён. Изменения отменены.") from exc


def update_admin_employee(
    settings: Settings,
    *,
    payload: object,
    employee: object,
    occurred_at: datetime,
) -> tuple[AdminWriteResult, EmployeeRecord]:
    expected = {
        "operation_id", "employee_id", "full_name", "is_active", "create"
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise AdminValidationError("Переданы неизвестные или неполные данные сотрудника.")
    operation_id = _operation_id(payload["operation_id"])
    employee_id = payload["employee_id"]
    try:
        employee_id = str(UUID(employee_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AdminValidationError("Неверный идентификатор сотрудника.") from exc
    try:
        full_name = validate_employee_full_name(payload["full_name"])
    except EmployeeProfileError as exc:
        raise AdminValidationError(str(exc)) from exc
    if not isinstance(payload["is_active"], bool) or not isinstance(payload["create"], bool):
        raise AdminValidationError("Состояние сотрудника должно быть включено или выключено.")
    is_active = payload["is_active"]
    create = payload["create"]
    actor = _employee(employee)
    timestamp = _timestamp(occurred_at)
    action = "admin.employee.created" if create else "admin.employee.updated"
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            row = connection.execute(
                "SELECT value FROM config WHERE key = ?", (EMPLOYEES_CONFIG_KEY,)
            ).fetchone()
            try:
                records = decode_employee_config(None if row is None else row["value"])
            except EmployeeProfileError as exc:
                raise AdminWriteError(str(exc)) from exc
            by_id = {record.employee_id: record for record in records}
            if _existing_operation(connection, operation_id, action):
                connection.rollback()
                saved = by_id.get(employee_id)
                if saved is None:
                    raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
                return AdminWriteResult(True, False, None), saved
            existing = by_id.get(employee_id)
            if create:
                if existing is not None:
                    raise AdminConflictError("Сотрудник уже существует. Обновите настройки.")
                if len(records) >= MAX_EMPLOYEES:
                    raise AdminValidationError("Нельзя добавить более 200 сотрудников.")
            elif existing is None:
                raise AdminConflictError("Сотрудник не найден. Обновите настройки.")
            if any(
                record.employee_id != employee_id
                and record.full_name.casefold() == full_name.casefold()
                for record in records
            ):
                raise AdminConflictError("Сотрудник с таким именем уже есть в списке.")
            updated = EmployeeRecord(employee_id, full_name, is_active)
            new_records = [
                updated if record.employee_id == employee_id else record
                for record in records
            ]
            if create:
                new_records.append(updated)
            if new_records and not any(record.is_active for record in new_records):
                raise AdminValidationError("В списке должен остаться хотя бы один активный сотрудник.")
            connection.execute(
                """INSERT INTO config(key, value, updated_at, updated_by)
                   VALUES(?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value=excluded.value, updated_at=excluded.updated_at,
                       updated_by=excluded.updated_by""",
                (
                    EMPLOYEES_CONFIG_KEY,
                    encode_employee_config(new_records),
                    timestamp,
                    actor,
                ),
            )
            changes = {
                "employee_id": employee_id,
                "full_name": {
                    "old": None if existing is None else existing.full_name,
                    "new": full_name,
                },
                "is_active": {
                    "old": None if existing is None else existing.is_active,
                    "new": is_active,
                },
            }
            connection.execute(
                """INSERT INTO archive.log(
                       log_id, operation_id, occurred_at, employee, action,
                       contract_id, cell_number, changes_json
                   ) VALUES(?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (
                    str(uuid4()), operation_id, timestamp, actor, action,
                    json.dumps(changes, ensure_ascii=False, sort_keys=True),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved_row = connection.execute(
                "SELECT value FROM config WHERE key = ?", (EMPLOYEES_CONFIG_KEY,)
            ).fetchone()
            try:
                saved_records = decode_employee_config(saved_row["value"])
            except (EmployeeProfileError, TypeError) as exc:
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
            saved = next(
                (record for record in saved_records if record.employee_id == employee_id),
                None,
            )
            if saved != updated:
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
            backup_created, warning = _backup_after_commit(
                connection, settings, operation_id=operation_id, occurred_at=occurred_at
            )
            return AdminWriteResult(False, backup_created, warning), saved
    except (
        AdminValidationError,
        AdminConflictError,
        AdminWriteError,
        AdminWriteUncertainError,
    ):
        raise
    except DatabaseUnavailableError as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {"opening", "begin", "transaction"}:
            raise AdminBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminWriteError("Список сотрудников не сохранён. Изменения отменены.") from exc


def _validate_tariffs(value: object) -> list[dict[str, int | None]]:
    if not isinstance(value, list) or not value:
        raise AdminValidationError("Передайте полный набор тарифов.")
    result: list[dict[str, int | None]] = []
    allowed = {
        "height_mm",
        "period_from_days",
        "period_to_days",
        "price_per_day_minor",
    }
    seen_keys: set[tuple[int, int]] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != allowed:
            raise AdminValidationError("Строка тарифа содержит неизвестные поля.")
        height = _integer(raw["height_mm"], "Высота", minimum=1, maximum=10_000)
        start = _integer(
            raw["period_from_days"], "Начало диапазона", minimum=1, maximum=100_000
        )
        end_value = raw["period_to_days"]
        end = None if end_value is None else _integer(
            end_value, "Конец диапазона", minimum=start, maximum=100_000
        )
        rate = _integer(
            raw["price_per_day_minor"],
            "Тариф",
            minimum=0,
            maximum=MAX_MONEY_VALUE,
        )
        key = (height, start)
        if key in seen_keys:
            raise AdminValidationError("В наборе есть повторяющаяся строка тарифа.")
        seen_keys.add(key)
        result.append(
            {
                "height_mm": height,
                "period_from_days": start,
                "period_to_days": end,
                "price_per_day_minor": rate,
            }
        )
    by_height: dict[int, list[dict[str, int | None]]] = {}
    for row in result:
        by_height.setdefault(int(row["height_mm"]), []).append(row)
    for height, rows in by_height.items():
        rows.sort(key=lambda row: int(row["period_from_days"]))
        expected_start = 1
        for index, row in enumerate(rows):
            if row["period_from_days"] != expected_start:
                raise AdminValidationError(
                    f"Тарифы высоты {height} мм содержат пропуск или пересечение."
                )
            end = row["period_to_days"]
            if index < len(rows) - 1 and end is None:
                raise AdminValidationError(
                    f"У тарифа высоты {height} мм открытый диапазон должен быть последним."
                )
            if index == len(rows) - 1:
                if end is not None:
                    raise AdminValidationError(
                        f"Последний тариф высоты {height} мм должен действовать без ограничения."
                    )
            else:
                expected_start = int(end) + 1
    return sorted(
        result, key=lambda row: (int(row["height_mm"]), int(row["period_from_days"]))
    )


def _validate_penalty(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"mode", "manual_rates"}:
        raise AdminValidationError("Переданы неизвестные или неполные настройки штрафа.")
    mode = value["mode"]
    if not isinstance(mode, str) or mode not in PENALTY_RATE_MODES:
        raise AdminValidationError("Выберите способ расчёта штрафной ставки.")
    raw_rates = value["manual_rates"]
    if not isinstance(raw_rates, list) or not raw_rates:
        raise AdminValidationError("Передайте ручные штрафные ставки по всем высотам.")
    rates: dict[int, int] = {}
    for raw in raw_rates:
        if not isinstance(raw, dict) or set(raw) != {
            "height_mm",
            "price_per_day_minor",
        }:
            raise AdminValidationError("Ручная штрафная ставка содержит неизвестные поля.")
        height = _integer(raw["height_mm"], "Высота", minimum=1, maximum=10_000)
        rate = _integer(
            raw["price_per_day_minor"],
            "Ручная штрафная ставка",
            minimum=0,
            maximum=MAX_MONEY_VALUE,
        )
        if height in rates:
            raise AdminValidationError("Ручная штрафная ставка одной высоты повторяется.")
        rates[height] = rate
    return {
        "mode": mode,
        "manual_rates": rates,
    }


def update_admin_settings(
    settings: Settings,
    *,
    payload: object,
    employee: object,
    occurred_at: datetime,
) -> AdminWriteResult:
    if not isinstance(payload, dict) or set(payload) != {
        "operation_id", "config", "tariffs", "penalty"
    }:
        raise AdminValidationError("Переданы неизвестные или неполные настройки.")
    operation_id = _operation_id(payload["operation_id"])
    config = _validate_config(payload["config"])
    tariffs = _validate_tariffs(payload["tariffs"])
    penalty = _validate_penalty(payload["penalty"])
    employee_name = _employee(employee)
    timestamp = _timestamp(occurred_at)
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            if _existing_operation(connection, operation_id, "admin.settings.updated"):
                connection.rollback()
                return AdminWriteResult(True, False, None)
            configured = connection.execute(
                "SELECT 1 FROM admin_credentials WHERE id = 1"
            ).fetchone()
            if configured is None:
                raise AdminConflictError("Административный пароль ещё не создан.")
            heights = {
                int(row["height_mm"])
                for row in connection.execute(
                    "SELECT DISTINCT height_mm FROM cells"
                ).fetchall()
            }
            supplied_heights = {int(row["height_mm"]) for row in tariffs}
            if supplied_heights != heights:
                raise AdminValidationError(
                    "Нужен полный набор тарифов для всех существующих высот ячеек."
                )
            if set(penalty["manual_rates"]) != heights:
                raise AdminValidationError(
                    "Нужны ручные штрафные ставки для всех существующих высот ячеек."
                )
            old_config = {
                str(row["key"]): str(row["value"])
                for row in connection.execute(
                    "SELECT key, value FROM config WHERE key IN (?, ?)",
                    tuple(sorted(EDITABLE_CONFIG_KEYS)),
                ).fetchall()
            }
            old_tariffs = [
                dict(row)
                for row in connection.execute(
                    """SELECT height_mm, period_from_days, period_to_days,
                              price_per_day_minor FROM tariffs
                       ORDER BY height_mm, period_from_days"""
                ).fetchall()
            ]
            try:
                old_penalty = get_penalty_settings(connection)
            except PenaltyRateConfigurationError as exc:
                raise AdminConflictError(str(exc)) from exc
            for key, value in config.items():
                cursor = connection.execute(
                    """UPDATE config SET value = ?, updated_at = ?, updated_by = ?
                       WHERE key = ?""",
                    (str(value), timestamp, employee_name, key),
                )
                if cursor.rowcount != 1:
                    raise AdminConflictError("Обязательная настройка отсутствует в базе.")
            penalty_values = {
                PENALTY_RATE_MODE_KEY: penalty["mode"],
                PENALTY_MANUAL_RATES_KEY: encode_manual_rates(
                    penalty["manual_rates"]
                ),
            }
            for key, value in penalty_values.items():
                connection.execute(
                    """INSERT INTO config(key, value, updated_at, updated_by)
                       VALUES(?, ?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET
                           value = excluded.value,
                           updated_at = excluded.updated_at,
                           updated_by = excluded.updated_by""",
                    (key, value, timestamp, employee_name),
                )
            connection.execute("DELETE FROM tariffs")
            connection.executemany(
                """INSERT INTO tariffs(
                       height_mm, period_from_days, period_to_days,
                       price_per_day_minor, updated_at, updated_by
                   ) VALUES(?, ?, ?, ?, ?, ?)""",
                [
                    (
                        row["height_mm"],
                        row["period_from_days"],
                        row["period_to_days"],
                        row["price_per_day_minor"],
                        timestamp,
                        employee_name,
                    )
                    for row in tariffs
                ],
            )
            changes = {
                "config": {
                    key: {"old": old_config.get(key), "new": str(value)}
                    for key, value in config.items()
                    if old_config.get(key) != str(value)
                },
                "tariffs": {"old": old_tariffs, "new": tariffs},
                "penalty": {
                    "old": old_penalty,
                    "new": {
                        "mode": penalty["mode"],
                        "manual_rates": [
                            {
                                "height_mm": height,
                                "price_per_day_minor": penalty["manual_rates"][height],
                            }
                            for height in sorted(penalty["manual_rates"])
                        ],
                    },
                },
            }
            connection.execute(
                """INSERT INTO archive.log(
                       log_id, operation_id, occurred_at, employee, action,
                       contract_id, cell_number, changes_json
                   ) VALUES(?, ?, ?, ?, 'admin.settings.updated', NULL, NULL, ?)""",
                (
                    str(uuid4()),
                    operation_id,
                    timestamp,
                    employee_name,
                    json.dumps(changes, ensure_ascii=False, sort_keys=True),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT 1 FROM archive.log WHERE operation_id = ? AND action = 'admin.settings.updated'",
                (operation_id,),
            ).fetchone()
            if saved is None:
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
            backup_created, warning = _backup_after_commit(
                connection,
                settings,
                operation_id=operation_id,
                occurred_at=occurred_at,
            )
            return AdminWriteResult(False, backup_created, warning)
    except (AdminValidationError, AdminConflictError, AdminWriteUncertainError):
        raise
    except DatabaseUnavailableError as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {"opening", "begin", "transaction"}:
            raise AdminBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminWriteError("Настройки не сохранены. Изменения отменены.") from exc
