from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
import json
import sqlite3
from uuid import uuid4

import pytest

from app import create_app
from app.config import Settings
from app.db.connections import open_readonly, open_write
from app.services.closures import (
    ClosureBusyError, ClosureConflictError, ClosureNetworkError,
    ClosureValidationError, ClosureWriteError, ClosureWriteUncertainError,
    calculate_closure_quote, close_contract, closing_kind, closing_penalty_days,
)


TODAY = date(2026, 7, 12)
OCCURRED = datetime.fromisoformat("2026-07-12T11:00:00+06:00")


def payload(**overrides):
    data = {
        "operation_id": str(uuid4()), "cell_number": "1",
        "contract_ref": "contract-test-1", "expected_end_date": "2026-07-12",
        "reason_code": "standard",
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("close", "end", "kind", "penalty"),
    [
        (date(2026, 7, 11), date(2026, 7, 12), "early", 0),
        (date(2026, 7, 12), date(2026, 7, 12), "on_time", 0),
        (date(2026, 7, 13), date(2026, 7, 12), "overdue", 1),
        (date(2026, 7, 14), date(2026, 7, 12), "overdue", 2),
    ],
)
def test_closing_kind_and_penalty_formula(close, end, kind, penalty):
    assert closing_kind(close_date=close, end_date=end) == kind
    assert closing_penalty_days(close_date=close, end_date=end) == penalty


def test_early_quote_has_no_rent_refund_and_full_deposit(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", start_date="2026-07-01", end_date="2026-07-20")
    with open_write(settings) as con:
        con.execute("UPDATE contracts SET deposit_amount_minor=1500 WHERE cell_number='1'")
    quote = calculate_closure_quote(
        settings, cell_number="1", contract_ref="contract-test-1",
        close_date=TODAY, reason_code="standard",
    )
    assert quote.close_kind == "early"
    assert quote.unused_days == 8
    assert quote.rent_refund == 0
    assert quote.deposit_refund == 1500
    assert quote.penalty_amount == 0


def test_lost_key_retains_deposit_without_general_deduction_function(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-12")
    with open_write(settings) as con:
        con.execute("UPDATE contracts SET deposit_amount_minor=1500 WHERE cell_number='1'")
    quote = calculate_closure_quote(
        settings, cell_number="1", contract_ref="contract-test-1",
        close_date=TODAY, reason_code="lost_key",
    )
    assert quote.close_reason == "Потеря ключа"
    assert quote.deposit_amount == 1500
    assert quote.deposit_refund == 0
    assert not hasattr(quote, "deduction_amount")


def test_overdue_quote_uses_1_to_30_penalty_rate(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    quote = calculate_closure_quote(
        settings, cell_number="1", contract_ref="contract-test-1",
        close_date=TODAY, reason_code="standard",
    )
    assert quote.penalty_days == 2
    assert quote.penalty_rate == 15
    assert quote.penalty_amount == 30


def test_close_atomically_archives_audits_deletes_active_and_preserves_renewals(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-12")
    with open_write(settings, attach_archive=True) as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """INSERT INTO archive.renewals(
                renewal_id,contract_id,contract_number,cell_number,old_end_date,
                renewal_date,new_start_date,new_end_date,renewal_days,
                price_per_day_minor,renewal_price_minor,penalty_days,
                penalty_rate_minor,penalty_amount_minor,created_at,created_by,operation_id
            ) VALUES('r1','contract-test-1','TEST-1','1','2026-07-01','2026-07-02',
                     '2026-07-02','2026-07-12',11,15,165,0,15,0,
                     '2026-07-02T09:00:00+06:00','test','renew-op')"""
        )
        con.commit()
    request = payload()
    result = close_contract(
        settings, payload=request, employee="test-user", close_date=TODAY,
        occurred_at=OCCURRED,
    )
    assert result.close_kind == "on_time"
    assert result.backup_created is True
    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as con:
        assert con.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 0
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as con:
        archive = con.execute("SELECT * FROM contracts_archive").fetchone()
        audit = con.execute("SELECT * FROM log WHERE action='contract.closed'").fetchone()
        assert con.execute("SELECT COUNT(*) FROM renewals").fetchone()[0] == 1
    assert archive["client_full_name"] == "Тестовый Клиент"
    assert archive["close_reason"] == "Окончание срока"
    assert audit["employee"] == "test-user"
    changes = json.loads(audit["changes_json"])
    assert changes["rent_refund"] == 0
    assert "client" not in audit["changes_json"].lower()
    backup_dir = settings.database_directory / "backups"
    assert len(list(backup_dir.glob(f"*_{request['operation_id']}.*.sqlite3"))) == 2


def test_repeat_same_close_is_idempotent(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-12")
    request = payload()
    first = close_contract(settings, payload=request, employee="test", close_date=TODAY, occurred_at=OCCURRED)
    second = close_contract(settings, payload=request, employee="test", close_date=TODAY, occurred_at=OCCURRED)
    assert second.contract_ref == first.contract_ref
    assert second.repeated is True
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as con:
        assert con.execute("SELECT COUNT(*) FROM contracts_archive").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM log WHERE action='contract.closed'").fetchone()[0] == 1


def test_free_cell_stale_end_and_invalid_reason_are_rejected(
    settings, initialized_databases, insert_test_contract
):
    with pytest.raises(ClosureConflictError):
        calculate_closure_quote(
            settings, cell_number="1", contract_ref="missing",
            close_date=TODAY, reason_code="standard",
        )
    insert_test_contract(cell_number="1", end_date="2026-07-12")
    with pytest.raises(ClosureConflictError, match="Дата окончания"):
        close_contract(
            settings, payload=payload(expected_end_date="2026-07-11"), employee="test",
            close_date=TODAY, occurred_at=OCCURRED,
        )
    with pytest.raises(ClosureValidationError, match="причину"):
        calculate_closure_quote(
            settings, cell_number="1", contract_ref="contract-test-1",
            close_date=TODAY, reason_code="custom-deduction",
        )


@pytest.mark.parametrize("hook", ["after_archive_insert", "before_active_delete"])
def test_partial_failure_rolls_back_both_databases(
    settings, initialized_databases, insert_test_contract, hook
):
    insert_test_contract(cell_number="1", end_date="2026-07-12")
    kwargs = {hook: lambda: (_ for _ in ()).throw(RuntimeError("partial"))}
    with pytest.raises(ClosureWriteError, match="Изменения отменены"):
        close_contract(
            settings, payload=payload(), employee="test", close_date=TODAY,
            occurred_at=OCCURRED, **kwargs,
        )
    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as con:
        assert con.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as con:
        assert con.execute("SELECT COUNT(*) FROM contracts_archive").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM log").fetchone()[0] == 0


def test_concurrent_close_allows_one_success_and_one_conflict(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-12")
    requests = [payload(operation_id=str(uuid4())) for _ in range(2)]
    def run(request):
        try:
            return close_contract(settings, payload=request, employee="test", close_date=TODAY, occurred_at=OCCURRED)
        except ClosureConflictError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, requests))
    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert sum(isinstance(item, ClosureConflictError) for item in results) == 1


def test_lock_and_missing_path_do_not_partially_close(
    settings, initialized_databases, insert_test_contract, tmp_path: Path
):
    insert_test_contract(cell_number="1", end_date="2026-07-12")
    short = Settings(database_directory=settings.database_directory, busy_timeout_ms=40, testing=True)
    with open_write(settings, attach_archive=True) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(ClosureBusyError):
            close_contract(short, payload=payload(), employee="test", close_date=TODAY, occurred_at=OCCURRED)
        blocker.rollback()
    missing = tmp_path / "offline"
    with pytest.raises(ClosureNetworkError):
        close_contract(
            Settings(database_directory=missing, testing=True), payload=payload(),
            employee="test", close_date=TODAY, occurred_at=OCCURRED,
        )
    assert not missing.exists()


def test_uncertain_commit_is_safe_to_repeat(
    settings, initialized_databases, insert_test_contract, monkeypatch
):
    insert_test_contract(cell_number="1", end_date="2026-07-12")
    real = open_write
    class Disconnect:
        def __init__(self, con): self.con = con
        def __getattr__(self, name): return getattr(self.con, name)
        def commit(self):
            self.con.commit()
            raise sqlite3.OperationalError("disconnect")
    @contextmanager
    def uncertain(arg, *, attach_archive=False):
        with real(arg, attach_archive=attach_archive) as con:
            yield Disconnect(con)
    request = payload()
    monkeypatch.setattr("app.services.closures.open_write", uncertain)
    with pytest.raises(ClosureWriteUncertainError):
        close_contract(settings, payload=request, employee="test", close_date=TODAY, occurred_at=OCCURRED)
    monkeypatch.setattr("app.services.closures.open_write", real)
    assert close_contract(settings, payload=request, employee="test", close_date=TODAY, occurred_at=OCCURRED).repeated


def test_closure_api_uses_server_date_and_returns_no_personal_data(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-10", client_name="PRIVATE-NAME")
    app = create_app(settings)
    app.config["TODAY_PROVIDER"] = lambda: TODAY
    app.config["TIMESTAMP_PROVIDER"] = lambda: OCCURRED
    client = app.test_client()
    quote = client.post(
        "/api/closures/calculate",
        json={"cell_number":"1","contract_ref":"contract-test-1","reason_code":"standard"},
    )
    assert quote.status_code == 200
    assert quote.get_json()["penalty_days"] == 2
    response = client.post("/api/closures", json=payload(expected_end_date="2026-07-10"))
    assert response.status_code == 201
    assert "PRIVATE-NAME" not in response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "no-store"
