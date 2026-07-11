from __future__ import annotations

from datetime import date

import pytest

from app.services.statuses import CellStatus, calculate_status


AS_OF = date(2026, 7, 1)


@pytest.mark.parametrize(
    ("end_date", "expected_status", "expected_days"),
    [
        (None, CellStatus.FREE, None),
        (date(2026, 6, 30), CellStatus.OVERDUE, -1),
        (date(2026, 7, 1), CellStatus.EXPIRING, 0),
        (date(2026, 7, 8), CellStatus.EXPIRING, 7),
        (date(2026, 7, 9), CellStatus.NORMAL, 8),
    ],
)
def test_status_boundaries(
    end_date: date | None,
    expected_status: CellStatus,
    expected_days: int | None,
) -> None:
    result = calculate_status(
        end_date=end_date,
        as_of_date=AS_OF,
        expiring_soon_days=7,
    )
    assert result.status == expected_status
    assert result.days_remaining == expected_days


def test_negative_expiring_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="отрицательным"):
        calculate_status(
            end_date=AS_OF,
            as_of_date=AS_OF,
            expiring_soon_days=-1,
        )
