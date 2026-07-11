"""Deterministic cell status calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class CellStatus(StrEnum):
    FREE = "free"
    NORMAL = "normal"
    EXPIRING = "expiring"
    OVERDUE = "overdue"


@dataclass(frozen=True, slots=True)
class StatusResult:
    status: CellStatus
    days_remaining: int | None


def calculate_status(
    *, end_date: date | None, as_of_date: date, expiring_soon_days: int
) -> StatusResult:
    if expiring_soon_days < 0:
        raise ValueError("Порог статуса не может быть отрицательным.")
    if end_date is None:
        return StatusResult(CellStatus.FREE, None)

    days_remaining = (end_date - as_of_date).days
    if days_remaining < 0:
        status = CellStatus.OVERDUE
    elif days_remaining <= expiring_soon_days:
        status = CellStatus.EXPIRING
    else:
        status = CellStatus.NORMAL
    return StatusResult(status, days_remaining)
