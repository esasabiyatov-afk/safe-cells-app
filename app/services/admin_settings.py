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
    DatabaseCorruptionError,
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_readonly,
    open_write,
    validate_database_pair,
)
from app.services.admin_auth import hash_password, validate_new_password, verify_password
from app.services.backups import create_backup_pair
from app.services.employee import (
    ADMIN_FULL_NAME_CONFIG_KEY,
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
from app.services.reminders import (
    REMINDER_TEMPLATE_EXPIRING_KEY,
    REMINDER_TEMPLATE_OVERDUE_KEY,
    ReminderTemplateValidationError,
    ReminderWriteError as ReminderServiceWriteError,
    get_reminder_templates,
    validate_reminder_template,
)
from app.services.sizes import SizeKey, size_key, size_label
from app.services.ui_preferences import (
    DEFAULT_UI_PREFERENCES,
    DISPLAY_DATE_WORDS_KEY,
    SHOW_UI_HINTS_KEY,
    UI_PREFERENCE_KEYS,
    UiPreferenceError,
    encode_config_bool,
    get_ui_preferences,
    validate_ui_preferences,
)
from app.template_fields import TEMPLATE_FIELD_DICTIONARY


BUSY_MESSAGE = "База сейчас занята другим сотрудником. Повторите позже."
UNCERTAIN_MESSAGE = (
    "Не удалось подтвердить результат записи. Обновите настройки и проверьте данные."
)
NUMERIC_CONFIG_KEYS = frozenset(
    {"expiring_soon_days", "deposit_amount_minor", "abs_session_minutes"}
)
EDITABLE_CONFIG_KEYS = NUMERIC_CONFIG_KEYS | UI_PREFERENCE_KEYS
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


def _cell_number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise AdminValidationError("Номер ячейки должен быть целым числом.")
    normalized = str(value).strip()
    if not normalized.isdecimal():
        raise AdminValidationError("Номер ячейки должен быть целым числом.")
    number = int(normalized)
    if not 1 <= number <= 999_999:
        raise AdminValidationError("Номер ячейки должен быть от 1 до 999999.")
    canonical = str(number)
    if normalized != canonical:
        raise AdminValidationError(
            "Введите номер ячейки без пробелов и ведущих нулей."
        )
    return canonical


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


def get_admin_identity(settings: Settings) -> dict[str, Any]:
    """Return non-secret startup information about the administrator."""

    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            password_configured = connection.execute(
                "SELECT 1 FROM admin_credentials WHERE id = 1"
            ).fetchone() is not None
            row = connection.execute(
                "SELECT value FROM config WHERE key = ?",
                (ADMIN_FULL_NAME_CONFIG_KEY,),
            ).fetchone()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    full_name = None
    if row is not None:
        try:
            full_name = validate_employee_full_name(row["value"])
        except EmployeeProfileError as exc:
            raise AdminWriteError("ФИО администратора повреждено.") from exc
    return {
        "configured": password_configured and full_name is not None,
        "password_configured": password_configured,
        "profile_configured": full_name is not None,
        "full_name": full_name,
    }


def setup_admin_identity(
    settings: Settings,
    *,
    operation_id: object,
    full_name: object,
    password: object,
    occurred_at: datetime,
) -> AdminWriteResult:
    """Save the administrator name once and create or verify its password."""

    normalized_operation = _operation_id(operation_id)
    try:
        normalized_name = validate_employee_full_name(full_name)
    except EmployeeProfileError as exc:
        raise AdminValidationError(str(exc)) from exc
    normalized_password = validate_new_password(password)
    timestamp = _timestamp(occurred_at)
    action = "admin.identity.created"
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            existing_name_row = connection.execute(
                "SELECT value FROM config WHERE key = ?",
                (ADMIN_FULL_NAME_CONFIG_KEY,),
            ).fetchone()
            password_row = connection.execute(
                "SELECT password_hash FROM admin_credentials WHERE id = 1"
            ).fetchone()
            if _existing_operation(connection, normalized_operation, action):
                if (
                    existing_name_row is None
                    or validate_employee_full_name(existing_name_row["value"])
                    != normalized_name
                    or password_row is None
                    or not verify_password(
                        normalized_password, password_row["password_hash"]
                    )
                ):
                    raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
                connection.rollback()
                return AdminWriteResult(True, False, None)
            if existing_name_row is not None:
                raise AdminConflictError(
                    "ФИО администратора уже настроено. Войдите под ним."
                )
            if password_row is None:
                connection.execute(
                    """
                    INSERT INTO admin_credentials(id, password_hash, changed_at)
                    VALUES(1, ?, ?)
                    """,
                    (hash_password(normalized_password), timestamp),
                )
            elif not verify_password(
                normalized_password, password_row["password_hash"]
            ):
                raise AdminValidationError(
                    "Неверный действующий административный пароль."
                )
            connection.execute(
                """
                INSERT INTO config(key, value, updated_at, updated_by)
                VALUES(?, ?, ?, ?)
                """,
                (
                    ADMIN_FULL_NAME_CONFIG_KEY,
                    normalized_name,
                    timestamp,
                    normalized_name,
                ),
            )
            connection.execute(
                """
                INSERT INTO config(key, value, updated_at, updated_by)
                VALUES('admin_access_mode', ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by
                """,
                (ACCESS_MODE_PASSWORD, timestamp, normalized_name),
            )
            connection.execute(
                """
                INSERT INTO archive.log(
                    log_id, operation_id, occurred_at, employee, action,
                    contract_id, cell_number, changes_json
                ) VALUES(?, ?, ?, ?, ?, NULL, NULL, ?)
                """,
                (
                    str(uuid4()),
                    normalized_operation,
                    timestamp,
                    normalized_name,
                    action,
                    json.dumps(
                        {"full_name_configured": True},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT value FROM config WHERE key = ?",
                (ADMIN_FULL_NAME_CONFIG_KEY,),
            ).fetchone()
            if saved is None or str(saved["value"]) != normalized_name:
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
            backup_created, warning = _backup_after_commit(
                connection,
                settings,
                operation_id=normalized_operation,
                occurred_at=occurred_at,
            )
            return AdminWriteResult(False, backup_created, warning)
    except (
        AdminValidationError,
        AdminConflictError,
        AdminWriteUncertainError,
    ):
        raise
    except DatabaseCorruptionError as exc:
        raise AdminNetworkError(str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {
            "opening",
            "begin",
            "transaction",
        }:
            raise AdminBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminWriteError(
            "ФИО администратора не сохранено. Изменения отменены."
        ) from exc


def get_admin_access_mode(settings: Settings) -> str:
    """Read the access mode without forcing password setup on an empty database."""
    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            row = connection.execute(
                "SELECT value FROM config WHERE key = 'admin_access_mode'"
            ).fetchone()
            password_exists = connection.execute(
                "SELECT 1 FROM admin_credentials WHERE id = 1"
            ).fetchone() is not None
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    if row is None:
        return (
            ACCESS_MODE_PASSWORD
            if password_exists
            else ACCESS_MODE_ACKNOWLEDGEMENT
        )
    mode = str(row["value"])
    if mode not in ADMIN_ACCESS_MODES:
        raise AdminWriteError("Режим доступа к настройкам повреждён.")
    if mode == ACCESS_MODE_PASSWORD and not password_exists:
        return ACCESS_MODE_ACKNOWLEDGEMENT
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
                connection.execute(
                    """INSERT INTO config(key, value, updated_at, updated_by)
                       VALUES('admin_access_mode', ?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET
                           value=excluded.value,
                           updated_at=excluded.updated_at,
                           updated_by=excluded.updated_by""",
                    (
                        ACCESS_MODE_PASSWORD,
                        timestamp,
                        normalized_employee,
                    ),
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
    except DatabaseCorruptionError as exc:
        raise AdminNetworkError(str(exc)) from exc
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
            config_placeholders = ",".join("?" for _ in EDITABLE_CONFIG_KEYS)
            config_rows = connection.execute(
                f"""SELECT key, value FROM config
                    WHERE key IN ({config_placeholders}) ORDER BY key""",
                tuple(sorted(EDITABLE_CONFIG_KEYS)),
            ).fetchall()
            ui_preferences = get_ui_preferences(connection)
            tariff_rows = connection.execute(
                """SELECT height_mm, width_mm, depth_mm,
                          period_from_days, period_to_days,
                          price_per_day_minor
                   FROM tariffs
                   ORDER BY height_mm, width_mm, depth_mm, period_from_days"""
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
            password_configured = connection.execute(
                "SELECT 1 FROM admin_credentials WHERE id = 1"
            ).fetchone() is not None
            penalty = get_penalty_settings(connection)
            reminder_templates = get_reminder_templates(connection)
            cell_rows = connection.execute(
                """
                SELECT cells.number, cells.height_mm,
                       COALESCE(cells.width_mm, defaults.width_mm) AS width_mm,
                       COALESCE(cells.depth_mm, defaults.depth_mm) AS depth_mm,
                       cells.is_active,
                       cells.retired_at, cells.retired_by,
                       cells.retirement_reason,
                       contracts.contract_id,
                       cell_blocks.block_kind
                FROM cells CROSS JOIN vault_defaults defaults
                LEFT JOIN contracts ON contracts.cell_number = cells.number
                LEFT JOIN cell_blocks ON cell_blocks.cell_number = cells.number
                WHERE defaults.id = 1
                ORDER BY CAST(cells.number AS INTEGER), cells.number
                """
            ).fetchall()
            allowed_cell_sizes = [
                {
                    "height_mm": int(row["height_mm"]),
                    "width_mm": int(row["width_mm"]),
                    "depth_mm": int(row["depth_mm"]),
                }
                for row in connection.execute(
                    """
                    SELECT DISTINCT height_mm, width_mm, depth_mm
                    FROM tariffs
                    ORDER BY height_mm, width_mm, depth_mm
                    """
                ).fetchall()
            ]
        with open_readonly(
            paths.archive, busy_timeout_ms=settings.busy_timeout_ms
        ) as archive_connection:
            cell_creation_logs = archive_connection.execute(
                """
                SELECT action, cell_number, changes_json
                FROM log
                WHERE action IN ('admin.cell.created', 'admin.cells.created')
                """
            ).fetchall()
    except PenaltyRateConfigurationError as exc:
        raise AdminWriteError(str(exc)) from exc
    except (ReminderServiceWriteError, UiPreferenceError) as exc:
        raise AdminWriteError(str(exc)) from exc
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    try:
        stored_config = {str(row["key"]): row["value"] for row in config_rows}
        config: dict[str, int | bool] = {
            key: int(stored_config[key]) for key in NUMERIC_CONFIG_KEYS
        }
    except (TypeError, ValueError) as exc:
        raise AdminWriteError("Обязательные настройки отсутствуют или повреждены.") from exc
    except KeyError as exc:
        raise AdminWriteError(
            "Обязательные настройки отсутствуют или повреждены."
        ) from exc
    config.update(ui_preferences)
    try:
        employees = decode_employee_config(
            None if employee_row is None else employee_row["value"]
        )
    except EmployeeProfileError as exc:
        raise AdminWriteError(str(exc)) from exc
    templates = []
    admin_created_numbers: set[str] = set()
    for row in cell_creation_logs:
        if row["action"] == "admin.cell.created" and row["cell_number"] is not None:
            admin_created_numbers.add(str(row["cell_number"]))
            continue
        try:
            data = json.loads(str(row["changes_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
        for cell in data.get("cells", []):
            if isinstance(cell, dict) and cell.get("number") is not None:
                admin_created_numbers.add(str(cell["number"]))
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
        "reminder_templates": reminder_templates,
        "template_fields": list(TEMPLATE_FIELD_DICTIONARY),
        "cells": {
            "count": sum(1 for row in cell_rows if int(row["is_active"]) == 1),
            "retired_count": sum(
                1 for row in cell_rows if int(row["is_active"]) == 0
            ),
            "allowed_sizes": allowed_cell_sizes,
            "items": [
                {
                    "number": str(row["number"]),
                    "height_mm": int(row["height_mm"]),
                    "width_mm": int(row["width_mm"]),
                    "depth_mm": int(row["depth_mm"]),
                    "is_active": bool(row["is_active"]),
                    "is_occupied": (
                        row["contract_id"] is not None
                        or row["block_kind"] is not None
                    ),
                    "retired_at": row["retired_at"],
                    "retired_by": row["retired_by"],
                    "retirement_reason": row["retirement_reason"],
                    "created_in_admin": str(row["number"]) in admin_created_numbers,
                }
                for row in cell_rows
            ],
        },
        "access_mode": get_admin_access_mode(settings),
        "password_configured": password_configured,
    }


def update_reminder_templates(
    settings: Settings,
    *,
    payload: object,
    employee: object,
    occurred_at: datetime,
) -> AdminWriteResult:
    if not isinstance(payload, dict) or set(payload) != {
        "operation_id", "templates"
    }:
        raise AdminValidationError(
            "Переданы неизвестные или неполные шаблоны WhatsApp."
        )
    raw_templates = payload["templates"]
    if not isinstance(raw_templates, dict) or set(raw_templates) != {
        "expiring", "overdue"
    }:
        raise AdminValidationError(
            "Нужны отдельные шаблоны для истекающей и просроченной аренды."
        )
    try:
        templates = {
            "expiring": validate_reminder_template(
                raw_templates["expiring"], label="Истекающая аренда"
            ),
            "overdue": validate_reminder_template(
                raw_templates["overdue"], label="Просроченная аренда"
            ),
        }
    except ReminderTemplateValidationError as exc:
        raise AdminValidationError(str(exc)) from exc
    operation_id = _operation_id(payload["operation_id"])
    employee_name = _employee(employee)
    timestamp = _timestamp(occurred_at)
    action = "admin.reminder_templates.updated"
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            if _existing_operation(connection, operation_id, action):
                connection.rollback()
                return AdminWriteResult(True, False, None)
            old_templates = get_reminder_templates(connection)
            for key, value in (
                (REMINDER_TEMPLATE_EXPIRING_KEY, templates["expiring"]),
                (REMINDER_TEMPLATE_OVERDUE_KEY, templates["overdue"]),
            ):
                connection.execute(
                    """INSERT INTO config(key, value, updated_at, updated_by)
                       VALUES(?, ?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET
                           value=excluded.value,
                           updated_at=excluded.updated_at,
                           updated_by=excluded.updated_by""",
                    (key, value, timestamp, employee_name),
                )
            connection.execute(
                """INSERT INTO archive.log(
                       log_id, operation_id, occurred_at, employee, action,
                       contract_id, cell_number, changes_json
                   ) VALUES(?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (
                    str(uuid4()),
                    operation_id,
                    timestamp,
                    employee_name,
                    action,
                    json.dumps(
                        {
                            "expiring": {
                                "old": old_templates["expiring"],
                                "new": templates["expiring"],
                            },
                            "overdue": {
                                "old": old_templates["overdue"],
                                "new": templates["overdue"],
                            },
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved_templates = get_reminder_templates(connection)
            if saved_templates != templates:
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
            backup_created, warning = _backup_after_commit(
                connection,
                settings,
                operation_id=operation_id,
                occurred_at=occurred_at,
            )
            return AdminWriteResult(False, backup_created, warning)
    except (
        AdminValidationError,
        AdminConflictError,
        AdminWriteUncertainError,
    ):
        raise
    except ReminderServiceWriteError as exc:
        raise AdminWriteError(str(exc)) from exc
    except DatabaseCorruptionError as exc:
        raise AdminNetworkError(str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {
            "opening", "begin", "transaction"
        }:
            raise AdminBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminWriteError(
            "Шаблоны WhatsApp не сохранены. Изменения отменены."
        ) from exc


def add_admin_cell(
    settings: Settings,
    *,
    payload: object,
    employee: object,
    occurred_at: datetime,
) -> tuple[AdminWriteResult, dict[str, int | str]]:
    if not isinstance(payload, dict) or set(payload) != {
        "operation_id", "number", "height_mm"
    }:
        raise AdminValidationError(
            "Переданы неизвестные или неполные данные новой ячейки."
        )
    operation_id = _operation_id(payload["operation_id"])
    number = _cell_number(payload["number"])
    height_mm = _integer(
        payload["height_mm"], "Высота", minimum=1, maximum=10_000
    )
    employee_name = _employee(employee)
    timestamp = _timestamp(occurred_at)
    action = "admin.cell.created"
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            if _existing_operation(connection, operation_id, action):
                saved = connection.execute(
                    "SELECT number, height_mm FROM cells WHERE number = ?",
                    (number,),
                ).fetchone()
                connection.rollback()
                if saved is None or int(saved["height_mm"]) != height_mm:
                    raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
                return (
                    AdminWriteResult(True, False, None),
                    {"number": number, "height_mm": height_mm},
                )
            existing = connection.execute(
                "SELECT height_mm FROM cells WHERE number = ?", (number,)
            ).fetchone()
            if existing is not None:
                raise AdminConflictError(
                    f"Ячейка №{number} уже существует."
                )
            tariff_exists = connection.execute(
                "SELECT 1 FROM tariffs WHERE height_mm = ? LIMIT 1",
                (height_mm,),
            ).fetchone()
            if tariff_exists is None:
                raise AdminValidationError(
                    "Для выбранной высоты не настроены тарифы."
                )
            connection.execute(
                """
                INSERT INTO cells(number, height_mm, width_mm, depth_mm)
                VALUES(?, ?, NULL, NULL)
                """,
                (number, height_mm),
            )
            connection.execute(
                """INSERT INTO archive.log(
                       log_id, operation_id, occurred_at, employee, action,
                       contract_id, cell_number, changes_json
                   ) VALUES(?, ?, ?, ?, ?, NULL, ?, ?)""",
                (
                    str(uuid4()),
                    operation_id,
                    timestamp,
                    employee_name,
                    action,
                    number,
                    json.dumps(
                        {"height_mm": height_mm},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT number, height_mm FROM cells WHERE number = ?",
                (number,),
            ).fetchone()
            if saved is None or int(saved["height_mm"]) != height_mm:
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
            backup_created, warning = _backup_after_commit(
                connection,
                settings,
                operation_id=operation_id,
                occurred_at=occurred_at,
            )
            return (
                AdminWriteResult(False, backup_created, warning),
                {"number": number, "height_mm": height_mm},
            )
    except (
        AdminValidationError,
        AdminConflictError,
        AdminWriteUncertainError,
    ):
        raise
    except DatabaseCorruptionError as exc:
        raise AdminNetworkError(str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.IntegrityError as exc:
        if "unique" in str(exc).lower() or "primary key" in str(exc).lower():
            raise AdminConflictError(
                f"Ячейка №{number} уже существует."
            ) from exc
        raise AdminWriteError(
            "Новую ячейку не удалось сохранить. Изменения отменены."
        ) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {
            "opening", "begin", "transaction"
        }:
            raise AdminBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminWriteError(
            "Новую ячейку не удалось сохранить. Изменения отменены."
        ) from exc


def _stored_tariff_periods(
    connection: sqlite3.Connection,
) -> tuple[tuple[int, int | None], ...]:
    rows = connection.execute(
        """
        SELECT DISTINCT period_from_days, period_to_days
        FROM tariffs
        ORDER BY period_from_days
        """,
    ).fetchall()
    periods = tuple(
        (
            int(row["period_from_days"]),
            None if row["period_to_days"] is None else int(row["period_to_days"]),
        )
        for row in rows
    )
    expected = 1
    for index, (start, end) in enumerate(periods):
        if start != expected:
            raise AdminWriteError("Тарифные диапазоны повреждены.")
        if index == len(periods) - 1:
            if end is not None:
                raise AdminWriteError(
                    "Последний тарифный диапазон должен быть открытым."
                )
        elif end is None:
            raise AdminWriteError("Открытый тарифный диапазон должен быть последним.")
        else:
            expected = end + 1
    if not periods:
        raise AdminWriteError("Тарифные диапазоны отсутствуют.")
    return periods


def _size_has_complete_tariffs(
    connection: sqlite3.Connection, size: SizeKey
) -> bool:
    rows = connection.execute(
        """
        SELECT period_from_days, period_to_days
        FROM tariffs
        WHERE height_mm=? AND width_mm=? AND depth_mm=?
        ORDER BY period_from_days
        """,
        size,
    ).fetchall()
    periods = tuple(
        (
            int(row["period_from_days"]),
            None if row["period_to_days"] is None else int(row["period_to_days"]),
        )
        for row in rows
    )
    return periods == _stored_tariff_periods(connection)


def add_admin_cells_batch(
    settings: Settings,
    *,
    payload: object,
    employee: object,
    occurred_at: datetime,
) -> tuple[AdminWriteResult, list[dict[str, int | str]]]:
    """Create a reviewed batch atomically; one invalid row cancels the batch."""

    if not isinstance(payload, dict) or set(payload) != {
        "operation_id", "cells", "new_tariffs", "new_penalty_rates"
    }:
        raise AdminValidationError(
            "Передан неизвестный или неполный список новых ячеек."
        )
    raw_cells = payload["cells"]
    if not isinstance(raw_cells, list) or not 1 <= len(raw_cells) <= 200:
        raise AdminValidationError("Добавьте от 1 до 200 ячеек в один список.")
    cells: list[dict[str, int | str]] = []
    numbers: set[str] = set()
    for index, raw_cell in enumerate(raw_cells, start=1):
        if not isinstance(raw_cell, dict) or set(raw_cell) != {
            "number", "height_mm", "width_mm", "depth_mm"
        }:
            raise AdminValidationError(f"Строка {index} заполнена не полностью.")
        number = _cell_number(raw_cell["number"])
        if number in numbers:
            raise AdminValidationError(
                f"Ячейка №{number} повторяется в подготовленном списке."
            )
        numbers.add(number)
        cells.append(
            {
                "number": number,
                "height_mm": _integer(
                    raw_cell["height_mm"],
                    f"Высота в строке {index}",
                    minimum=1,
                    maximum=10_000,
                ),
                "width_mm": _integer(
                    raw_cell["width_mm"], f"Ширина в строке {index}",
                    minimum=1, maximum=10_000,
                ),
                "depth_mm": _integer(
                    raw_cell["depth_mm"], f"Глубина в строке {index}",
                    minimum=1, maximum=10_000,
                ),
            }
        )
    new_tariffs = _validate_tariffs(payload["new_tariffs"], allow_empty=True)
    raw_penalties = payload["new_penalty_rates"]
    if not isinstance(raw_penalties, list):
        raise AdminValidationError("Неверные штрафные ставки новых размеров.")
    new_penalties: dict[SizeKey, int] = {}
    for row in raw_penalties:
        if not isinstance(row, dict) or set(row) != {
            "height_mm", "width_mm", "depth_mm", "price_per_day_minor"
        }:
            raise AdminValidationError("Неверная штрафная ставка нового размера.")
        size = (
            _integer(row["height_mm"], "Высота", minimum=1, maximum=10_000),
            _integer(row["width_mm"], "Ширина", minimum=1, maximum=10_000),
            _integer(row["depth_mm"], "Глубина", minimum=1, maximum=10_000),
        )
        if size in new_penalties:
            raise AdminValidationError("Штрафная ставка нового размера повторяется.")
        new_penalties[size] = _integer(
            row["price_per_day_minor"], "Штрафная ставка",
            minimum=0, maximum=MAX_MONEY_VALUE,
        )

    operation_id = _operation_id(payload["operation_id"])
    employee_name = _employee(employee)
    timestamp = _timestamp(occurred_at)
    action = "admin.cells.created"
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            if _existing_operation(connection, operation_id, action):
                for cell in cells:
                    saved = connection.execute(
                        """
                        SELECT height_mm, width_mm, depth_mm FROM cells
                        WHERE number = ? AND is_active = 1
                        """,
                        (cell["number"],),
                    ).fetchone()
                    if saved is None or (
                        int(saved["height_mm"]),
                        int(saved["width_mm"]),
                        int(saved["depth_mm"]),
                    ) != (
                        cell["height_mm"], cell["width_mm"], cell["depth_mm"]
                    ):
                        raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
                connection.rollback()
                return AdminWriteResult(True, False, None), cells

            existing = connection.execute(
                f"""
                SELECT number FROM cells
                WHERE number IN ({','.join('?' for _ in cells)})
                ORDER BY CAST(number AS INTEGER), number
                """,
                tuple(cell["number"] for cell in cells),
            ).fetchall()
            if existing:
                joined = ", ".join(str(row["number"]) for row in existing)
                raise AdminConflictError(
                    f"Эти номера уже есть в базе: {joined}."
                )
            periods = _stored_tariff_periods(connection)
            draft_sizes = {
                (
                    int(cell["height_mm"]),
                    int(cell["width_mm"]),
                    int(cell["depth_mm"]),
                )
                for cell in cells
            }
            existing_sizes = {
                (int(row[0]), int(row[1]), int(row[2]))
                for row in connection.execute(
                    "SELECT DISTINCT height_mm, width_mm, depth_mm FROM tariffs"
                ).fetchall()
            }
            required_new_sizes = draft_sizes - existing_sizes
            supplied_new_sizes = {
                (
                    int(row["height_mm"]),
                    int(row["width_mm"]),
                    int(row["depth_mm"]),
                )
                for row in new_tariffs
            }
            if supplied_new_sizes != required_new_sizes:
                raise AdminValidationError(
                    "Заполните тарифы для каждого совершенно нового размера."
                )
            for size in required_new_sizes:
                rows = [
                    row for row in new_tariffs
                    if (
                        int(row["height_mm"]), int(row["width_mm"]),
                        int(row["depth_mm"])
                    ) == size
                ]
                if tuple(
                    (int(row["period_from_days"]), row["period_to_days"])
                    for row in rows
                ) != periods:
                    raise AdminValidationError(
                        f"Тарифы размера {size_label(size)} не совпадают с диапазонами."
                    )
            old_penalty = get_penalty_settings(connection)
            manual_rates = {
                (
                    int(row["height_mm"]), int(row["width_mm"]),
                    int(row["depth_mm"])
                ): int(row["price_per_day_minor"])
                for row in old_penalty["manual_rates"]
            }
            if old_penalty["mode"] == "manual" and set(new_penalties) != required_new_sizes:
                raise AdminValidationError(
                    "Укажите ручную штрафную ставку для каждого нового размера."
                )
            if old_penalty["mode"] != "manual" and set(new_penalties) - required_new_sizes:
                raise AdminValidationError("Передана лишняя штрафная ставка.")
            for size in required_new_sizes:
                first_rate = next(
                    int(row["price_per_day_minor"])
                    for row in new_tariffs
                    if (
                        int(row["height_mm"]), int(row["width_mm"]),
                        int(row["depth_mm"]), int(row["period_from_days"])
                    ) == (*size, 1)
                )
                manual_rates[size] = new_penalties.get(size, first_rate)
            if new_tariffs:
                connection.executemany(
                    """
                    INSERT INTO tariffs(
                        height_mm, width_mm, depth_mm, period_from_days,
                        period_to_days, price_per_day_minor, updated_at, updated_by
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            row["height_mm"], row["width_mm"], row["depth_mm"],
                            row["period_from_days"], row["period_to_days"],
                            row["price_per_day_minor"], timestamp, employee_name,
                        )
                        for row in new_tariffs
                    ],
                )
                connection.execute(
                    """
                    UPDATE config SET value=?, updated_at=?, updated_by=?
                    WHERE key=?
                    """,
                    (
                        encode_manual_rates(manual_rates), timestamp,
                        employee_name, PENALTY_MANUAL_RATES_KEY,
                    ),
                )
            connection.executemany(
                """
                INSERT INTO cells(
                    number, height_mm, width_mm, depth_mm, is_active
                ) VALUES(?, ?, ?, ?, 1)
                """,
                [
                    (
                        cell["number"], cell["height_mm"],
                        cell["width_mm"], cell["depth_mm"],
                    )
                    for cell in cells
                ],
            )
            connection.execute(
                """INSERT INTO archive.log(
                       log_id, operation_id, occurred_at, employee, action,
                       contract_id, cell_number, changes_json
                   ) VALUES(?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (
                    str(uuid4()),
                    operation_id,
                    timestamp,
                    employee_name,
                    action,
                    json.dumps(
                        {"cells": cells, "new_tariffs": new_tariffs},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved_count = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*) FROM cells
                    WHERE is_active = 1
                      AND number IN ({','.join('?' for _ in cells)})
                    """,
                    tuple(cell["number"] for cell in cells),
                ).fetchone()[0]
            )
            if saved_count != len(cells):
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
            backup_created, warning = _backup_after_commit(
                connection,
                settings,
                operation_id=operation_id,
                occurred_at=occurred_at,
            )
            return AdminWriteResult(False, backup_created, warning), cells
    except (AdminValidationError, AdminConflictError, AdminWriteUncertainError):
        raise
    except DatabaseCorruptionError as exc:
        raise AdminNetworkError(str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.IntegrityError as exc:
        raise AdminConflictError(
            "Один из номеров уже сохранён другим сотрудником. Обновите список."
        ) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {
            "opening", "begin", "transaction"
        }:
            raise AdminBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminWriteError(
            "Список ячеек не сохранён. Все изменения отменены."
        ) from exc


def _cell_was_created_in_admin(
    connection: sqlite3.Connection, number: str
) -> bool:
    direct = connection.execute(
        """
        SELECT 1 FROM archive.log
        WHERE action = 'admin.cell.created' AND cell_number = ?
        LIMIT 1
        """,
        (number,),
    ).fetchone()
    if direct is not None:
        return True
    rows = connection.execute(
        """
        SELECT changes_json FROM archive.log
        WHERE action = 'admin.cells.created'
        """
    ).fetchall()
    for row in rows:
        try:
            data = json.loads(str(row["changes_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
        if any(
            isinstance(cell, dict) and str(cell.get("number")) == number
            for cell in data.get("cells", [])
        ):
            return True
    return False


def update_admin_cell_lifecycle(
    settings: Settings,
    *,
    payload: object,
    employee: object,
    occurred_at: datetime,
) -> tuple[AdminWriteResult, dict[str, Any]]:
    """Retire, restore, or delete an erroneous never-used administrative cell."""

    if not isinstance(payload, dict) or set(payload) != {
        "operation_id", "number", "action", "reason"
    }:
        raise AdminValidationError("Переданы неполные данные изменения ячейки.")
    operation_id = _operation_id(payload["operation_id"])
    number = _cell_number(payload["number"])
    action_code = payload["action"]
    if action_code not in {"retire", "restore", "delete"}:
        raise AdminValidationError("Неизвестное действие с ячейкой.")
    reason = " ".join(str(payload["reason"] or "").split())
    if action_code == "retire" and not 3 <= len(reason) <= 300:
        raise AdminValidationError("Укажите причину вывода из эксплуатации.")
    if action_code != "retire":
        reason = ""
    employee_name = _employee(employee)
    timestamp = _timestamp(occurred_at)
    audit_action = f"admin.cell.{action_code}d"
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            if _existing_operation(connection, operation_id, audit_action):
                connection.rollback()
                return (
                    AdminWriteResult(True, False, None),
                    {"number": number, "action": action_code},
                )
            cell = connection.execute(
                """
                SELECT cells.height_mm,
                       COALESCE(cells.width_mm, defaults.width_mm) AS width_mm,
                       COALESCE(cells.depth_mm, defaults.depth_mm) AS depth_mm,
                       cells.is_active,
                       contracts.contract_id, cell_blocks.block_kind
                FROM cells CROSS JOIN vault_defaults defaults
                LEFT JOIN contracts ON contracts.cell_number = cells.number
                LEFT JOIN cell_blocks ON cell_blocks.cell_number = cells.number
                WHERE cells.number = ? AND defaults.id = 1
                """,
                (number,),
            ).fetchone()
            if cell is None:
                raise AdminConflictError(f"Ячейка №{number} не найдена.")
            occupied = (
                cell["contract_id"] is not None or cell["block_kind"] is not None
            )
            if occupied:
                raise AdminConflictError(
                    "Занятую или заблокированную ячейку изменять нельзя."
                )
            if action_code == "retire":
                if not bool(cell["is_active"]):
                    raise AdminConflictError("Ячейка уже выведена из эксплуатации.")
                connection.execute(
                    """
                    UPDATE cells
                    SET is_active=0, retired_at=?, retired_by=?,
                        retirement_reason=?
                    WHERE number=?
                    """,
                    (timestamp, employee_name, reason, number),
                )
            elif action_code == "restore":
                if bool(cell["is_active"]):
                    raise AdminConflictError("Ячейка уже используется.")
                if not _size_has_complete_tariffs(
                    connection,
                    (
                        int(cell["height_mm"]), int(cell["width_mm"]),
                        int(cell["depth_mm"]),
                    ),
                ):
                    raise AdminConflictError(
                        "Перед восстановлением настройте тарифы этой высоты."
                    )
                connection.execute(
                    """
                    UPDATE cells
                    SET is_active=1, retired_at=NULL, retired_by=NULL,
                        retirement_reason=NULL
                    WHERE number=?
                    """,
                    (number,),
                )
            else:
                if not _cell_was_created_in_admin(connection, number):
                    raise AdminConflictError(
                        "Удалить можно только ячейку, добавленную через настройки."
                    )
                has_history = connection.execute(
                    """
                    SELECT 1 FROM archive.contracts_archive
                    WHERE cell_number=?
                    UNION ALL
                    SELECT 1 FROM archive.renewals
                    WHERE cell_number=?
                    LIMIT 1
                    """,
                    (number, number),
                ).fetchone()
                if has_history is not None:
                    raise AdminConflictError(
                        "У ячейки есть история договоров. Используйте вывод "
                        "из эксплуатации."
                    )
                connection.execute("DELETE FROM cells WHERE number=?", (number,))
            connection.execute(
                """INSERT INTO archive.log(
                       log_id, operation_id, occurred_at, employee, action,
                       contract_id, cell_number, changes_json
                   ) VALUES(?, ?, ?, ?, ?, NULL, ?, ?)""",
                (
                    str(uuid4()),
                    operation_id,
                    timestamp,
                    employee_name,
                    audit_action,
                    number,
                    json.dumps(
                        {"action": action_code, "reason": reason or None},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT is_active FROM cells WHERE number=?", (number,)
            ).fetchone()
            expected_active = {"retire": 0, "restore": 1, "delete": None}[action_code]
            if (
                (expected_active is None and saved is not None)
                or (
                    expected_active is not None
                    and (saved is None or int(saved["is_active"]) != expected_active)
                )
            ):
                raise AdminWriteUncertainError(UNCERTAIN_MESSAGE)
            backup_created, warning = _backup_after_commit(
                connection,
                settings,
                operation_id=operation_id,
                occurred_at=occurred_at,
            )
            return (
                AdminWriteResult(False, backup_created, warning),
                {"number": number, "action": action_code},
            )
    except (AdminValidationError, AdminConflictError, AdminWriteUncertainError):
        raise
    except DatabaseCorruptionError as exc:
        raise AdminNetworkError(str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {
            "opening", "begin", "transaction"
        }:
            raise AdminBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}:
            raise AdminWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise AdminWriteError("Ячейку не удалось изменить.") from exc


def _validate_config(value: object) -> dict[str, int | bool]:
    if not isinstance(value, dict) or set(value) != EDITABLE_CONFIG_KEYS:
        raise AdminValidationError(
            "Разрешено изменять только утверждённый набор общих настроек."
        )
    config: dict[str, int | bool] = {
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
        "abs_session_minutes": _integer(
            value["abs_session_minutes"],
            "Длительность сеанса АБС",
            minimum=1,
            maximum=1_440,
        ),
    }
    try:
        config.update(validate_ui_preferences(value))
    except UiPreferenceError as exc:
        raise AdminValidationError(str(exc)) from exc
    return config


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
    except DatabaseCorruptionError as exc:
        raise AdminNetworkError(str(exc)) from exc
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
    except DatabaseCorruptionError as exc:
        raise AdminNetworkError(str(exc)) from exc
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


def _validate_tariffs(
    value: object, *, allow_empty: bool = False
) -> list[dict[str, int | None]]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise AdminValidationError("Передайте полный набор тарифов.")
    result: list[dict[str, int | None]] = []
    allowed = {
        "height_mm",
        "width_mm",
        "depth_mm",
        "period_from_days",
        "period_to_days",
        "price_per_day_minor",
    }
    seen_keys: set[tuple[int, int, int, int]] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != allowed:
            raise AdminValidationError("Строка тарифа содержит неизвестные поля.")
        height = _integer(raw["height_mm"], "Высота", minimum=1, maximum=10_000)
        width = _integer(raw["width_mm"], "Ширина", minimum=1, maximum=10_000)
        depth = _integer(raw["depth_mm"], "Глубина", minimum=1, maximum=10_000)
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
        key = (height, width, depth, start)
        if key in seen_keys:
            raise AdminValidationError("В наборе есть повторяющаяся строка тарифа.")
        seen_keys.add(key)
        result.append(
            {
                "height_mm": height,
                "width_mm": width,
                "depth_mm": depth,
                "period_from_days": start,
                "period_to_days": end,
                "price_per_day_minor": rate,
            }
        )
    by_size: dict[SizeKey, list[dict[str, int | None]]] = {}
    for row in result:
        size = (
            int(row["height_mm"]),
            int(row["width_mm"]),
            int(row["depth_mm"]),
        )
        by_size.setdefault(size, []).append(row)
    expected_periods: tuple[tuple[int, int | None], ...] | None = None
    for size, rows in by_size.items():
        rows.sort(key=lambda row: int(row["period_from_days"]))
        expected_start = 1
        for index, row in enumerate(rows):
            if row["period_from_days"] != expected_start:
                raise AdminValidationError(
                    f"Тарифы размера {size_label(size)} содержат пропуск или пересечение."
                )
            end = row["period_to_days"]
            if index < len(rows) - 1 and end is None:
                    raise AdminValidationError(
                        f"У тарифа размера {size_label(size)} открытый диапазон должен быть последним."
                )
            if index == len(rows) - 1:
                if end is not None:
                    raise AdminValidationError(
                        f"Последний тариф размера {size_label(size)} должен действовать без ограничения."
                    )
            else:
                expected_start = int(end) + 1
        periods = tuple(
            (int(row["period_from_days"]), row["period_to_days"])
            for row in rows
        )
        if expected_periods is None:
            expected_periods = periods
        elif periods != expected_periods:
            raise AdminValidationError(
                "Для всех размеров должен использоваться одинаковый набор диапазонов."
            )
    return sorted(
        result,
        key=lambda row: (
            int(row["height_mm"]),
            int(row["width_mm"]),
            int(row["depth_mm"]),
            int(row["period_from_days"]),
        ),
    )


def _validate_penalty(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"mode", "manual_rates"}:
        raise AdminValidationError("Переданы неизвестные или неполные настройки штрафа.")
    mode = value["mode"]
    if not isinstance(mode, str) or mode not in PENALTY_RATE_MODES:
        raise AdminValidationError("Выберите способ расчёта штрафной ставки.")
    raw_rates = value["manual_rates"]
    if not isinstance(raw_rates, list) or not raw_rates:
        raise AdminValidationError("Передайте ручные штрафные ставки по всем размерам.")
    rates: dict[SizeKey, int] = {}
    for raw in raw_rates:
        if not isinstance(raw, dict) or set(raw) != {
            "height_mm",
            "width_mm",
            "depth_mm",
            "price_per_day_minor",
        }:
            raise AdminValidationError("Ручная штрафная ставка содержит неизвестные поля.")
        height = _integer(raw["height_mm"], "Высота", minimum=1, maximum=10_000)
        width = _integer(raw["width_mm"], "Ширина", minimum=1, maximum=10_000)
        depth = _integer(raw["depth_mm"], "Глубина", minimum=1, maximum=10_000)
        rate = _integer(
            raw["price_per_day_minor"],
            "Ручная штрафная ставка",
            minimum=0,
            maximum=MAX_MONEY_VALUE,
        )
        size = (height, width, depth)
        if size in rates:
            raise AdminValidationError("Ручная штрафная ставка одного размера повторяется.")
        rates[size] = rate
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
            sizes = {
                (
                    int(row["height_mm"]),
                    int(row["width_mm"]),
                    int(row["depth_mm"]),
                )
                for row in connection.execute(
                    """
                    SELECT DISTINCT cells.height_mm,
                           COALESCE(cells.width_mm, defaults.width_mm) AS width_mm,
                           COALESCE(cells.depth_mm, defaults.depth_mm) AS depth_mm
                    FROM cells CROSS JOIN vault_defaults defaults
                    WHERE defaults.id = 1
                    """
                ).fetchall()
            }
            supplied_sizes = {
                (
                    int(row["height_mm"]),
                    int(row["width_mm"]),
                    int(row["depth_mm"]),
                )
                for row in tariffs
            }
            if supplied_sizes != sizes:
                raise AdminValidationError(
                    "Нужен полный набор тарифов для всех существующих размеров ячеек."
                )
            if set(penalty["manual_rates"]) != sizes:
                raise AdminValidationError(
                    "Нужны ручные штрафные ставки для всех существующих размеров ячеек."
                )
            old_config = {
                str(row["key"]): str(row["value"])
                for row in connection.execute(
                    f"""SELECT key, value FROM config
                        WHERE key IN ({','.join('?' for _ in EDITABLE_CONFIG_KEYS)})""",
                    tuple(sorted(EDITABLE_CONFIG_KEYS)),
                ).fetchall()
            }
            for key, default in DEFAULT_UI_PREFERENCES.items():
                old_config.setdefault(key, encode_config_bool(default))
            old_tariffs = [
                dict(row)
                for row in connection.execute(
                    """SELECT height_mm, width_mm, depth_mm,
                              period_from_days, period_to_days,
                              price_per_day_minor FROM tariffs
                       ORDER BY height_mm, width_mm, depth_mm, period_from_days"""
                ).fetchall()
            ]
            try:
                old_penalty = get_penalty_settings(connection)
            except PenaltyRateConfigurationError as exc:
                raise AdminConflictError(str(exc)) from exc
            for key, value in config.items():
                stored_value = (
                    encode_config_bool(value)
                    if key in UI_PREFERENCE_KEYS
                    else str(value)
                )
                connection.execute(
                    """INSERT INTO config(key, value, updated_at, updated_by)
                       VALUES(?, ?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET
                           value = excluded.value,
                           updated_at = excluded.updated_at,
                           updated_by = excluded.updated_by""",
                    (key, stored_value, timestamp, employee_name),
                )
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
                       height_mm, width_mm, depth_mm,
                       period_from_days, period_to_days,
                       price_per_day_minor, updated_at, updated_by
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        row["height_mm"],
                        row["width_mm"],
                        row["depth_mm"],
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
                    key: {
                        "old": old_config.get(key),
                        "new": (
                            encode_config_bool(value)
                            if key in UI_PREFERENCE_KEYS
                            else str(value)
                        ),
                    }
                    for key, value in config.items()
                    if old_config.get(key) != (
                        encode_config_bool(value)
                        if key in UI_PREFERENCE_KEYS
                        else str(value)
                    )
                },
                "tariffs": {"old": old_tariffs, "new": tariffs},
                "penalty": {
                    "old": old_penalty,
                    "new": {
                        "mode": penalty["mode"],
                        "manual_rates": [
                            {
                                "height_mm": size[0],
                                "width_mm": size[1],
                                "depth_mm": size[2],
                                "price_per_day_minor": penalty["manual_rates"][size],
                            }
                            for size in sorted(penalty["manual_rates"])
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
    except DatabaseCorruptionError as exc:
        raise AdminNetworkError(str(exc)) from exc
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
