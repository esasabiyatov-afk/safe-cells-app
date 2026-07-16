from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app import create_app
from app.config import Settings
from app.db.connections import NETWORK_ERROR_MESSAGE, open_write
from app.services.journal import (
    JournalReadError,
    JournalValidationError,
    list_journal_entries,
)


def _insert_log(
    settings: Settings,
    *,
    occurred_at: str,
    action: str,
    cell_number: str | None,
    changes: dict[str, object],
    employee: str = "Тестовый сотрудник",
) -> None:
    operation_id = str(uuid4())
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO archive.log(
                log_id, operation_id, occurred_at, employee, action,
                contract_id, cell_number, changes_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                operation_id,
                occurred_at,
                employee,
                action,
                f"contract-{operation_id}",
                cell_number,
                json.dumps(changes, ensure_ascii=False),
            ),
        )
        connection.commit()


def _insert_sample_entries(settings: Settings) -> None:
    _insert_log(
        settings,
        occurred_at="2026-07-01T09:00:00+06:00",
        action="contract.created",
        cell_number="7",
        changes={
            "start_date": "2026-07-01",
            "end_date": "2026-07-30",
            "rent_days": 30,
            "client_full_name": "НЕ ДОЛЖНО ПОПАСТЬ В ЖУРНАЛ",
        },
    )
    _insert_log(
        settings,
        occurred_at="2026-07-10T10:30:00+06:00",
        action="contract.renewed",
        cell_number="7",
        changes={
            "old_end_date": "2026-07-30",
            "new_end_date": "2026-08-30",
            "renewal_days": 31,
            "penalty_days": 0,
        },
        employee="Второй сотрудник",
    )
    _insert_log(
        settings,
        occurred_at="2026-07-11T11:00:00+06:00",
        action="contract.edited",
        cell_number="9",
        changes={
            "client_full_name": {
                "old": "СЕКРЕТНОЕ СТАРОЕ ФИО",
                "new": "СЕКРЕТНОЕ НОВОЕ ФИО",
            },
            "account_number": {"old": "SECRET-OLD", "new": "SECRET-NEW"},
        },
    )
    _insert_log(
        settings,
        occurred_at="2026-07-12T12:00:00+06:00",
        action="contract.closed",
        cell_number="7",
        changes={
            "close_date": "2026-07-12",
            "close_reason": "Досрочное расторжение",
            "penalty_days": 0,
            "id_card_number": "SECRET-ID",
        },
    )
    _insert_log(
        settings,
        occurred_at="2026-07-13T12:00:00+06:00",
        action="admin.settings.updated",
        cell_number=None,
        changes={"deposit_amount": {"old": 1500, "new": 1600}},
    )


def test_journal_returns_only_cell_events_and_safe_summaries(
    settings: Settings, initialized_databases
) -> None:
    _insert_sample_entries(settings)

    payload = list_journal_entries(settings)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert [entry["action"] for entry in payload["entries"]] == [
        "contract.closed",
        "contract.edited",
        "contract.renewed",
        "contract.created",
    ]
    assert payload["pagination"]["total"] == 4
    assert "admin.settings.updated" not in serialized
    assert "НЕ ДОЛЖНО" not in serialized
    assert "СЕКРЕТНОЕ" not in serialized
    assert "SECRET-" not in serialized
    assert "SECRET-ID" not in serialized
    assert "Исправлены данные активного договора" in serialized
    assert "01.07.2026 — 30.07.2026" in serialized


def test_journal_filters_and_paginates_with_parameterized_values(
    settings: Settings, initialized_databases
) -> None:
    _insert_sample_entries(settings)

    first = list_journal_entries(settings, cell_number="7", page=1, page_size=2)
    second = list_journal_entries(settings, cell_number="7", page=2, page_size=2)
    filtered = list_journal_entries(
        settings,
        action="contract.renewed",
        date_from="2026-07-10",
        date_to="2026-07-10",
    )
    injection = list_journal_entries(settings, cell_number="7' OR 1=1 --")

    assert first["pagination"] == {
        "page": 1,
        "page_size": 2,
        "page_count": 2,
        "total": 3,
        "has_previous": False,
        "has_next": True,
    }
    assert len(first["entries"]) == 2
    assert len(second["entries"]) == 1
    assert [entry["action"] for entry in filtered["entries"]] == [
        "contract.renewed"
    ]
    assert injection["entries"] == []


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"action": "admin.settings.updated"}, "допустимое действие"),
        ({"date_from": "2026-07-02", "date_to": "2026-07-01"}, "раньше"),
        ({"date_from": "01.07.2026"}, "корректную дату"),
        ({"page": 0}, "от 1"),
        ({"page_size": 101}, "от 1 до 100"),
    ],
)
def test_journal_rejects_invalid_filters(
    settings: Settings, initialized_databases, arguments: dict[str, object], message: str
) -> None:
    with pytest.raises(JournalValidationError, match=message):
        list_journal_entries(settings, **arguments)


def test_journal_unavailable_path_does_not_create_local_database(tmp_path: Path) -> None:
    missing = tmp_path / "offline journal data"
    settings = Settings(database_directory=missing, testing=True)

    with pytest.raises(JournalReadError, match=NETWORK_ERROR_MESSAGE):
        list_journal_entries(settings)

    assert not missing.exists()


def test_journal_api_requires_employee_and_returns_safe_page(
    settings: Settings, initialized_databases
) -> None:
    _insert_sample_entries(settings)
    app = create_app(settings)
    client = app.test_client()

    missing_employee = client.get("/api/journal")
    assert missing_employee.status_code == 409
    assert missing_employee.get_json()["selection_required"] is True

    app.config["EMPLOYEE_PROVIDER"] = lambda: "Тестовый сотрудник"
    response = client.get(
        "/api/journal?cell_number=7&action=contract.closed&date_from=2026-07-01&page=1"
    )
    serialized = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.get_json()["pagination"]["total"] == 1
    assert response.get_json()["entries"][0]["action_label"] == "Договор закрыт"
    assert "SECRET-ID" not in serialized
    assert client.get("/api/journal?action=unknown").status_code == 400


def test_journal_interface_uses_text_content_and_local_assets(
    settings: Settings, initialized_databases
) -> None:
    app = create_app(settings)
    client = app.test_client()

    html = client.get("/").get_data(as_text=True)
    script = client.get("/static/js/journal.js").get_data(as_text=True)

    assert 'data-journal-url="/api/journal"' in html
    assert 'src="/static/js/journal.js"' in html
    assert 'id="journalOpen"' in html
    assert 'id="journalDialog"' in html
    assert "Общий журнал ячеек" in html
    assert "без персональных данных клиентов" in html
    assert "innerHTML" not in script
    assert "textContent" in script
    assert "URLSearchParams" in script
    assert 'event.preventDefault()' in script
