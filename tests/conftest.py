from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from app.config import Settings
from app.db.schema import InitializationResult, initialize_databases
from app.db.connections import open_write


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cells_csv_path() -> Path:
    return PROJECT_ROOT / "data" / "cell_heights.csv"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    database_directory = tmp_path / "shared test data"
    database_directory.mkdir()
    return Settings(database_directory=database_directory, testing=True)


@pytest.fixture
def initialized_databases(
    settings: Settings, cells_csv_path: Path
) -> InitializationResult:
    return initialize_databases(settings, cells_csv_path=cells_csv_path)


@pytest.fixture
def insert_test_contract(
    settings: Settings, initialized_databases: InitializationResult
) -> Callable[..., None]:
    def insert(
        *,
        cell_number: str,
        end_date: str,
        start_date: str | None = None,
        client_name: str = "Тестовый Клиент",
        account_number: str = "TEST-ACCOUNT",
    ) -> None:
        identifier = f"contract-test-{cell_number}"
        effective_start_date = start_date or end_date
        values = (
            identifier,
            cell_number,
            client_name,
            f"TEST-ID-{cell_number}",
            "Тестовый орган",
            "2030-12-31",
            account_number,
            effective_start_date,
            end_date,
            1,
            15,
            15,
            0,
            "2026-07-01T09:00:00+06:00",
            "test-user",
            "2026-07-01T09:00:00+06:00",
            "test-user",
        )
        with open_write(settings) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO contracts(
                    contract_id, cell_number, client_full_name,
                    id_card_number, id_card_issuer, id_card_expiry_date,
                    account_number, start_date, end_date, rent_days,
                    price_per_day_minor, rent_price_minor, deposit_amount_minor,
                    created_at, created_by, updated_at, updated_by
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            connection.commit()

    return insert
