from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Callable
from uuid import uuid4

import pytest

from app import create_app
from app.config import Settings
from app.db.connections import DatabasePaths, open_readonly
from app.services.editing import EditingConflictError, EditingValidationError, edit_contract

WHEN = datetime(2026, 7, 13, 9, 0, tzinfo=timezone(timedelta(hours=6)))

def payload(**overrides):
    value = {"operation_id": str(uuid4()), "contract_ref": "contract-test-1", "cell_number": "1",
        "client_full_name": "Исправленный Клиент", "id_card_number": "NEW-ID",
        "id_card_issuer": "Новый орган", "id_card_issue_date": "2020-01-01", "account_number": "NEW-ACCOUNT"}
    value.update(overrides); return value

def test_edit_updates_active_contract_and_writes_full_audit(
    settings: Settings, insert_test_contract: Callable[..., None]
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-07-20")
    result = edit_contract(settings, payload=payload(), employee="editor", occurred_at=WHEN)
    assert result.repeated is False and result.backup_created is True
    paths = DatabasePaths.from_settings(settings)
    with open_readonly(paths.working) as con:
        row = con.execute("SELECT * FROM contracts WHERE cell_number='1'").fetchone()
        assert row["client_full_name"] == "Исправленный Клиент"
        assert row["start_date"] == "2026-07-20"
        assert row["updated_by"] == "editor"
    with open_readonly(paths.archive) as con:
        audit = con.execute("SELECT * FROM log WHERE action='contract.edited'").fetchone()
        changes = json.loads(audit["changes_json"])
        assert changes["client_full_name"] == {"old": "Тестовый Клиент", "new": "Исправленный Клиент"}


def test_edit_can_link_abs_id_but_cannot_replace_it(settings, insert_test_contract):
    insert_test_contract(cell_number="1", end_date="2026-07-20")
    edit_contract(
        settings,
        payload=payload(abs_customer_id="777"),
        employee="editor",
        occurred_at=WHEN,
    )
    with pytest.raises(EditingConflictError, match="другому ID"):
        edit_contract(
            settings,
            payload=payload(
                operation_id=str(uuid4()),
                client_full_name="Ещё одно имя",
                abs_customer_id="778",
            ),
            employee="editor",
            occurred_at=WHEN,
        )

def test_edit_rejects_forbidden_financial_or_date_field(settings, initialized_databases):
    with pytest.raises(EditingValidationError, match="запрещённое"):
        edit_contract(settings, payload=payload(end_date="2030-01-01"), employee="editor", occurred_at=WHEN)

def test_edit_rejects_stale_contract(settings, insert_test_contract):
    insert_test_contract(cell_number="1", end_date="2026-07-20")
    with pytest.raises(EditingConflictError, match="изменён или закрыт"):
        edit_contract(settings, payload=payload(contract_ref="stale"), employee="editor", occurred_at=WHEN)

def test_edit_rejects_no_changes(settings, insert_test_contract):
    insert_test_contract(cell_number="1", end_date="2026-07-20")
    unchanged = payload(client_full_name="Тестовый Клиент", id_card_number="TEST-ID-1",
        id_card_issuer="Тестовый орган", id_card_issue_date="2017-09-12", account_number="TEST-ACCOUNT")
    with pytest.raises(EditingValidationError, match="не изменены"):
        edit_contract(settings, payload=unchanged, employee="editor", occurred_at=WHEN)

def test_edit_api(settings, insert_test_contract):
    insert_test_contract(cell_number="1", end_date="2026-07-20")
    app = create_app(settings); app.config["TIMESTAMP_PROVIDER"] = lambda: WHEN
    app.config["EMPLOYEE_PROVIDER"] = lambda: "Тестовый Сотрудник"
    response = app.test_client().post("/api/contracts/edit", json=payload())
    assert response.status_code == 200
    assert response.get_json()["cell_number"] == "1"

def test_repeated_edit_operation_does_not_duplicate_audit(settings, insert_test_contract):
    insert_test_contract(cell_number="1", end_date="2026-07-20")
    edit_payload = payload()
    first = edit_contract(settings, payload=edit_payload, employee="editor", occurred_at=WHEN)
    second = edit_contract(settings, payload=edit_payload, employee="editor", occurred_at=WHEN)
    assert first.repeated is False and second.repeated is True
    paths = DatabasePaths.from_settings(settings)
    with open_readonly(paths.archive) as con:
        assert con.execute("SELECT COUNT(*) FROM log WHERE action='contract.edited'").fetchone()[0] == 1

def test_edit_rejects_future_id_card_issue_date(settings, insert_test_contract):
    insert_test_contract(cell_number="1", end_date="2026-07-20")
    with pytest.raises(EditingValidationError, match="не может быть в будущем"):
        edit_contract(
            settings,
            payload=payload(id_card_issue_date="2026-07-14"),
            employee="editor",
            occurred_at=WHEN,
        )
