"""Read-only view of the shared cell operation journal."""

from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path
import sqlite3
from typing import Any

from app.config import Settings
from app.db.connections import (
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_readonly,
    validate_database_pair,
)
from app.services.ui_preferences import (
    DEFAULT_UI_PREFERENCES,
    UI_PREFERENCE_KEYS,
    UiPreferenceError,
    parse_config_bool,
)


ACTION_LABELS = {
    "contract.created": "Открытие",
    "contract.renewed": "Продление",
    "contract.closed": "Закрытие",
    "contract.action_cancelled": "Отмена",
    "cell.manual_occupied": "Открытие",
    "cell.manual_released": "Закрытие",
    # Legacy actions stay readable after the explicit schema 4→5 migration.
    "cell.bank_occupied": "Открытие",
    "cell.bank_released": "Закрытие",
    "cell.key_restored": "Ключ восстановлен",
}
FILTER_LABELS = {
    "contract.created": "Открытие",
    "contract.renewed": "Продление",
    "contract.closed": "Закрытие",
    "contract.action_cancelled": "Отмена",
    "overdue": "Просрочка",
    "cell.key_restored": "Ключ восстановлен",
}
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_REPORT_ROWS = 20_000


class JournalValidationError(ValueError):
    """A journal filter is invalid."""


class JournalReadError(RuntimeError):
    """The journal databases could not be read."""


def _optional_text(value: object, *, maximum: int, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise JournalValidationError(f"Поле «{label}» указано неверно.")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise JournalValidationError(f"Поле «{label}» слишком длинное.")
    return normalized


def _optional_date(value: object, *, label: str) -> date | None:
    normalized = _optional_text(value, maximum=10, label=label)
    if normalized is None:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise JournalValidationError(f"Укажите корректную {label.lower()}.") from exc


def _positive_integer(value: object, *, default: int, maximum: int, label: str) -> int:
    if value is None or value == "":
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise JournalValidationError(f"Поле «{label}» указано неверно.") from exc
    if normalized < 1 or normalized > maximum:
        raise JournalValidationError(
            f"Поле «{label}» должно быть от 1 до {maximum}."
        )
    return normalized


def _safe_changes(raw_value: object) -> dict[str, Any]:
    if not isinstance(raw_value, str):
        return {}
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


RUSSIAN_MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def _display_date(value: object, *, words: bool) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    if words:
        return f"{parsed.day} {RUSSIAN_MONTHS[parsed.month]} {parsed.year} года"
    return parsed.strftime("%d.%m.%Y")


def _safe_nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def _summary(action: str, raw_changes: object, *, date_words: bool) -> str:
    """Build a summary from an explicit allow-list; never return raw audit values."""

    changes = _safe_changes(raw_changes)
    if action == "contract.created":
        start = _display_date(changes.get("start_date"), words=date_words)
        end = _display_date(changes.get("end_date"), words=date_words)
        days = _safe_nonnegative_integer(changes.get("rent_days"))
        parts = []
        if start and end:
            parts.append(f"Период аренды: {start} — {end}")
        if days is not None:
            parts.append(f"Срок: {days} дн.")
        return "; ".join(parts) or "Открыт новый договор аренды."

    if action == "contract.renewed":
        new_start = _display_date(changes.get("new_start_date"), words=date_words)
        new_end = _display_date(changes.get("new_end_date"), words=date_words)
        days = _safe_nonnegative_integer(changes.get("renewal_days"))
        penalty_days = _safe_nonnegative_integer(changes.get("penalty_days"))
        parts = []
        if new_start and new_end:
            parts.append(f"Период продления: {new_start} — {new_end}")
        if days is not None:
            parts.append(f"Срок: {days} дн.")
        if penalty_days:
            parts.append(f"Просрочка: {penalty_days} дн.")
        return "; ".join(parts) or "Срок договора продлён."

    if action == "contract.closed":
        penalty_days = _safe_nonnegative_integer(changes.get("penalty_days"))
        reason = changes.get("close_reason")
        allowed_reasons = {
            "Досрочное расторжение",
            "Окончание срока",
            "Закрытие после окончания срока",
            "Потеря ключа",
        }
        parts = []
        if reason in allowed_reasons:
            parts.append(str(reason))
        if penalty_days:
            parts.append(f"Просрочка: {penalty_days} дн.")
        return "; ".join(parts) or "Договор закрыт, ячейка освобождена."

    if action == "contract.action_cancelled":
        original_action = changes.get("original_action")
        cancelled_label = {
            "contract.created": "Отменено открытие",
            "contract.renewed": "Отменено продление",
            "contract.closed": "Отменено закрытие",
        }.get(original_action, "Отменено действие")
        reason = changes.get("reason")
        allowed_reasons = {
            "Клиент изменил решение",
            "Нужно изменить срок",
            "Ошибка при вводе",
        }
        if reason in allowed_reasons:
            return f"{cancelled_label}; причина: {reason}."
        return f"{cancelled_label}."

    if action in {"cell.manual_occupied", "cell.bank_occupied"}:
        return "Открыто без договора и срока."
    if action in {"cell.manual_released", "cell.bank_released"}:
        return "Закрыто без договора и срока."
    if action == "cell.key_restored":
        return "Ключ восстановлен, ячейка свободна."

    return "Операция по договору."


def _validated_filters(
    *,
    cell_number: object = None,
    action: object = None,
    date_from: object = None,
    date_to: object = None,
    client_name: object = None,
    employee: object = None,
) -> tuple[
    str | None,
    str | None,
    date | None,
    date | None,
    str | None,
    str | None,
]:
    cell = _optional_text(cell_number, maximum=50, label="Номер ячейки")
    action_code = _optional_text(action, maximum=40, label="Действие")
    if action_code is not None and action_code not in FILTER_LABELS:
        raise JournalValidationError("Выберите допустимое действие журнала.")
    start = _optional_date(date_from, label="Дату начала")
    end = _optional_date(date_to, label="Дату окончания")
    if start is not None and end is not None and end < start:
        raise JournalValidationError("Дата окончания фильтра раньше даты начала.")
    client = _optional_text(client_name, maximum=200, label="ФИО клиента")
    employee_name = _optional_text(employee, maximum=128, label="Сотрудник")
    return cell, action_code, start, end, client, employee_name


def _where_clause(
    cell: str | None,
    action_code: str | None,
    start: date | None,
    end: date | None,
    client_name: str | None,
    employee: str | None,
) -> tuple[str, list[object]]:
    clauses = [
        "log.cell_number IS NOT NULL",
        f"log.action IN ({','.join('?' for _ in ACTION_LABELS)})",
    ]
    parameters: list[object] = list(ACTION_LABELS)
    if cell is not None:
        clauses.append("log.cell_number = ?")
        parameters.append(cell)
    if action_code == "overdue":
        clauses.append("log.action IN ('contract.renewed', 'contract.closed')")
        clauses.append(
            "CASE WHEN json_valid(log.changes_json) "
            "THEN COALESCE(CAST(json_extract(log.changes_json, ?) AS INTEGER), 0) "
            "ELSE 0 END > 0"
        )
        parameters.append("$.penalty_days")
    elif action_code == "contract.created":
        clauses.append(
            "log.action IN ('contract.created', 'cell.manual_occupied', "
            "'cell.bank_occupied')"
        )
    elif action_code == "contract.closed":
        clauses.append(
            "log.action IN ('contract.closed', 'cell.manual_released', "
            "'cell.bank_released')"
        )
    elif action_code is not None:
        clauses.append("log.action = ?")
        parameters.append(action_code)
    if start is not None:
        clauses.append("substr(log.occurred_at, 1, 10) >= ?")
        parameters.append(start.isoformat())
    if end is not None:
        clauses.append("substr(log.occurred_at, 1, 10) <= ?")
        parameters.append(end.isoformat())
    if client_name is not None:
        clauses.append(
            "instr(casefold(COALESCE(active.client_full_name, "
            "archived.client_full_name, CASE WHEN "
            "log.action IN ('cell.manual_occupied', 'cell.manual_released', "
            "'cell.bank_occupied', 'cell.bank_released') "
            "AND json_valid(log.changes_json) "
            "THEN CAST(json_extract(log.changes_json, ?) AS TEXT) "
            "ELSE '' END, '')), casefold(?)) > 0"
        )
        parameters.extend(("$.occupation_label", client_name))
    if employee is not None:
        clauses.append("log.employee = ?")
        parameters.append(employee)
    return " AND ".join(clauses), parameters


def _readonly_uri(path: Path) -> str:
    return f"{path.absolute().as_uri()}?mode=ro"


def _entry(row: sqlite3.Row, *, date_words: bool) -> dict[str, Any]:
    client_name = str(row["client_full_name"] or "").strip()
    action = str(row["action"])
    changes = _safe_changes(row["changes_json"])
    manual_label = changes.get("occupation_label")
    if not isinstance(manual_label, str) or not (1 <= len(manual_label.strip()) <= 80):
        manual_label = ""
    else:
        manual_label = manual_label.strip()
    penalty_days = _safe_nonnegative_integer(changes.get("penalty_days"))
    is_overdue = action in {"contract.renewed", "contract.closed"} and bool(
        penalty_days
    )
    action_label = ACTION_LABELS[action]
    return {
        "occurred_at": str(row["occurred_at"]),
        "employee": str(row["employee"]),
        "cell_number": str(row["cell_number"]),
        "client_full_name": (
            client_name
            or manual_label
            or (
                "Без договора"
                if action.startswith(("cell.manual_", "cell.bank_"))
                else "Клиент не найден"
            )
        ),
        "action": action,
        "action_label": action_label,
        "report_action_label": (
            f"{action_label} / Просрочка" if is_overdue else action_label
        ),
        "is_overdue": is_overdue,
        "summary": _summary(action, row["changes_json"], date_words=date_words),
    }


def _read_entries(
    settings: Settings,
    *,
    where_sql: str,
    parameters: list[object],
    limit: int,
    offset: int = 0,
    use_stored_preferences: bool = True,
) -> tuple[int, list[dict[str, Any]], list[str], dict[str, bool]]:
    paths = validate_database_pair(settings)
    with open_readonly(
        paths.archive, busy_timeout_ms=settings.busy_timeout_ms
    ) as connection:
        connection.create_function(
            "casefold", 1, lambda value: str(value or "").casefold()
        )
        connection.execute(
            "ATTACH DATABASE ? AS working", (_readonly_uri(paths.working),)
        )
        connection.execute("BEGIN")
        preferences = dict(DEFAULT_UI_PREFERENCES)
        if use_stored_preferences:
            preference_rows = connection.execute(
                f"""SELECT key, value FROM working.config
                    WHERE key IN ({','.join('?' for _ in UI_PREFERENCE_KEYS)})""",
                tuple(sorted(UI_PREFERENCE_KEYS)),
            ).fetchall()
            for preference_row in preference_rows:
                key = str(preference_row["key"])
                preferences[key] = parse_config_bool(
                    preference_row["value"], key=key
                )
        else:
            preferences["display_date_words"] = False
        rows = connection.execute(
            f"""
            SELECT
                log.occurred_at,
                log.employee,
                log.action,
                log.cell_number,
                log.changes_json,
                COALESCE(active.client_full_name, archived.client_full_name)
                    AS client_full_name
            FROM log
            LEFT JOIN working.contracts AS active
                ON active.contract_id = log.contract_id
            LEFT JOIN contracts_archive AS archived
                ON archived.contract_id = log.contract_id
            WHERE {where_sql}
            ORDER BY log.occurred_at DESC, log.rowid DESC
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        total = int(
            connection.execute(
                f"""
                SELECT COUNT(*)
                FROM log
                LEFT JOIN working.contracts AS active
                    ON active.contract_id = log.contract_id
                LEFT JOIN contracts_archive AS archived
                    ON archived.contract_id = log.contract_id
                WHERE {where_sql}
                """,
                parameters,
            ).fetchone()[0]
        )
        employees = [
            str(row["employee"])
            for row in connection.execute(
                f"""
                SELECT DISTINCT employee FROM log
                WHERE cell_number IS NOT NULL
                  AND action IN ({','.join('?' for _ in ACTION_LABELS)})
                ORDER BY casefold(employee), employee
                """,
                tuple(ACTION_LABELS),
            ).fetchall()
        ]
        connection.rollback()
    return (
        total,
        [
            _entry(row, date_words=preferences["display_date_words"])
            for row in rows
        ],
        employees,
        preferences,
    )


def list_journal_entries(
    settings: Settings,
    *,
    cell_number: object = None,
    action: object = None,
    date_from: object = None,
    date_to: object = None,
    page: object = 1,
    page_size: object = DEFAULT_PAGE_SIZE,
    client_name: object = None,
    employee: object = None,
) -> dict[str, Any]:
    """Return one filtered page of cell events with the client's full name."""

    cell, action_code, start, end, client, employee_name = _validated_filters(
        cell_number=cell_number,
        action=action,
        date_from=date_from,
        date_to=date_to,
        client_name=client_name,
        employee=employee,
    )
    page_number = _positive_integer(page, default=1, maximum=1_000_000, label="Страница")
    size = _positive_integer(
        page_size, default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE, label="Размер страницы"
    )
    where_sql, parameters = _where_clause(
        cell, action_code, start, end, client, employee_name
    )

    try:
        total, entries, employees, preferences = _read_entries(
            settings,
            where_sql=where_sql,
            parameters=parameters,
            limit=size,
            offset=(page_number - 1) * size,
        )
    except (DatabaseUnavailableError, UiPreferenceError, OSError, sqlite3.Error) as exc:
        raise JournalReadError(NETWORK_ERROR_MESSAGE) from exc

    page_count = max(1, math.ceil(total / size))
    return {
        "entries": entries,
        "filters": {"employees": employees},
        "ui_preferences": preferences,
        "pagination": {
            "page": page_number,
            "page_size": size,
            "page_count": page_count,
            "total": total,
            "has_previous": page_number > 1,
            "has_next": page_number < page_count,
        },
    }


def list_journal_report_entries(
    settings: Settings,
    *,
    cell_number: object = None,
    action: object = None,
    date_from: object = None,
    date_to: object = None,
    client_name: object = None,
    employee: object = None,
) -> list[dict[str, Any]]:
    """Return the complete filtered selection for one controlled XLSX report."""

    cell, action_code, start, end, client, employee_name = _validated_filters(
        cell_number=cell_number,
        action=action,
        date_from=date_from,
        date_to=date_to,
        client_name=client_name,
        employee=employee,
    )
    where_sql, parameters = _where_clause(
        cell, action_code, start, end, client, employee_name
    )
    try:
        total, entries, _employees, _preferences = _read_entries(
            settings,
            where_sql=where_sql,
            parameters=parameters,
            limit=MAX_REPORT_ROWS + 1,
            use_stored_preferences=False,
        )
    except (DatabaseUnavailableError, UiPreferenceError, OSError, sqlite3.Error) as exc:
        raise JournalReadError(NETWORK_ERROR_MESSAGE) from exc
    if total > MAX_REPORT_ROWS:
        raise JournalValidationError(
            "В отчёте слишком много записей. Уточните период или номер ячейки."
        )
    return entries
