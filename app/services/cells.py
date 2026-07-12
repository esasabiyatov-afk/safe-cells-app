"""Short-lived read-only queries for the main screen."""

from __future__ import annotations

from datetime import date
import sqlite3
from typing import Any

from app.config import Settings
from app.db.connections import (
    DatabasePaths,
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_readonly,
    validate_database_pair,
)
from app.services.statuses import calculate_status


class CellsReadError(RuntimeError):
    """Safe user-facing database read error."""


class InvalidStoredDataError(RuntimeError):
    """Stored data violates a required invariant."""


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidStoredDataError("Некорректная дата договора.") from exc


def _expiring_threshold(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM config WHERE key = ?", ("expiring_soon_days",)
    ).fetchone()
    if row is None:
        raise InvalidStoredDataError("Не настроен порог истечения.")
    try:
        value = int(row["value"])
    except (TypeError, ValueError) as exc:
        raise InvalidStoredDataError("Некорректный порог истечения.") from exc
    if value < 0:
        raise InvalidStoredDataError("Некорректный порог истечения.")
    return value


def list_cells(settings: Settings, *, as_of_date: date) -> dict[str, Any]:
    """Return only operational, non-personal fields for every cell."""

    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            threshold = _expiring_threshold(connection)
            rows = connection.execute(
                """
                SELECT
                    cells.number,
                    cells.height_mm,
                    COALESCE(cells.width_mm, vault_defaults.width_mm) AS width_mm,
                    COALESCE(cells.depth_mm, vault_defaults.depth_mm) AS depth_mm,
                    contracts.contract_id,
                    contracts.start_date,
                    contracts.end_date,
                    contracts.rent_days,
                    contracts.price_per_day_minor,
                    contracts.rent_price_minor,
                    contracts.deposit_amount_minor
                FROM cells
                CROSS JOIN vault_defaults
                LEFT JOIN contracts ON contracts.cell_number = cells.number
                WHERE vault_defaults.id = 1
                ORDER BY CAST(cells.number AS INTEGER), cells.number
                """
            ).fetchall()
    except InvalidStoredDataError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise CellsReadError(NETWORK_ERROR_MESSAGE) from exc

    cells: list[dict[str, Any]] = []
    counts = {"free": 0, "normal": 0, "expiring": 0, "overdue": 0}
    for row in rows:
        start_date = _parse_date(row["start_date"])
        end_date = _parse_date(row["end_date"])
        rent_days = int(row["rent_days"]) if row["rent_days"] is not None else None
        if start_date is None and end_date is not None:
            raise InvalidStoredDataError("Некорректный срок договора.")
        if start_date is not None and end_date is None:
            raise InvalidStoredDataError("Некорректный срок договора.")
        if start_date is not None:
            if end_date < start_date or rent_days is None or rent_days < 1:
                raise InvalidStoredDataError("Некорректный срок договора.")
            total_days = (end_date - start_date).days + 1
        else:
            total_days = None
        status = calculate_status(
            end_date=end_date,
            as_of_date=as_of_date,
            expiring_soon_days=threshold,
        )
        counts[status.status.value] += 1
        cells.append(
            {
                "number": row["number"],
                "height_mm": int(row["height_mm"]),
                "width_mm": int(row["width_mm"]),
                "depth_mm": int(row["depth_mm"]),
                "status": status.status.value,
                "contract_ref": row["contract_id"],
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "rent_days": rent_days,
                "total_days": total_days,
                "price_per_day": (
                    int(row["price_per_day_minor"])
                    if row["price_per_day_minor"] is not None
                    else None
                ),
                "rent_price": (
                    int(row["rent_price_minor"])
                    if row["rent_price_minor"] is not None
                    else None
                ),
                "deposit_amount": (
                    int(row["deposit_amount_minor"])
                    if row["deposit_amount_minor"] is not None
                    else None
                ),
                "days_remaining": status.days_remaining,
            }
        )

    return {
        "as_of_date": as_of_date.isoformat(),
        "expiring_soon_days": threshold,
        "counts": counts,
        "cells": cells,
    }


def search_cell_numbers(settings: Settings, *, query: str) -> list[str]:
    """Search private fields but return only matching cell numbers."""

    normalized_query = query.strip().casefold()
    if not normalized_query:
        return []

    try:
        paths: DatabasePaths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            rows = connection.execute(
                """
                SELECT cells.number, contracts.client_full_name, contracts.account_number
                FROM cells
                LEFT JOIN contracts ON contracts.cell_number = cells.number
                ORDER BY CAST(cells.number AS INTEGER), cells.number
                """
            ).fetchall()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise CellsReadError(NETWORK_ERROR_MESSAGE) from exc

    matches: list[str] = []
    for row in rows:
        searchable_values = (
            str(row["number"]),
            row["client_full_name"] or "",
            row["account_number"] or "",
        )
        if any(normalized_query in value.casefold() for value in searchable_values):
            matches.append(str(row["number"]))
    return matches
