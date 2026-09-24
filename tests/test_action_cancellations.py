from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from uuid import uuid4

import pytest

from app import create_app
from app.config import Settings
from app.db.connections import open_readonly, open_write
from app.services.action_cancellations import (
    ActionCancellationBusyError,
    ActionCancellationConflictError,
    ActionCancellationNetworkError,
    ActionCancellationWriteError,
    cancel_contract_action,
)
from app.services.backups import list_backup_sets
from app.services.contract_details import get_private_contract_details
from app.services.closures import ClosureConflictError, close_contract
from app.services.contracts import ContractConflictError, create_contract
from app.services.journal import list_journal_entries
from app.services.renewals import renew_contract


TODAY = date(2026, 7, 29)
WHEN = datetime.fromisoformat("2026-07-29T10:30:00+06:00")


def opening_payload(**overrides) -> dict:
    payload = {
        "operation_id": str(uuid4()),
        "cell_number": "1",
        "client_full_name": "Тестовый Клиент",
        "client_phone": "+996 (555) 000-001",
        "id_card_number": "TEST-ID-CANCEL",
        "id_card_issuer": "Тестовый орган",
        "id_card_issue_date": "2019-05-15",
        "account_number": "TEST-ACCOUNT-CANCEL",
        "start_date": TODAY.isoformat(),
        "end_date": "2026-08-27",
        "rent_days": 30,
    }
    payload.update(overrides)
    return payload


def cancellation_payload(
    *,
    original_operation_id: str,
    contract_ref: str,
    cell_number: str = "1",
    **overrides,
) -> dict:
    payload = {
        "cancellation_operation_id": str(uuid4()),
        "original_operation_id": original_operation_id,
        "contract_ref": contract_ref,
        "cell_number": cell_number,
        "reason_code": "client_changed",
    }
    payload.update(overrides)
    return payload


def renewal_payload(*, operation_id: str | None = None) -> dict:
    return {
        "operation_id": operation_id or str(uuid4()),
        "cell_number": "1",
        "contract_ref": "contract-test-1",
        "expected_end_date": "2026-07-28",
        "new_end_date": "2026-08-27",
        "renewal_days": 30,
    }


def closure_payload(*, operation_id: str | None = None, **overrides) -> dict:
    payload = {
        "operation_id": operation_id or str(uuid4()),
        "cell_number": "1",
        "contract_ref": "contract-test-1",
        "expected_end_date": "2026-08-10",
        "reason_code": "standard",
    }
    payload.update(overrides)
    return payload


def test_cancel_opening_frees_cell_but_preserves_archive_and_audit(
    settings: Settings, initialized_databases
) -> None:
    request = opening_payload()
    opened = create_contract(
        settings,
        payload=request,
        employee="Тестовый Сотрудник",
        occurred_at=WHEN,
        as_of_date=TODAY,
    )
    cancel_request = cancellation_payload(
        original_operation_id=request["operation_id"],
        contract_ref=opened.contract_id,
    )

    result = cancel_contract_action(
        settings,
        payload=cancel_request,
        employee="Тестовый Сотрудник",
        occurred_at=WHEN + timedelta(minutes=2),
    )

    assert result.action_kind == "opening"
    assert result.restored_end_date is None
    assert result.backup_created is True
    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        assert working.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 0
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        cancelled_contract = archive.execute(
            "SELECT client_full_name, close_reason FROM contracts_archive"
        ).fetchone()
        cancellation = archive.execute(
            "SELECT * FROM operation_cancellations"
        ).fetchone()
        actions = [
            row[0] for row in archive.execute("SELECT action FROM log ORDER BY rowid")
        ]
    assert tuple(cancelled_contract) == (
        "Тестовый Клиент",
        "Отмена открытия — Клиент изменил решение",
    )
    assert cancellation["original_operation_id"] == request["operation_id"]
    assert actions == ["contract.created", "contract.action_cancelled"]
    assert any(
        item.operation_id == cancel_request["cancellation_operation_id"]
        for item in list_backup_sets(settings)
    )

    journal = list_journal_entries(settings)
    assert [entry["action_label"] for entry in journal["entries"]] == [
        "Отмена",
        "Открытие",
    ]
    assert {entry["client_full_name"] for entry in journal["entries"]} == {
        "Тестовый Клиент"
    }


def test_cancel_opening_is_idempotent_and_original_request_cannot_reopen(
    settings: Settings, initialized_databases
) -> None:
    request = opening_payload()
    opened = create_contract(
        settings,
        payload=request,
        employee="Сотрудник",
        occurred_at=WHEN,
        as_of_date=TODAY,
    )
    cancel_request = cancellation_payload(
        original_operation_id=request["operation_id"],
        contract_ref=opened.contract_id,
    )
    first = cancel_contract_action(
        settings,
        payload=cancel_request,
        employee="Сотрудник",
        occurred_at=WHEN,
    )
    repeated = cancel_contract_action(
        settings,
        payload=cancel_request,
        employee="Сотрудник",
        occurred_at=WHEN,
    )

    assert repeated.cancellation_id == first.cancellation_id
    assert repeated.repeated is True
    with pytest.raises(ContractConflictError, match="уже отменено"):
        create_contract(
            settings,
            payload=request,
            employee="Сотрудник",
            occurred_at=WHEN,
            as_of_date=TODAY,
        )


def test_cancel_renewal_restores_old_end_and_marks_history(
    settings: Settings, initialized_databases, insert_test_contract
) -> None:
    insert_test_contract(
        cell_number="1",
        start_date="2026-06-29",
        end_date="2026-07-28",
    )
    renewal_request = renewal_payload()
    renewed = renew_contract(
        settings,
        payload=renewal_request,
        employee="Первый Сотрудник",
        renewal_date=TODAY,
        occurred_at=WHEN,
    )
    cancel_request = cancellation_payload(
        original_operation_id=renewal_request["operation_id"],
        contract_ref=renewed.contract_ref,
        reason_code="change_term",
    )

    result = cancel_contract_action(
        settings,
        payload=cancel_request,
        employee="Второй Сотрудник",
        occurred_at=WHEN + timedelta(minutes=3),
    )

    assert result.action_kind == "renewal"
    assert result.restored_end_date == "2026-07-28"
    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        contract = working.execute(
            "SELECT end_date, updated_by FROM contracts WHERE cell_number='1'"
        ).fetchone()
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        assert archive.execute("SELECT COUNT(*) FROM renewals").fetchone()[0] == 1
        marker = archive.execute(
            "SELECT reason_code, cancelled_by FROM operation_cancellations"
        ).fetchone()
    assert tuple(contract) == ("2026-07-28", "Второй Сотрудник")
    assert tuple(marker) == ("change_term", "Второй Сотрудник")

    details = get_private_contract_details(
        settings,
        cell_number="1",
        contract_ref="contract-test-1",
    )
    assert len(details.renewals) == 1
    assert details.renewals[0].cancelled is True
    assert details.renewals[0].cancellation_reason == "Нужно изменить срок"
    assert details.renewals[0].cancelled_by == "Второй Сотрудник"


def test_cancellation_rejects_later_contract_action_and_next_day(
    settings: Settings, initialized_databases, insert_test_contract
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-07-28")
    renewal_request = renewal_payload()
    renewed = renew_contract(
        settings,
        payload=renewal_request,
        employee="Сотрудник",
        renewal_date=TODAY,
        occurred_at=WHEN,
    )
    cancel_request = cancellation_payload(
        original_operation_id=renewal_request["operation_id"],
        contract_ref=renewed.contract_ref,
    )

    with pytest.raises(ActionCancellationConflictError, match="только в день"):
        cancel_contract_action(
            settings,
            payload=cancel_request,
            employee="Сотрудник",
            occurred_at=WHEN + timedelta(days=1),
        )

    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO archive.log(
                log_id, operation_id, occurred_at, employee, action,
                contract_id, cell_number, changes_json
            ) VALUES(?, ?, ?, ?, 'contract.edited', ?, ?, '{}')
            """,
            (
                str(uuid4()),
                str(uuid4()),
                (WHEN + timedelta(minutes=1)).isoformat(),
                "Другой Сотрудник",
                renewed.contract_ref,
                renewed.cell_number,
            ),
        )
        connection.commit()

    with pytest.raises(ActionCancellationConflictError, match="уже изменялся"):
        cancel_contract_action(
            settings,
            payload=cancel_request,
            employee="Сотрудник",
            occurred_at=WHEN + timedelta(minutes=2),
        )
    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        assert working.execute("SELECT end_date FROM contracts").fetchone()[0] == (
            "2026-08-27"
        )


def test_partial_failure_rolls_back_both_databases(
    settings: Settings, initialized_databases
) -> None:
    request = opening_payload()
    opened = create_contract(
        settings,
        payload=request,
        employee="Сотрудник",
        occurred_at=WHEN,
        as_of_date=TODAY,
    )
    cancel_request = cancellation_payload(
        original_operation_id=request["operation_id"],
        contract_ref=opened.contract_id,
    )

    def fail() -> None:
        raise RuntimeError("simulated failure")

    with pytest.raises(ActionCancellationWriteError, match="полностью откатились"):
        cancel_contract_action(
            settings,
            payload=cancel_request,
            employee="Сотрудник",
            occurred_at=WHEN,
            after_state_change=fail,
        )

    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        assert working.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        assert archive.execute(
            "SELECT COUNT(*) FROM contracts_archive"
        ).fetchone()[0] == 0
        assert archive.execute(
            "SELECT COUNT(*) FROM operation_cancellations"
        ).fetchone()[0] == 0
        assert archive.execute("SELECT COUNT(*) FROM log").fetchone()[0] == 1


def test_locked_and_missing_databases_do_not_partially_cancel(
    settings: Settings, initialized_databases, tmp_path
) -> None:
    request = opening_payload()
    opened = create_contract(
        settings,
        payload=request,
        employee="Сотрудник",
        occurred_at=WHEN,
        as_of_date=TODAY,
    )
    cancel_request = cancellation_payload(
        original_operation_id=request["operation_id"],
        contract_ref=opened.contract_id,
    )
    short = Settings(
        database_directory=settings.database_directory,
        busy_timeout_ms=40,
        testing=True,
    )
    with open_write(settings, attach_archive=True) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(ActionCancellationBusyError, match="Другая операция"):
            cancel_contract_action(
                short,
                payload=cancel_request,
                employee="Сотрудник",
                occurred_at=WHEN,
            )
        blocker.rollback()

    missing = tmp_path / "offline"
    with pytest.raises(ActionCancellationNetworkError, match="сетевого диска"):
        cancel_contract_action(
            Settings(database_directory=missing, testing=True),
            payload=cancel_request,
            employee="Сотрудник",
            occurred_at=WHEN,
        )
    assert not missing.exists()


def test_cancellation_api_uses_selected_actor_and_returns_no_personal_data(
    settings: Settings, initialized_databases
) -> None:
    request = opening_payload(client_full_name="НЕ ВОЗВРАЩАТЬ В API")
    opened = create_contract(
        settings,
        payload=request,
        employee="Сотрудник",
        occurred_at=WHEN,
        as_of_date=TODAY,
    )
    cancel_request = cancellation_payload(
        original_operation_id=request["operation_id"],
        contract_ref=opened.contract_id,
        reason_code="input_error",
    )
    app = create_app(settings)
    app.config["EMPLOYEE_PROVIDER"] = lambda: "Тестовый Руководитель"
    app.config["TIMESTAMP_PROVIDER"] = lambda: WHEN + timedelta(minutes=1)

    response = app.test_client().post(
        "/api/action-cancellations",
        json=cancel_request,
    )

    assert response.status_code == 201
    body = response.get_data(as_text=True)
    assert "НЕ ВОЗВРАЩАТЬ В API" not in body
    assert response.get_json()["action_kind"] == "opening"
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        audit = archive.execute(
            """
            SELECT employee, changes_json FROM log
            WHERE action='contract.action_cancelled'
            """
        ).fetchone()
    assert audit["employee"] == "Тестовый Руководитель"
    assert json.loads(audit["changes_json"])["reason"] == "Ошибка при вводе"


def test_cancel_standard_closure_restores_full_active_contract(
    settings: Settings, initialized_databases, insert_test_contract
) -> None:
    insert_test_contract(
        cell_number="1",
        start_date="2026-07-01",
        end_date="2026-08-10",
        client_name="Тестовый Клиент Закрытия",
    )
    with open_write(settings) as working:
        working.execute(
            "UPDATE contracts SET deposit_amount_minor=1500 WHERE cell_number='1'"
        )
        working.commit()
    close_request = closure_payload()
    close_contract(
        settings,
        payload=close_request,
        employee="Первый Сотрудник",
        close_date=TODAY,
        occurred_at=WHEN,
    )
    cancel_request = cancellation_payload(
        original_operation_id=close_request["operation_id"],
        contract_ref="contract-test-1",
        reason_code="client_changed",
    )

    result = cancel_contract_action(
        settings,
        payload=cancel_request,
        employee="Второй Сотрудник",
        occurred_at=WHEN + timedelta(minutes=2),
    )

    assert result.action_kind == "closure"
    assert result.restored_end_date == "2026-08-10"
    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        active = working.execute(
            """
            SELECT client_full_name, start_date, end_date, deposit_amount_minor
            FROM contracts WHERE contract_id='contract-test-1'
            """
        ).fetchone()
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        assert archive.execute(
            "SELECT COUNT(*) FROM contracts_archive"
        ).fetchone()[0] == 0
        marker = archive.execute(
            """
            SELECT original_action, cancelled_by
            FROM operation_cancellations
            """
        ).fetchone()
        actions = [
            row[0] for row in archive.execute("SELECT action FROM log ORDER BY rowid")
        ]
    assert tuple(active) == (
        "Тестовый Клиент Закрытия",
        "2026-07-01",
        "2026-08-10",
        1500,
    )
    assert tuple(marker) == ("contract.closed", "Второй Сотрудник")
    assert actions == ["contract.closed", "contract.action_cancelled"]
    journal = list_journal_entries(settings)
    assert journal["entries"][0]["action_label"] == "Отмена"
    assert journal["entries"][0]["summary"].startswith("Отменено закрытие")

    repeated = cancel_contract_action(
        settings,
        payload=cancel_request,
        employee="Второй Сотрудник",
        occurred_at=WHEN + timedelta(minutes=3),
    )
    assert repeated.repeated is True
    with pytest.raises(ClosureConflictError, match="закрытие уже отменено"):
        close_contract(
            settings,
            payload=close_request,
            employee="Первый Сотрудник",
            close_date=TODAY,
            occurred_at=WHEN,
        )


def test_cancel_lost_key_closure_removes_only_its_block(
    settings: Settings, initialized_databases, insert_test_contract
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-08-10")
    close_request = closure_payload(reason_code="lost_key")
    close_contract(
        settings,
        payload=close_request,
        employee="Сотрудник",
        close_date=TODAY,
        occurred_at=WHEN,
    )
    cancel_request = cancellation_payload(
        original_operation_id=close_request["operation_id"],
        contract_ref="contract-test-1",
    )

    cancel_contract_action(
        settings,
        payload=cancel_request,
        employee="Сотрудник",
        occurred_at=WHEN + timedelta(minutes=1),
    )

    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        assert working.execute(
            "SELECT COUNT(*) FROM contracts WHERE cell_number='1'"
        ).fetchone()[0] == 1
        assert working.execute(
            "SELECT COUNT(*) FROM cell_blocks WHERE cell_number='1'"
        ).fetchone()[0] == 0


def test_cancel_closure_rejects_later_cell_use(
    settings: Settings, initialized_databases, insert_test_contract
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-08-10")
    close_request = closure_payload()
    close_contract(
        settings,
        payload=close_request,
        employee="Сотрудник",
        close_date=TODAY,
        occurred_at=WHEN,
    )
    new_opening = opening_payload(
        cell_number="1",
        client_full_name="Другой Тестовый Клиент",
        end_date="2026-08-27",
    )
    create_contract(
        settings,
        payload=new_opening,
        employee="Сотрудник",
        occurred_at=WHEN + timedelta(minutes=1),
        as_of_date=TODAY,
    )

    with pytest.raises(ActionCancellationConflictError, match="уже изменялся"):
        cancel_contract_action(
            settings,
            payload=cancellation_payload(
                original_operation_id=close_request["operation_id"],
                contract_ref="contract-test-1",
            ),
            employee="Сотрудник",
            occurred_at=WHEN + timedelta(minutes=2),
        )


def test_cancel_closure_partial_failure_rolls_back_restoration(
    settings: Settings, initialized_databases, insert_test_contract
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-08-10")
    close_request = closure_payload()
    close_contract(
        settings,
        payload=close_request,
        employee="Сотрудник",
        close_date=TODAY,
        occurred_at=WHEN,
    )

    def fail() -> None:
        raise RuntimeError("simulated restoration failure")

    with pytest.raises(ActionCancellationWriteError, match="полностью откатились"):
        cancel_contract_action(
            settings,
            payload=cancellation_payload(
                original_operation_id=close_request["operation_id"],
                contract_ref="contract-test-1",
            ),
            employee="Сотрудник",
            occurred_at=WHEN + timedelta(minutes=1),
            after_state_change=fail,
        )

    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        assert working.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 0
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        assert archive.execute(
            "SELECT COUNT(*) FROM contracts_archive"
        ).fetchone()[0] == 1
        assert archive.execute(
            "SELECT COUNT(*) FROM operation_cancellations"
        ).fetchone()[0] == 0
