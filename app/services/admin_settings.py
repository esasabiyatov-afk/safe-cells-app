"""Transactional administrative credentials, tariffs, and safe config values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
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


BUSY_MESSAGE = "База сейчас занята другим сотрудником. Повторите позже."
UNCERTAIN_MESSAGE = (
    "Не удалось подтвердить результат записи. Обновите настройки и проверьте данные."
)
EDITABLE_CONFIG_KEYS = frozenset({"expiring_soon_days", "deposit_amount_minor"})
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
                          relative_file_name, is_active
                   FROM document_templates
                   ORDER BY document_type, display_name, template_id"""
            ).fetchall()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    try:
        config = {str(row["key"]): int(row["value"]) for row in config_rows}
    except (TypeError, ValueError) as exc:
        raise AdminWriteError("Обязательные настройки отсутствуют или повреждены.") from exc
    if set(config) != EDITABLE_CONFIG_KEYS:
        raise AdminWriteError("Обязательные настройки отсутствуют или повреждены.")
    return {
        "config": config,
        "tariffs": [dict(row) for row in tariff_rows],
        "templates": [
            {
                **dict(row),
                "is_active": bool(row["is_active"]),
            }
            for row in template_rows
        ],
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


def update_admin_settings(
    settings: Settings,
    *,
    payload: object,
    employee: object,
    occurred_at: datetime,
) -> AdminWriteResult:
    if not isinstance(payload, dict) or set(payload) != {"operation_id", "config", "tariffs"}:
        raise AdminValidationError("Переданы неизвестные или неполные настройки.")
    operation_id = _operation_id(payload["operation_id"])
    config = _validate_config(payload["config"])
    tariffs = _validate_tariffs(payload["tariffs"])
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
            for key, value in config.items():
                cursor = connection.execute(
                    """UPDATE config SET value = ?, updated_at = ?, updated_by = ?
                       WHERE key = ?""",
                    (str(value), timestamp, employee_name, key),
                )
                if cursor.rowcount != 1:
                    raise AdminConflictError("Обязательная настройка отсутствует в базе.")
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
