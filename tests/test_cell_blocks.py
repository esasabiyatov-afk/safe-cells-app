from __future__ import annotations

from datetime import date, datetime
import json
from uuid import uuid4

import pytest

from app import create_app
from app.config import Settings
from app.db.connections import open_readonly, open_write
from app.services.cell_blocks import (
    CellBlockBusyError,
    CellBlockConflictError,
    lost_key_client_name,
    occupy_cell_manually,
    release_cell_block,
)
from app.services.cells import list_cells, search_cell_numbers
from app.services.closures import close_contract
from app.services.rental_calculator import CellUnavailableError, calculate_rental_quote


WHEN = datetime.fromisoformat("2026-07-16T10:00:00+06:00")


def _payload(cell_number: str = "1") -> dict[str, str]:
    return {"operation_id": str(uuid4()), "cell_number": cell_number}


def _manual_payload(
    cell_number: str = "1", occupation_label: str = "Служебное хранение"
) -> dict[str, str]:
    return {**_payload(cell_number), "occupation_label": occupation_label}


def test_manual_occupation_has_custom_label_no_term_and_can_be_released(
    settings, initialized_databases
):
    request = _manual_payload(occupation_label="Внутренняя проверка")
    first = occupy_cell_manually(
        settings, payload=request, employee="Тестовый Сотрудник", occurred_at=WHEN
    )
    repeated = occupy_cell_manually(
        settings, payload=request, employee="Тестовый Сотрудник", occurred_at=WHEN
    )

    assert first.block_kind == "manual" and first.repeated is False
    assert first.occupation_label == "Внутренняя проверка"
    assert repeated.repeated is True
    cells_payload = list_cells(settings, as_of_date=date(2026, 7, 16))
    cell = cells_payload["cells"][0]
    assert cell["status"] == "normal"
    assert cell["client_display_name"] == "Внутренняя проверка"
    assert cell["occupation_label"] == "Внутренняя проверка"
    assert cell["start_date"] is None and cell["end_date"] is None
    assert cell["rent_days"] is None and cell["days_remaining"] is None
    assert cells_payload["counts"] == {
        "free": 125, "normal": 1, "expiring": 0, "overdue": 0
    }
    assert search_cell_numbers(settings, query="внутренняя") == ["1"]
    with pytest.raises(CellUnavailableError, match="занята"):
        calculate_rental_quote(
            settings,
            cell_number="1",
            start_date_value="2026-07-16",
            rent_days_value=1,
            as_of_date=date(2026, 7, 16),
        )

    released = release_cell_block(
        settings,
        payload=_payload(),
        expected_kind="manual",
        employee="Тестовый Сотрудник",
        occurred_at=WHEN,
    )

    assert released.block_kind == "manual"
    assert list_cells(settings, as_of_date=date(2026, 7, 16))["cells"][0][
        "status"
    ] == "free"
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        logs = archive.execute(
            "SELECT action, contract_id, changes_json FROM log ORDER BY occurred_at, rowid"
        ).fetchall()
    assert [row["action"] for row in logs] == [
        "cell.manual_occupied",
        "cell.manual_released",
    ]
    assert all(row["contract_id"] is None for row in logs)
    assert all(json.loads(row["changes_json"]) == {"block_kind": "manual"} for row in logs)
    assert "Сотрудник" not in "".join(row["changes_json"] for row in logs)
    assert "Внутренняя проверка" not in "".join(row["changes_json"] for row in logs)


def test_lost_key_client_is_resolved_from_archive_and_key_restore_frees_cell(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(
        cell_number="1",
        start_date="2026-07-01",
        end_date="2026-07-16",
        client_name="Вымышленный Клиент Ключа",
    )
    close_contract(
        settings,
        payload={
            "operation_id": str(uuid4()),
            "cell_number": "1",
            "contract_ref": "contract-test-1",
            "expected_end_date": "2026-07-16",
            "reason_code": "lost_key",
        },
        employee="Тестовый Сотрудник",
        close_date=date(2026, 7, 16),
        occurred_at=WHEN,
    )

    cells_payload = list_cells(settings, as_of_date=date(2026, 7, 16))
    cell = cells_payload["cells"][0]
    assert cell["status"] == "normal"
    assert cell["client_display_name"] == "Ключ утерян"
    assert lost_key_client_name(settings, cell_number="1") == "Вымышленный Клиент Ключа"
    assert search_cell_numbers(settings, query="клиент ключа") == ["1"]
    assert cells_payload["counts"]["normal"] == 1

    release_cell_block(
        settings,
        payload=_payload(),
        expected_kind="lost_key",
        employee="Другой Тестовый Сотрудник",
        occurred_at=WHEN,
    )

    assert list_cells(settings, as_of_date=date(2026, 7, 16))["cells"][0][
        "status"
    ] == "free"
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        restored = archive.execute(
            "SELECT contract_id, changes_json FROM log WHERE action='cell.key_restored'"
        ).fetchone()
    assert restored["contract_id"] == "contract-test-1"
    assert "Вымышленный" not in restored["changes_json"]


def test_manual_occupation_rechecks_current_state_inside_transaction(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-16")

    with pytest.raises(CellBlockConflictError, match="уже занята"):
        occupy_cell_manually(
            settings,
            payload=_manual_payload(),
            employee="Тестовый Сотрудник",
            occurred_at=WHEN,
        )

    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        assert working.execute("SELECT COUNT(*) FROM cell_blocks").fetchone()[0] == 0


def test_manual_occupation_reports_busy_database_without_partial_write(
    settings, initialized_databases
):
    short = Settings(
        database_directory=settings.database_directory,
        busy_timeout_ms=50,
        testing=True,
    )
    with open_write(settings) as locker:
        locker.execute("BEGIN IMMEDIATE")
        with pytest.raises(CellBlockBusyError):
            occupy_cell_manually(
                short,
                payload=_manual_payload(),
                employee="Тестовый Сотрудник",
                occurred_at=WHEN,
            )
        locker.rollback()

    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        assert working.execute("SELECT COUNT(*) FROM cell_blocks").fetchone()[0] == 0


def test_cell_block_routes_require_employee_and_protect_lost_key_name(
    settings, initialized_databases
):
    app = create_app(settings)
    app.config["NOW_PROVIDER"] = lambda: WHEN
    client = app.test_client()

    assert client.post("/api/cell-blocks/manual", json=_manual_payload()).status_code == 409
    app.config["EMPLOYEE_PROVIDER"] = lambda: "Тестовый Сотрудник"
    response = client.post("/api/cell-blocks/manual", json=_manual_payload())
    assert response.status_code == 201
    assert client.post(
        "/api/cell-blocks/lost-key-client", json={"cell_number": "1"}
    ).status_code == 403


@pytest.mark.parametrize("label", ["", "   ", "x" * 81])
def test_manual_occupation_rejects_invalid_label(
    settings, initialized_databases, label
):
    with pytest.raises(ValueError, match="Пометка"):
        occupy_cell_manually(
            settings,
            payload=_manual_payload(occupation_label=label),
            employee="Тестовый Сотрудник",
            occurred_at=WHEN,
        )
