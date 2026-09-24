from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app import create_app
from app.db.connections import open_readonly


NOW = datetime(2026, 7, 27, 9, 15, tzinfo=timezone(timedelta(hours=6)))
ADMIN_NAME = "Начальник Отдела"
EMPLOYEE_NAME = "Аманова Залия"
PASSWORD = "7"


def _private_headers(app) -> dict[str, str]:
    return {
        "X-Safe-Cells-Token": app.extensions["safe_cells_private_token"],
        "Content-Type": "application/json",
    }


def _contract_payload(employee_id: str | None = None) -> dict:
    payload = {
        "operation_id": str(uuid4()),
        "cell_number": "1",
        "client_full_name": "Тестовый Клиент",
        "client_phone": "+996 (555) 123-456",
        "id_card_number": "TEST-ID-001",
        "id_card_issuer": "Тестовый орган",
        "id_card_issue_date": "2017-09-12",
        "account_number": "TEST-ACCOUNT-001",
        "start_date": "2026-07-27",
        "end_date": "2026-08-25",
        "rent_days": 30,
    }
    if employee_id is not None:
        payload["document_employee_id"] = employee_id
    return payload


def test_admin_identity_is_selected_once_and_documents_require_executor(
    settings, initialized_databases, monkeypatch
):
    app = create_app(settings)
    app.config.update(
        TODAY_PROVIDER=lambda: date(2026, 7, 27),
        TIMESTAMP_PROVIDER=lambda: NOW,
    )
    client = app.test_client()
    headers = _private_headers(app)

    directory = client.get("/api/employee").get_json()
    assert directory["admin"] == {
        "configured": False,
        "full_name": None,
        "password_configured": False,
        "profile_configured": False,
    }

    selected = client.post(
        "/api/employee/admin-select",
        headers=headers,
        json={
            "operation_id": str(uuid4()),
            "full_name": ADMIN_NAME,
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert selected.status_code == 200, selected.get_json()
    admin_token = selected.get_json()["admin_token"]
    assert client.get("/api/employee").get_json()["selected_kind"] == "admin"

    employee_id = str(uuid4())
    employee_response = client.put(
        "/api/admin/employees",
        headers={"X-Safe-Cells-Admin-Token": admin_token},
        json={
            "operation_id": str(uuid4()),
            "employee_id": employee_id,
            "full_name": EMPLOYEE_NAME,
            "is_active": True,
            "create": True,
        },
    )
    assert employee_response.status_code == 201, employee_response.get_json()

    captured: dict[str, str] = {}

    def fake_generate(*args, employee: str, **kwargs):
        captured["employee"] = employee
        return []

    monkeypatch.setattr(
        "app.routes.document_events.generate_event_documents", fake_generate
    )

    missing_executor = client.post("/api/contracts", json=_contract_payload())
    assert missing_executor.status_code == 409
    assert "исполнителя" in missing_executor.get_json()["message"]

    created = client.post(
        "/api/contracts", json=_contract_payload(employee_id)
    )
    assert created.status_code == 201, created.get_json()
    assert captured["employee"] == EMPLOYEE_NAME

    with open_readonly(
        settings.database_directory / settings.archive_database_name
    ) as archive:
        audit = archive.execute(
            """
            SELECT employee FROM log
            WHERE action='contract.created' AND cell_number='1'
            """
        ).fetchone()
    assert audit["employee"] == ADMIN_NAME

    ordinary = client.post(
        "/api/employee/select",
        headers=headers,
        json={"employee_id": employee_id},
    )
    assert ordinary.status_code == 200
    assert client.get("/api/employee").get_json()["selected_kind"] == "employee"
    assert client.get(
        "/api/admin/settings",
        headers={"X-Safe-Cells-Admin-Token": admin_token},
    ).status_code == 401
