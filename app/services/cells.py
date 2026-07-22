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
from app.services.legacy_contracts import legacy_status


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


def client_display_name(full_name: str | None) -> str | None:
    if not full_name:
        return None
    parts = full_name.split()
    if not parts:
        return None
    initials = " ".join(f"{part[0].upper()}." for part in parts[1:3] if part)
    return f"{parts[0]} {initials}".strip()


def _archived_client_names(
    settings: Settings, paths: DatabasePaths, contract_ids: set[str]
) -> dict[str, str]:
    if not contract_ids:
        return {}
    placeholders = ",".join("?" for _ in contract_ids)
    with open_readonly(
        paths.archive, busy_timeout_ms=settings.busy_timeout_ms
    ) as connection:
        rows = connection.execute(
            f"""
            SELECT contract_id, client_full_name
            FROM contracts_archive
            WHERE contract_id IN ({placeholders})
            """,
            tuple(sorted(contract_ids)),
        ).fetchall()
    return {str(row["contract_id"]): str(row["client_full_name"]) for row in rows}


def list_cells(settings: Settings, *, as_of_date: date) -> dict[str, Any]:
    """Return operational fields plus the explicitly approved abbreviated name."""

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
                    contracts.client_full_name,
                    contracts.extra_fields_json,
                    cell_blocks.block_kind,
                    cell_blocks.source_contract_id,
                    cell_blocks.occupation_label
                FROM cells
                CROSS JOIN vault_defaults
                LEFT JOIN contracts ON contracts.cell_number = cells.number
                LEFT JOIN cell_blocks ON cell_blocks.cell_number = cells.number
                WHERE vault_defaults.id = 1
                ORDER BY CAST(cells.number AS INTEGER), cells.number
                """
            ).fetchall()
        archived_names = _archived_client_names(
            settings,
            paths,
            {
                str(row["source_contract_id"])
                for row in rows
                if row["block_kind"] == "lost_key"
                and row["source_contract_id"] is not None
            },
        )
    except InvalidStoredDataError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise CellsReadError(NETWORK_ERROR_MESSAGE) from exc

    cells: list[dict[str, Any]] = []
    counts = {
        "free": 0,
        "normal": 0,
        "expiring": 0,
        "overdue": 0,
    }
    for row in rows:
        block_kind = row["block_kind"]
        if block_kind not in {None, "lost_key", "manual"}:
            raise InvalidStoredDataError("Некорректная блокировка ячейки.")
        if block_kind is not None and row["contract_id"] is not None:
            raise InvalidStoredDataError(
                "Ячейка одновременно содержит договор и отдельную блокировку."
            )
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
            if start_date > as_of_date:
                raise InvalidStoredDataError(
                    "Дата начала активного договора находится в будущем."
                )
            total_days = (end_date - start_date).days + 1
        else:
            total_days = None
        if block_kind == "lost_key":
            source_contract_id = str(row["source_contract_id"] or "")
            lost_client_name = archived_names.get(source_contract_id)
            if not lost_client_name:
                raise InvalidStoredDataError(
                    "Для утерянного ключа не найден закрытый договор."
                )
            status_value = "normal"
            days_remaining = None
            display_name = "Ключ утерян"
        elif block_kind == "manual":
            occupation_label = str(row["occupation_label"] or "").strip()
            if not occupation_label:
                raise InvalidStoredDataError("Для занятой ячейки не указана пометка.")
            status_value = "normal"
            days_remaining = None
            display_name = occupation_label
        else:
            status = calculate_status(
                end_date=end_date,
                as_of_date=as_of_date,
                expiring_soon_days=threshold,
            )
            status_value = status.status.value
            days_remaining = status.days_remaining
            display_name = client_display_name(row["client_full_name"])
        legacy = legacy_status(row["extra_fields_json"])
        counts[status_value] += 1
        cells.append(
            {
                "number": row["number"],
                "height_mm": int(row["height_mm"]),
                "width_mm": int(row["width_mm"]),
                "depth_mm": int(row["depth_mm"]),
                "status": status_value,
                "contract_ref": row["contract_id"],
                "block_kind": block_kind,
                "source_contract_ref": row["source_contract_id"],
                "occupation_label": row["occupation_label"],
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "rent_days": rent_days,
                "total_days": total_days,
                "client_display_name": display_name,
                "days_remaining": days_remaining,
                **legacy,
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
                SELECT
                    cells.number,
                    contracts.client_full_name,
                    contracts.account_number,
                    cell_blocks.block_kind,
                    cell_blocks.source_contract_id,
                    cell_blocks.occupation_label
                FROM cells
                LEFT JOIN contracts ON contracts.cell_number = cells.number
                LEFT JOIN cell_blocks ON cell_blocks.cell_number = cells.number
                ORDER BY CAST(cells.number AS INTEGER), cells.number
                """
            ).fetchall()
        archived_names = _archived_client_names(
            settings,
            paths,
            {
                str(row["source_contract_id"])
                for row in rows
                if row["block_kind"] == "lost_key"
                and row["source_contract_id"] is not None
            },
        )
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise CellsReadError(NETWORK_ERROR_MESSAGE) from exc

    matches: list[str] = []
    for row in rows:
        searchable_values = (
            str(row["number"]),
            row["client_full_name"] or "",
            row["account_number"] or "",
            archived_names.get(str(row["source_contract_id"] or ""), ""),
            "Ключ утерян" if row["block_kind"] == "lost_key" else "",
            row["occupation_label"] or "",
        )
        if any(normalized_query in value.casefold() for value in searchable_values):
            matches.append(str(row["number"]))
    return matches
