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
from app.services.renewals import (
    RenewalBusyError,
    RenewalConflictError,
    RenewalNetworkError,
    RenewalValidationError,
    RenewalWriteError,
    RenewalWriteUncertainError,
    calculate_renewal_quote,
    renew_contract,
    renewal_penalty_days,
    renewal_start_date,
)


TODAY = date(2026, 7, 12)
OCCURRED_AT = datetime.fromisoformat("2026-07-12T10:30:00+06:00")


def payload(**overrides) -> dict:
    data = {
        "operation_id": str(uuid4()),
        "cell_number": "1",
        "contract_ref": "contract-test-1",
        "expected_end_date": "2026-07-10",
        "new_end_date": "2026-08-10",
        "renewal_days": 30,
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("renewal", "old_end", "expected_start", "penalty"),
    [
        (date(2026, 7, 9), date(2026, 7, 10), date(2026, 7, 11), 0),
        (date(2026, 7, 10), date(2026, 7, 10), date(2026, 7, 11), 0),
        (date(2026, 7, 11), date(2026, 7, 10), date(2026, 7, 11), 0),
        (date(2026, 7, 12), date(2026, 7, 10), date(2026, 7, 12), 1),
    ],
)
def test_approved_start_and_penalty_rules(renewal, old_end, expected_start, penalty):
    assert renewal_start_date(renewal_date=renewal, old_end_date=old_end) == expected_start
    assert renewal_penalty_days(renewal_date=renewal, old_end_date=old_end) == penalty


@pytest.mark.parametrize(
    ("days", "expected_rate"),
    [(1, 15), (30, 15), (31, 10), (90, 10), (91, 8), (180, 8), (181, 7)],
)
def test_renewal_tariff_boundaries_and_penalty_rate(
    settings: Settings, initialized_databases, insert_test_contract, days, expected_rate
):
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    start = TODAY
    end = start.fromordinal(start.toordinal() + days - 1)
    quote = calculate_renewal_quote(
        settings,
        cell_number="1",
        contract_ref="contract-test-1",
        renewal_date=TODAY,
        new_end_date_value=end.isoformat(),
        renewal_days_value=days,
    )
    assert quote.new_start_date == "2026-07-12"
    assert quote.price_per_day == expected_rate
    assert quote.renewal_price == days * expected_rate
    assert quote.penalty_days == 1
    assert quote.penalty_rate == 15
    assert quote.penalty_amount == 15


def test_confirmed_renewal_updates_end_and_writes_history_audit_and_backups(
    settings: Settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    request = payload()
    result = renew_contract(
        settings, payload=request, employee="test-user", renewal_date=TODAY,
        occurred_at=OCCURRED_AT,
    )
    assert result.new_end_date == "2026-08-10"
    assert result.renewal_days == 30
    assert result.penalty_days == 1
    assert result.total_amount == 465
    assert result.backup_created is True

    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        contract = working.execute("SELECT * FROM contracts WHERE cell_number='1'").fetchone()
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        renewal = archive.execute("SELECT * FROM renewals").fetchone()
        audit = archive.execute("SELECT * FROM log").fetchone()
    assert contract["start_date"] == "2026-07-10"
    assert contract["rent_days"] == 1
    assert contract["rent_price_minor"] == 15
    assert contract["end_date"] == "2026-08-10"
    assert renewal["old_end_date"] == "2026-07-10"
    assert renewal["new_start_date"] == "2026-07-12"
    assert audit["action"] == "contract.renewed"
    changes = json.loads(audit["changes_json"])
    assert "client" not in audit["changes_json"].lower()
    assert changes["penalty_amount"] == 15
    backup_dir = settings.database_directory / "backups"
    assert len(list(backup_dir.glob(f"*_{request['operation_id']}.*.sqlite3"))) == 2


def test_repeat_same_operation_is_idempotent(
    settings: Settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    request = payload()
    first = renew_contract(
        settings, payload=request, employee="test-user", renewal_date=TODAY,
        occurred_at=OCCURRED_AT,
    )
    second = renew_contract(
        settings, payload=request, employee="test-user", renewal_date=TODAY,
        occurred_at=OCCURRED_AT,
    )
    assert second.renewal_id == first.renewal_id
    assert second.repeated is True
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM renewals").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM log").fetchone()[0] == 1


def test_stale_end_or_contract_reference_is_rejected(
    settings: Settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    with pytest.raises(RenewalConflictError, match="Дата окончания"):
        renew_contract(
            settings, payload=payload(expected_end_date="2026-07-09"),
            employee="test-user", renewal_date=TODAY, occurred_at=OCCURRED_AT,
        )
    with pytest.raises(RenewalConflictError, match="Договор изменился"):
        calculate_renewal_quote(
            settings, cell_number="1", contract_ref="stale-ref", renewal_date=TODAY,
            renewal_days_value=1,
        )


def test_free_cell_and_invalid_period_are_rejected(
    settings: Settings, initialized_databases, insert_test_contract
):
    with pytest.raises(RenewalConflictError):
        calculate_renewal_quote(
            settings, cell_number="1", contract_ref="missing", renewal_date=TODAY,
            renewal_days_value=1,
        )
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    with pytest.raises(RenewalValidationError, match="раньше начала"):
        calculate_renewal_quote(
            settings, cell_number="1", contract_ref="contract-test-1",
            renewal_date=TODAY, new_end_date_value="2026-07-11",
        )
    with pytest.raises(RenewalValidationError, match="не соответствует"):
        calculate_renewal_quote(
            settings, cell_number="1", contract_ref="contract-test-1",
            renewal_date=TODAY, new_end_date_value="2026-07-20", renewal_days_value=3,
        )


def test_partial_failure_rolls_back_both_databases(
    settings: Settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    def fail():
        raise RuntimeError("simulated partial failure")
    with pytest.raises(RenewalWriteError, match="Изменения отменены"):
        renew_contract(
            settings, payload=payload(), employee="test-user", renewal_date=TODAY,
            occurred_at=OCCURRED_AT, after_renewal_insert=fail,
        )
    with open_readonly(settings.database_directory / "vault_cells.sqlite3") as working:
        assert working.execute("SELECT end_date FROM contracts").fetchone()[0] == "2026-07-10"
    with open_readonly(settings.database_directory / "vault_archive.sqlite3") as archive:
        assert archive.execute("SELECT COUNT(*) FROM renewals").fetchone()[0] == 0
        assert archive.execute("SELECT COUNT(*) FROM log").fetchone()[0] == 0


def test_concurrent_renewals_from_same_old_end_allow_only_one(
    settings: Settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    requests = [payload(operation_id=str(uuid4())) for _ in range(2)]
    def run(request):
        try:
            return renew_contract(
                settings, payload=request, employee="parallel-user", renewal_date=TODAY,
                occurred_at=OCCURRED_AT,
            )
        except RenewalConflictError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, requests))
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, RenewalConflictError) for result in results) == 1


def test_locked_and_missing_databases_are_safe(
    settings: Settings, initialized_databases, insert_test_contract, tmp_path: Path
):
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    short = Settings(database_directory=settings.database_directory, busy_timeout_ms=40, testing=True)
    with open_write(settings, attach_archive=True) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(RenewalBusyError, match="Другая операция"):
            renew_contract(
                short, payload=payload(), employee="test-user", renewal_date=TODAY,
                occurred_at=OCCURRED_AT,
            )
        blocker.rollback()
    missing = tmp_path / "offline"
    with pytest.raises(RenewalNetworkError, match="сетевого диска"):
        renew_contract(
            Settings(database_directory=missing, testing=True), payload=payload(),
            employee="test-user", renewal_date=TODAY, occurred_at=OCCURRED_AT,
        )
    assert not missing.exists()


def test_uncertain_commit_can_be_checked_by_repeating_same_operation(
    settings: Settings, initialized_databases, insert_test_contract, monkeypatch
):
    insert_test_contract(cell_number="1", end_date="2026-07-10")
    real_open_write = open_write
    class CommitThenDisconnect:
        def __init__(self, connection): self.connection = connection
        def __getattr__(self, name): return getattr(self.connection, name)
        def commit(self):
            self.connection.commit()
            raise sqlite3.OperationalError("simulated disconnect")
    @contextmanager
    def uncertain(settings_arg, *, attach_archive=False):
        with real_open_write(settings_arg, attach_archive=attach_archive) as connection:
            yield CommitThenDisconnect(connection)
    request = payload()
    monkeypatch.setattr("app.services.renewals.open_write", uncertain)
    with pytest.raises(RenewalWriteUncertainError, match="Не повторяйте"):
        renew_contract(
            settings, payload=request, employee="test-user", renewal_date=TODAY,
            occurred_at=OCCURRED_AT,
        )
    monkeypatch.setattr("app.services.renewals.open_write", real_open_write)
    assert renew_contract(
        settings, payload=request, employee="test-user", renewal_date=TODAY,
        occurred_at=OCCURRED_AT,
    ).repeated is True


def test_renewal_api_uses_server_date_and_does_not_return_personal_data(
    settings: Settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-07-10", client_name="PRIVATE-NAME")
    app = create_app(settings)
    app.config["TODAY_PROVIDER"] = lambda: TODAY
    app.config["TIMESTAMP_PROVIDER"] = lambda: OCCURRED_AT
    client = app.test_client()
    quote_response = client.post(
        "/api/renewals/calculate",
        json={"cell_number": "1", "contract_ref": "contract-test-1", "renewal_days": 30},
    )
    assert quote_response.status_code == 200
    assert quote_response.get_json()["renewal_date"] == "2026-07-12"
    response = client.post("/api/renewals", json=payload())
    assert response.status_code == 201
    body = response.get_data(as_text=True)
    assert "PRIVATE-NAME" not in body
    assert response.headers["Cache-Control"] == "no-store"
