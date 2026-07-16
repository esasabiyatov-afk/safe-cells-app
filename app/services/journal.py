"""Read-only, privacy-safe view of the shared cell operation journal."""

from __future__ import annotations

from datetime import date
import json
import math
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
    "contract.created": "Ячейка занята",
    "contract.renewed": "Договор продлён",
    "contract.edited": "Данные исправлены",
    "contract.closed": "Договор закрыт",
}
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


class JournalValidationError(ValueError):
    """A journal filter is invalid."""


class JournalReadError(RuntimeError):
    """The archive database could not be read."""


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
        old_end = _display_date(changes.get("old_end_date"))
        new_end = _display_date(changes.get("new_end_date"))
        days = _safe_nonnegative_integer(changes.get("renewal_days"))
        penalty_days = _safe_nonnegative_integer(changes.get("penalty_days"))
        parts = []
        if old_end and new_end:
            parts.append(f"Окончание: {old_end} → {new_end}")
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

    return "Исправлены данные активного договора без изменения срока и сумм."


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
    """Return one filtered page of cell-related audit entries without client data."""

    cell = _optional_text(cell_number, maximum=50, label="Номер ячейки")
    action_code = _optional_text(action, maximum=40, label="Действие")
    if action_code is not None and action_code not in ACTION_LABELS:
        raise JournalValidationError("Выберите допустимое действие журнала.")
    start = _optional_date(date_from, label="Дату начала")
    end = _optional_date(date_to, label="Дату окончания")
    if start is not None and end is not None and end < start:
        raise JournalValidationError("Дата окончания фильтра раньше даты начала.")
    page_number = _positive_integer(page, default=1, maximum=1_000_000, label="Страница")
    size = _positive_integer(
        page_size, default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE, label="Размер страницы"
    )

    clauses = ["cell_number IS NOT NULL", f"action IN ({','.join('?' for _ in ACTION_LABELS)})"]
    parameters: list[object] = list(ACTION_LABELS)
    if cell is not None:
        clauses.append("cell_number = ?")
        parameters.append(cell)
    if action_code is not None:
        clauses.append("action = ?")
        parameters.append(action_code)
    if start is not None:
        clauses.append("substr(occurred_at, 1, 10) >= ?")
        parameters.append(start.isoformat())
    if end is not None:
        clauses.append("substr(occurred_at, 1, 10) <= ?")
        parameters.append(end.isoformat())
    where_sql = " AND ".join(clauses)

    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.archive, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM log WHERE {where_sql}", parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT occurred_at, employee, action, cell_number, changes_json
                FROM log
                WHERE {where_sql}
                ORDER BY occurred_at DESC, rowid DESC
                LIMIT ? OFFSET ?
                """,
                (*parameters, size, (page_number - 1) * size),
            ).fetchall()
    except JournalValidationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise JournalReadError(NETWORK_ERROR_MESSAGE) from exc

    entries = [
        {
            "occurred_at": str(row["occurred_at"]),
            "employee": str(row["employee"]),
            "cell_number": str(row["cell_number"]),
            "action": str(row["action"]),
            "action_label": ACTION_LABELS[str(row["action"])],
            "summary": _summary(str(row["action"]), row["changes_json"]),
        }
        for row in rows
    ]
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
