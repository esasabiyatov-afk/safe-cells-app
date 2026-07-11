from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

import pytest

from app import create_app
from app.config import Settings
from app.db.connections import DatabasePaths, open_readonly, open_write
from app.services.rental_calculator import (
    CellUnavailableError,
    RentalDataError,
    RentalValidationError,
    calculate_rental_quote,
    end_date_from_days,
    inclusive_days,
)


HEIGHT_TO_CELL = {50: "1", 75: "55", 100: "2", 125: "58", 175: "35", 300: "61"}
EXPECTED_RATES = {
    50: (15, 10, 8, 7),
    75: (17, 13, 11, 8),
    100: (17, 13, 11, 8),
    125: (20, 15, 13, 10),
    175: (25, 20, 15, 13),
    300: (30, 25, 20, 17),
}
BOUNDARIES = ((1, 0), (30, 0), (31, 1), (90, 1), (91, 2), (180, 2), (181, 3))


@pytest.mark.parametrize(
    ("start_date", "end_date", "expected_days"),
    [
        (date(2026, 7, 1), date(2026, 7, 1), 1),
        (date(2026, 7, 1), date(2026, 7, 30), 30),
        (date(2026, 7, 1), date(2026, 7, 31), 31),
        (date(2026, 1, 1), date(2026, 3, 31), 90),
        (date(2026, 1, 1), date(2026, 4, 1), 91),
        (date(2026, 1, 1), date(2026, 6, 29), 180),
        (date(2026, 1, 1), date(2026, 6, 30), 181),
    ],
)
def test_inclusive_days_at_tariff_boundaries(
    start_date: date, end_date: date, expected_days: int
) -> None:
    assert inclusive_days(start_date, end_date) == expected_days


@pytest.mark.parametrize("rent_days", [1, 30, 31, 90, 91, 180, 181])
def test_end_date_from_days_is_inclusive(rent_days: int) -> None:
    start_date = date(2026, 1, 1)
    assert inclusive_days(
        start_date, end_date_from_days(start_date, rent_days)
    ) == rent_days


def test_every_height_and_tariff_boundary(
    settings: Settings, initialized_databases
) -> None:
    for height, cell_number in HEIGHT_TO_CELL.items():
        for rent_days, rate_index in BOUNDARIES:
            quote = calculate_rental_quote(
                settings,
                cell_number=cell_number,
                start_date_value="2026-01-01",
                rent_days_value=rent_days,
            )
            expected_rate = EXPECTED_RATES[height][rate_index]
            assert quote.height_mm == height
            assert quote.rent_days == rent_days
            assert quote.price_per_day == expected_rate
            assert quote.rent_price == rent_days * expected_rate
            assert quote.deposit_amount == 1500
            assert quote.total_amount == quote.rent_price + 1500
            assert quote.currency_code == "KGS"
            assert quote.currency_label == "сом"


def test_quote_accepts_end_date_and_recomputes_days(
    settings: Settings, initialized_databases
) -> None:
    quote = calculate_rental_quote(
        settings,
        cell_number="1",
        start_date_value="2026-07-01",
        end_date_value="2026-07-30",
    )
    assert quote.rent_days == 30
    assert quote.end_date == "2026-07-30"
    assert quote.price_per_day == 15
    assert quote.rent_price == 450
    assert quote.total_amount == 1950


def test_quote_accepts_days_and_recomputes_end_date(
    settings: Settings, initialized_databases
) -> None:
    quote = calculate_rental_quote(
        settings,
        cell_number="1",
        start_date_value="2026-07-01",
        rent_days_value=31,
    )
    assert quote.end_date == "2026-07-31"
    assert quote.price_per_day == 10
    assert quote.rent_price == 310
    assert quote.total_amount == 1810


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"cell_number": "", "start_date_value": "2026-07-01", "rent_days_value": 1}, "номер"),
        ({"cell_number": "1", "start_date_value": "", "rent_days_value": 1}, "дату начала"),
        ({"cell_number": "1", "start_date_value": "bad", "rent_days_value": 1}, "неверную дату"),
        (
            {
                "cell_number": "1",
                "start_date_value": "2026-07-02",
                "end_date_value": "2026-07-01",
            },
            "раньше",
        ),
        ({"cell_number": "1", "start_date_value": "2026-07-01", "rent_days_value": 0}, "не меньше 1"),
        ({"cell_number": "1", "start_date_value": "2026-07-01", "rent_days_value": True}, "целым числом"),
        (
            {
                "cell_number": "1",
                "start_date_value": "2026-07-01",
                "end_date_value": "2026-07-30",
                "rent_days_value": 29,
            },
            "не соответствует",
        ),
        ({"cell_number": "1", "start_date_value": "2026-07-01"}, "дату окончания"),
    ],
)
def test_invalid_calculation_input_is_rejected(
    settings: Settings, initialized_databases, kwargs: dict, message: str
) -> None:
    with pytest.raises(RentalValidationError, match=message):
        calculate_rental_quote(settings, **kwargs)


def test_occupied_cell_is_rechecked_on_backend(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-07-30")
    with pytest.raises(CellUnavailableError, match="уже занята"):
        calculate_rental_quote(
            settings,
            cell_number="1",
            start_date_value="2026-07-01",
            rent_days_value=30,
        )


def test_calculator_does_not_write_to_database(
    settings: Settings, initialized_databases
) -> None:
    paths = DatabasePaths.from_settings(settings)
    with open_readonly(paths.working) as connection:
        before = connection.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]

    calculate_rental_quote(
        settings,
        cell_number="1",
        start_date_value="2026-07-01",
        rent_days_value=30,
    )

    with open_readonly(paths.working) as connection:
        after = connection.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    assert before == after == 0


def test_missing_tariff_is_safe_data_error(
    settings: Settings, initialized_databases
) -> None:
    with open_write(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM tariffs WHERE height_mm = 50 AND period_from_days = 1"
        )
        connection.commit()

    with pytest.raises(RentalDataError, match="тариф"):
        calculate_rental_quote(
            settings,
            cell_number="1",
            start_date_value="2026-07-01",
            rent_days_value=30,
        )


def test_invalid_money_config_is_safe_data_error(
    settings: Settings, initialized_databases
) -> None:
    with open_write(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE config SET value = 'USD' WHERE key = 'currency_code'"
        )
        connection.commit()

    with pytest.raises(RentalDataError, match="настройки"):
        calculate_rental_quote(
            settings,
            cell_number="1",
            start_date_value="2026-07-01",
            rent_days_value=30,
        )


def test_rental_api_success_and_no_cache(
    settings: Settings, initialized_databases
) -> None:
    app = create_app(settings)
    response = app.test_client().post(
        "/api/rental/calculate",
        json={
            "cell_number": "1",
            "start_date": "2026-07-01",
            "end_date": "2026-07-30",
            "rent_days": 30,
        },
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert payload["rent_days"] == 30
    assert payload["price_per_day"] == 15
    assert payload["rent_price"] == 450
    assert payload["deposit_amount"] == 1500
    assert payload["total_amount"] == 1950
    assert payload["currency_label"] == "сом"


def test_rental_api_rejects_tampered_days(
    settings: Settings, initialized_databases
) -> None:
    app = create_app(settings)
    response = app.test_client().post(
        "/api/rental/calculate",
        json={
            "cell_number": "1",
            "start_date": "2026-07-01",
            "end_date": "2026-07-30",
            "rent_days": 1,
        },
    )
    assert response.status_code == 400
    assert "не соответствует" in response.get_json()["message"]


def test_rental_api_rejects_occupied_cell(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-07-30")
    app = create_app(settings)
    response = app.test_client().post(
        "/api/rental/calculate",
        json={"cell_number": "1", "start_date": "2026-07-01", "rent_days": 30},
    )
    assert response.status_code == 409
    assert "занята" in response.get_json()["message"]


def test_rental_api_unavailable_path_does_not_create_database(tmp_path: Path) -> None:
    missing = tmp_path / "offline network"
    settings = Settings(database_directory=missing, testing=True)
    app = create_app(settings)
    response = app.test_client().post(
        "/api/rental/calculate",
        json={"cell_number": "1", "start_date": "2026-07-01", "rent_days": 30},
    )
    assert response.status_code == 503
    assert "сетевого диска" in response.get_json()["message"]
    assert not missing.exists()
