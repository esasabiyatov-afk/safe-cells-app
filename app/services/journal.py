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


ACTION_LABELS = {
    "contract.created": "Занятие ячейки",
    "contract.renewed": "Договор продлён",
    "contract.closed": "Договор закрыт",
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


def _display_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed.strftime("%d.%m.%Y")


def _safe_nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def _summary(action: str, raw_changes: object) -> str:
    """Build a summary from an explicit allow-list; never return raw audit values."""

    changes = _safe_changes(raw_changes)
    if action == "contract.created":
        start = _display_date(changes.get("start_date"))
        end = _display_date(changes.get("end_date"))
        days = _safe_nonnegative_integer(changes.get("rent_days"))
        parts = []
        if start and end:
            parts.append(f"Срок: {start} — {end}")
        if days is not None:
            parts.append(f"Дней: {days}")
        return "; ".join(parts) or "Открыт новый договор аренды."

    if action == "contract.renewed":
        new_start = _display_date(changes.get("new_start_date"))
        new_end = _display_date(changes.get("new_end_date"))
        days = _safe_nonnegative_integer(changes.get("renewal_days"))
        penalty_days = _safe_nonnegative_integer(changes.get("penalty_days"))
        parts = []
        if new_start and new_end:
            parts.append(f"Период продления: {new_start} — {new_end}")
        if days is not None:
            parts.append(f"Продление: {days} дн.")
        if penalty_days:
            parts.append(f"Просрочка: {penalty_days} дн.")
        return "; ".join(parts) or "Срок договора продлён."

    if action == "contract.closed":
        close_date = _display_date(changes.get("close_date"))
        penalty_days = _safe_nonnegative_integer(changes.get("penalty_days"))
        reason = changes.get("close_reason")
        allowed_reasons = {
            "Досрочное расторжение",
            "Окончание срока",
            "Закрытие после окончания срока",
            "Потеря ключа",
        }
        parts = []
        if close_date:
            parts.append(f"Дата закрытия: {close_date}")
        if reason in allowed_reasons:
            parts.append(f"Причина: {reason}")
        if penalty_days:
            parts.append(f"Просрочка: {penalty_days} дн.")
        return "; ".join(parts) or "Договор закрыт, ячейка освобождена."

    return "Операция по договору."


def _validated_filters(
    *,
    cell_number: object = None,
    action: object = None,
    date_from: object = None,
    date_to: object = None,
) -> tuple[str | None, str | None, date | None, date | None]:
    cell = _optional_text(cell_number, maximum=50, label="Номер ячейки")
    action_code = _optional_text(action, maximum=40, label="Действие")
    if action_code is not None and action_code not in ACTION_LABELS:
        raise JournalValidationError("Выберите допустимое действие журнала.")
    start = _optional_date(date_from, label="Дату начала")
    end = _optional_date(date_to, label="Дату окончания")
    if start is not None and end is not None and end < start:
        raise JournalValidationError("Дата окончания фильтра раньше даты начала.")
    return cell, action_code, start, end


def _where_clause(
    cell: str | None,
    action_code: str | None,
    start: date | None,
    end: date | None,
) -> tuple[str, list[object]]:
    clauses = [
        "log.cell_number IS NOT NULL",
        f"log.action IN ({','.join('?' for _ in ACTION_LABELS)})",
    ]
    parameters: list[object] = list(ACTION_LABELS)
    if cell is not None:
        clauses.append("log.cell_number = ?")
        parameters.append(cell)
    if action_code is not None:
        clauses.append("log.action = ?")
        parameters.append(action_code)
    if start is not None:
        clauses.append("substr(log.occurred_at, 1, 10) >= ?")
        parameters.append(start.isoformat())
    if end is not None:
        clauses.append("substr(log.occurred_at, 1, 10) <= ?")
        parameters.append(end.isoformat())
    return " AND ".join(clauses), parameters


def _readonly_uri(path: Path) -> str:
    return f"{path.absolute().as_uri()}?mode=ro"


def _entry(row: sqlite3.Row) -> dict[str, str]:
    client_name = str(row["client_full_name"] or "").strip()
    return {
        "occurred_at": str(row["occurred_at"]),
        "employee": str(row["employee"]),
        "cell_number": str(row["cell_number"]),
        "client_full_name": client_name or "Клиент не найден",
        "action": str(row["action"]),
        "action_label": ACTION_LABELS[str(row["action"])],
        "summary": _summary(str(row["action"]), row["changes_json"]),
    }


def _read_entries(
    settings: Settings,
    *,
    where_sql: str,
    parameters: list[object],
    limit: int,
    offset: int = 0,
) -> tuple[int, list[dict[str, str]]]:
    paths = validate_database_pair(settings)
    with open_readonly(
        paths.archive, busy_timeout_ms=settings.busy_timeout_ms
    ) as connection:
        connection.execute(
            "ATTACH DATABASE ? AS working", (_readonly_uri(paths.working),)
        )
        connection.execute("BEGIN")
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
                f"SELECT COUNT(*) FROM log WHERE {where_sql}", parameters
            ).fetchone()[0]
        )
        connection.rollback()
    return total, [_entry(row) for row in rows]


def list_journal_entries(
    settings: Settings,
    *,
    cell_number: object = None,
    action: object = None,
    date_from: object = None,
    date_to: object = None,
    page: object = 1,
    page_size: object = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Return one filtered page of cell events with the client's full name."""

    cell, action_code, start, end = _validated_filters(
        cell_number=cell_number,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    page_number = _positive_integer(page, default=1, maximum=1_000_000, label="Страница")
    size = _positive_integer(
        page_size, default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE, label="Размер страницы"
    )
    where_sql, parameters = _where_clause(cell, action_code, start, end)

    try:
        total, entries = _read_entries(
            settings,
            where_sql=where_sql,
            parameters=parameters,
            limit=size,
            offset=(page_number - 1) * size,
        )
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise JournalReadError(NETWORK_ERROR_MESSAGE) from exc

    page_count = max(1, math.ceil(total / size))
    return {
        "entries": entries,
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
) -> list[dict[str, str]]:
    """Return the complete filtered selection for one controlled XLSX report."""

    cell, action_code, start, end = _validated_filters(
        cell_number=cell_number,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    where_sql, parameters = _where_clause(cell, action_code, start, end)
    try:
        total, entries = _read_entries(
            settings,
            where_sql=where_sql,
            parameters=parameters,
            limit=MAX_REPORT_ROWS + 1,
        )
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise JournalReadError(NETWORK_ERROR_MESSAGE) from exc
    if total > MAX_REPORT_ROWS:
        raise JournalValidationError(
            "В отчёте слишком много записей. Уточните период или номер ячейки."
        )
    return entries
