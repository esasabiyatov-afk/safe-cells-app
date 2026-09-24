from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import sqlite3
from typing import Callable
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.connections import DatabasePaths, open_write
from app.services.cells import (
    InvalidStoredDataError,
    list_cells,
    search_cell_numbers,
)
from app.services.closures import close_contract


AS_OF = date(2026, 7, 1)


def test_list_cells_returns_only_approved_client_display_name(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(
        cell_number="1",
        end_date="2026-07-09",
        start_date="2026-07-01",
        client_name="Секретный Тестовый Клиент",
        account_number="PRIVATE-TEST-ACCOUNT",
    )

    payload = list_cells(settings, as_of_date=AS_OF)
    cell = payload["cells"][0]

    assert payload["ui_preferences"] == {
        "display_date_words": True,
        "show_ui_hints": True,
    }
    assert set(cell) == {
        "number",
        "height_mm",
        "width_mm",
        "depth_mm",
        "status",
            "contract_ref",
            "block_kind",
            "source_contract_ref",
            "occupation_label",
        "start_date",
        "end_date",
        "rent_days",
        "total_days",
            "client_display_name",
            "days_remaining",
            "last_reminded_at",
            "reminder_count",
            "reminder_status",
            "cancellable_action",
            "legacy_imported",
            "legacy_identity_complete",
            "legacy_deposit_known",
            "legacy_rent_terms_known",
        }
    assert cell["start_date"] == "2026-07-01"
    assert cell["contract_ref"] == "contract-test-1"
    assert cell["rent_days"] == 1
    assert cell["total_days"] == 9
    assert cell["client_display_name"] == "Секретный Т. К."
    assert cell["cancellable_action"] is None
    assert cell["legacy_imported"] is False
    serialized = repr(payload)
    assert "Секретный Тестовый" not in serialized
    assert "PRIVATE-TEST-ACCOUNT" not in serialized


def test_list_cells_exposes_only_latest_same_day_cancellation_candidate(
    settings: Settings,
    initialized_databases,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(
        cell_number="1",
        start_date="2026-06-01",
        end_date="2026-07-09",
    )
    operation_id = str(uuid4())
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO archive.log(
                log_id, operation_id, occurred_at, employee, action,
                contract_id, cell_number, changes_json
            ) VALUES(?, ?, ?, 'Тестовый Сотрудник', 'contract.renewed',
                     'contract-test-1', '1', '{}')
            """,
            (
                str(uuid4()),
                operation_id,
                "2026-07-01T10:00:00+06:00",
            ),
        )
        connection.commit()

    cell = list_cells(settings, as_of_date=AS_OF)["cells"][0]

    assert cell["cancellable_action"] == {
        "original_operation_id": operation_id,
        "contract_ref": "contract-test-1",
        "cell_number": "1",
        "action_kind": "renewal",
    }

    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO archive.log(
                log_id, operation_id, occurred_at, employee, action,
                contract_id, cell_number, changes_json
            ) VALUES(?, ?, ?, 'Тестовый Сотрудник', 'contract.edited',
                     'contract-test-1', '1', '{}')
            """,
            (
                str(uuid4()),
                str(uuid4()),
                "2026-07-01T10:01:00+06:00",
            ),
        )
        connection.commit()

    assert list_cells(settings, as_of_date=AS_OF)["cells"][0][
        "cancellable_action"
    ] is None


def test_list_cells_exposes_cancelled_closure_on_now_free_cell(
    settings: Settings,
    initialized_databases,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(
        cell_number="1",
        start_date="2026-06-01",
        end_date="2026-07-09",
    )
    operation_id = str(uuid4())
    close_contract(
        settings,
        payload={
            "operation_id": operation_id,
            "cell_number": "1",
            "contract_ref": "contract-test-1",
            "expected_end_date": "2026-07-09",
            "reason_code": "standard",
        },
        employee="Тестовый Сотрудник",
        close_date=AS_OF,
        occurred_at=datetime.fromisoformat("2026-07-01T11:00:00+06:00"),
    )

    cell = list_cells(settings, as_of_date=AS_OF)["cells"][0]

    assert cell["status"] == "free"
    assert cell["cancellable_action"] == {
        "original_operation_id": operation_id,
        "contract_ref": "contract-test-1",
        "cell_number": "1",
        "action_kind": "closure",
    }


def test_old_database_without_ui_preferences_uses_safe_visible_defaults(
    settings: Settings,
    initialized_databases,
) -> None:
    with open_write(settings) as connection:
        connection.execute(
            "DELETE FROM config WHERE key IN ('display_date_words', 'show_ui_hints')"
        )
        connection.commit()

    payload = list_cells(settings, as_of_date=AS_OF)

    assert payload["ui_preferences"] == {
        "display_date_words": True,
        "show_ui_hints": True,
    }


def test_list_cells_calculates_counts_at_boundaries(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-06-30")
    insert_test_contract(
        cell_number="2", start_date="2026-07-01", end_date="2026-07-01"
    )
    insert_test_contract(
        cell_number="3", start_date="2026-07-01", end_date="2026-07-08"
    )
    insert_test_contract(
        cell_number="4", start_date="2026-07-01", end_date="2026-07-09"
    )

    payload = list_cells(settings, as_of_date=AS_OF)

    assert payload["counts"] == {
        "free": 122,
        "normal": 1,
        "expiring": 2,
        "overdue": 1,
    }
    assert [cell["status"] for cell in payload["cells"][:4]] == [
        "overdue",
        "expiring",
        "expiring",
        "normal",
    ]


@pytest.mark.parametrize("query", ["секретный", "private-test"])
def test_private_search_returns_only_matching_number(
    settings: Settings,
    insert_test_contract: Callable[..., None],
    query: str,
) -> None:
    insert_test_contract(
        cell_number="1",
        end_date="2026-07-09",
        client_name="Секретный Тестовый Клиент",
        account_number="PRIVATE-TEST-ACCOUNT",
    )

    assert search_cell_numbers(settings, query=query) == ["1"]


def test_number_search_supports_partial_match(
    settings: Settings, initialized_databases
) -> None:
    assert search_cell_numbers(settings, query="126") == ["126"]


def test_empty_private_search_returns_no_numbers(
    settings: Settings, initialized_databases
) -> None:
    assert search_cell_numbers(settings, query="   ") == []


def test_invalid_stored_date_is_safe_integrity_error(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-07-09")
    paths = DatabasePaths.from_settings(settings)
    connection = sqlite3.connect(paths.working)
    try:
        connection.execute("UPDATE contracts SET end_date = 'bad-date' WHERE cell_number = '1'")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(InvalidStoredDataError, match="дата"):
        list_cells(settings, as_of_date=AS_OF)


def test_future_start_date_is_safe_integrity_error(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(
        cell_number="1", start_date="2026-07-02", end_date="2026-07-02"
    )
    with pytest.raises(InvalidStoredDataError, match="будущем"):
        list_cells(settings, as_of_date=AS_OF)


def test_invalid_expiring_config_is_safe_integrity_error(
    settings: Settings, initialized_databases
) -> None:
    paths = DatabasePaths.from_settings(settings)
    connection = sqlite3.connect(paths.working)
    try:
        connection.execute(
            "UPDATE config SET value = 'bad' WHERE key = 'expiring_soon_days'"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(InvalidStoredDataError, match="порог"):
        list_cells(settings, as_of_date=AS_OF)


def test_invalid_reminder_timestamp_is_safe_integrity_error(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-07-01")
    paths = DatabasePaths.from_settings(settings)
    connection = sqlite3.connect(paths.working)
    try:
        connection.execute(
            """
            UPDATE contracts
            SET last_reminded_at='bad-time', reminder_count=1
            WHERE cell_number='1'
            """
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(InvalidStoredDataError, match="оповещения"):
        list_cells(settings, as_of_date=AS_OF)
