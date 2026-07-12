from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from app import create_app
from app.config import Settings
from app.db.connections import DatabasePaths, open_write
from app.services.contract_details import (
    ActiveContractNotFoundError,
    ContractDetailsReadError,
    ContractDetailsValidationError,
    get_contract_client_name,
    get_private_contract_details,
)


def _insert_renewal(settings: Settings, *, contract_id: str = "contract-test-1") -> None:
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO archive.renewals(
                renewal_id, contract_id, cell_number,
                old_end_date, renewal_date, new_start_date, new_end_date,
                renewal_days, price_per_day_minor, renewal_price_minor,
                penalty_days, penalty_rate_minor, penalty_amount_minor,
                created_at, created_by, operation_id
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "renewal-test-1",
                contract_id,
                "1",
                "2026-07-09",
                "2026-07-08",
                "2026-07-10",
                "2026-08-08",
                30,
                15,
                450,
                0,
                15,
                0,
                "2026-07-08T09:00:00+06:00",
                "test-user",
                "renewal-operation-test-1",
            ),
        )
        connection.commit()


def test_private_details_are_read_only_and_include_hidden_history(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(
        cell_number="1",
        end_date="2026-07-09",
        client_name="Секретный Тестовый Клиент",
        account_number="PRIVATE-TEST-ACCOUNT",
    )
    _insert_renewal(settings)

    details = get_private_contract_details(
        settings, cell_number="1", contract_ref="contract-test-1"
    )

    assert details.cell_number == "1"
    assert details.client_full_name == "Секретный Тестовый Клиент"
    assert details.id_card_number == "TEST-ID-1"
    assert details.id_card_issuer == "Тестовый орган"
    assert details.id_card_issue_date == "2017-09-12"
    assert details.account_number == "PRIVATE-TEST-ACCOUNT"
    assert details.created_at == "2026-07-01T09:00:00+06:00"
    assert len(details.renewals) == 1
    assert details.renewals[0].renewal_price == 450
    assert details.renewals[0].new_end_date == "2026-08-08"

    paths = DatabasePaths.from_settings(settings)
    renamed_working = paths.working.with_suffix(".closed-check")
    renamed_archive = paths.archive.with_suffix(".closed-check")
    paths.working.rename(renamed_working)
    paths.archive.rename(renamed_archive)
    renamed_working.rename(paths.working)
    renamed_archive.rename(paths.archive)


def test_opened_card_reads_only_full_client_name(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(
        cell_number="1",
        end_date="2026-07-09",
        client_name="Иванов Арсен Саилович",
    )

    assert get_contract_client_name(
        settings, cell_number="1", contract_ref="contract-test-1"
    ) == "Иванов Арсен Саилович"


@pytest.mark.parametrize("cell_number", [None, "", "x" * 51])
def test_private_details_reject_invalid_cell_number(
    settings: Settings,
    initialized_databases,
    cell_number: object,
) -> None:
    with pytest.raises(ContractDetailsValidationError):
        get_private_contract_details(
            settings, cell_number=cell_number, contract_ref="contract-test-1"
        )


def test_private_details_reject_free_cell(
    settings: Settings, initialized_databases
) -> None:
    with pytest.raises(ActiveContractNotFoundError, match="свободна"):
        get_private_contract_details(
            settings, cell_number="1", contract_ref="missing-contract"
        )


def test_private_details_reject_stale_contract_reference(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-07-09")
    with pytest.raises(ActiveContractNotFoundError, match="договор уже закрыт"):
        get_private_contract_details(
            settings, cell_number="1", contract_ref="old-contract-reference"
        )


def test_private_details_require_contract_reference(
    settings: Settings, initialized_databases
) -> None:
    with pytest.raises(ContractDetailsValidationError, match="устарела"):
        get_private_contract_details(settings, cell_number="1", contract_ref=None)


def test_private_details_network_error_does_not_create_database(tmp_path: Path) -> None:
    missing = tmp_path / "offline network"
    settings = Settings(database_directory=missing, testing=True)
    with pytest.raises(ContractDetailsReadError, match="сетевого диска"):
        get_private_contract_details(
            settings, cell_number="1", contract_ref="contract-test-1"
        )
    assert not missing.exists()


def test_private_api_requires_instance_token_and_post(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-07-09")
    app = create_app(settings)
    client = app.test_client()
    token = app.extensions["safe_cells_private_token"]

    assert client.get("/api/contracts/private").status_code == 405
    assert client.post(
        "/api/contracts/private",
        json={"cell_number": "1", "contract_ref": "contract-test-1"},
    ).status_code == 403
    assert client.post(
        "/api/contracts/private",
        json={"cell_number": "1", "contract_ref": "contract-test-1"},
        headers={"X-Safe-Cells-Token": "wrong-token"},
    ).status_code == 403

    response = client.post(
        "/api/contracts/private",
        json={"cell_number": "1", "contract_ref": "contract-test-1"},
        headers={"X-Safe-Cells-Token": token},
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["client_full_name"] == "Тестовый Клиент"
    missing_ref = client.post(
        "/api/contracts/private",
        json={"cell_number": "1"},
        headers={"X-Safe-Cells-Token": token},
    )
    assert missing_ref.status_code == 400

    name_response = client.post(
        "/api/contracts/client-name",
        json={"cell_number": "1", "contract_ref": "contract-test-1"},
        headers={"X-Safe-Cells-Token": token},
    )
    assert name_response.status_code == 200
    assert name_response.get_json() == {"client_full_name": "Тестовый Клиент"}
    assert client.post(
        "/api/contracts/client-name",
        json={"cell_number": "1", "contract_ref": "contract-test-1"},
    ).status_code == 403


def test_private_api_returns_xss_marker_only_after_explicit_authorized_request(
    settings: Settings,
    insert_test_contract: Callable[..., None],
) -> None:
    marker = '<script data-private="true">alert(1)</script>'
    insert_test_contract(
        cell_number="1",
        end_date="2026-07-09",
        client_name=marker,
        account_number="PRIVATE-XSS-ACCOUNT",
    )
    app = create_app(settings)
    client = app.test_client()

    html = client.get("/").get_data(as_text=True)
    list_body = client.get("/api/cells").get_data(as_text=True)
    assert marker not in html
    assert marker not in list_body
    assert "PRIVATE-XSS-ACCOUNT" not in html
    assert "PRIVATE-XSS-ACCOUNT" not in list_body

    response = client.post(
        "/api/contracts/private",
        json={"cell_number": "1", "contract_ref": "contract-test-1"},
        headers={
            "X-Safe-Cells-Token": app.extensions["safe_cells_private_token"]
        },
    )
    assert response.status_code == 200
    assert response.get_json()["client_full_name"] == marker


def test_each_app_instance_has_a_different_private_token(settings: Settings) -> None:
    first = create_app(settings).extensions["safe_cells_private_token"]
    second = create_app(settings).extensions["safe_cells_private_token"]
    assert first != second
    assert len(first) >= 32
    assert len(second) >= 32
