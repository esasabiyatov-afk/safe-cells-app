from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app import create_app
from app.db.connections import open_readonly, open_write
from app.services.admin_settings import (
    AdminConflictError,
    AdminValidationError,
    update_admin_employee,
)
from app.services.employee import (
    EMPLOYEES_CONFIG_KEY,
    EmployeeProfileError,
    EmployeeRecord,
    encode_employee_config,
    validate_employee_full_name,
)


OCCURRED_AT = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)


def _store_employees(settings, employees: list[EmployeeRecord]) -> None:
    with open_write(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE config SET value = ? WHERE key = ?",
            (encode_employee_config(employees), EMPLOYEES_CONFIG_KEY),
        )
        connection.commit()


@pytest.mark.parametrize("value", ["", "Иванов", "<Иванов> Иван"])
def test_employee_name_rejects_incomplete_or_unsafe_value(value: str):
    with pytest.raises(EmployeeProfileError):
        validate_employee_full_name(value)


def test_employee_directory_selection_is_local_to_each_app_process(
    settings, initialized_databases
):
    first = EmployeeRecord(str(uuid4()), "Тестов Иван", True)
    second = EmployeeRecord(str(uuid4()), "Примерова Анна", True)
    _store_employees(settings, [first, second])
    first_app = create_app(settings)
    second_app = create_app(settings)
    first_client = first_app.test_client()
    second_client = second_app.test_client()

    assert first_client.get("/api/employee").get_json()["selection_required"] is True
    assert second_client.get("/api/employee").get_json()["selection_required"] is True
    assert first_client.post(
        "/api/employee/select", json={"employee_id": first.employee_id}
    ).status_code == 403
    response = first_client.post(
        "/api/employee/select",
        headers={"X-Safe-Cells-Token": first_app.extensions["safe_cells_private_token"]},
        json={"employee_id": first.employee_id},
    )

    assert response.status_code == 200
    assert response.get_json()["full_name"] == "Тестов Иван"
    assert first_client.get("/api/employee").get_json()["selected_employee_id"] == first.employee_id
    assert second_client.get("/api/employee").get_json()["selection_required"] is True


def test_disabled_selected_employee_must_be_chosen_again(settings, initialized_databases):
    first = EmployeeRecord(str(uuid4()), "Тестов Иван", True)
    second = EmployeeRecord(str(uuid4()), "Примерова Анна", True)
    _store_employees(settings, [first, second])
    app = create_app(settings)
    client = app.test_client()
    token = app.extensions["safe_cells_private_token"]
    assert client.post(
        "/api/employee/select",
        headers={"X-Safe-Cells-Token": token},
        json={"employee_id": first.employee_id},
    ).status_code == 200

    _store_employees(settings, [EmployeeRecord(first.employee_id, first.full_name, False), second])
    payload = client.get("/api/employee").get_json()

    assert payload["selection_required"] is True
    assert [item["employee_id"] for item in payload["employees"]] == [second.employee_id]


def test_admin_employee_write_validates_audits_and_is_idempotent(
    settings, initialized_databases
):
    employee_id = str(uuid4())
    operation_id = str(uuid4())
    payload = {
        "operation_id": operation_id,
        "employee_id": employee_id,
        "full_name": "Тестов Иван",
        "is_active": True,
        "create": True,
    }

    result, saved = update_admin_employee(
        settings, payload=payload, employee="Первичная Настройка", occurred_at=OCCURRED_AT
    )
    repeated, repeated_employee = update_admin_employee(
        settings, payload=payload, employee="Первичная Настройка", occurred_at=OCCURRED_AT
    )

    assert result.repeated is False
    assert repeated.repeated is True
    assert saved == repeated_employee == EmployeeRecord(employee_id, "Тестов Иван", True)
    with open_readonly(settings.database_directory / settings.archive_database_name) as connection:
        audit = connection.execute(
            "SELECT action, employee FROM log WHERE operation_id = ?", (operation_id,)
        ).fetchall()
    assert [tuple(row) for row in audit] == [("admin.employee.created", "Первичная Настройка")]

    duplicate = dict(payload, operation_id=str(uuid4()), employee_id=str(uuid4()))
    with pytest.raises(AdminConflictError):
        update_admin_employee(
            settings, payload=duplicate, employee="Тестов Иван", occurred_at=OCCURRED_AT
        )

    disable = dict(payload, operation_id=str(uuid4()), is_active=False, create=False)
    with pytest.raises(AdminValidationError, match="активный"):
        update_admin_employee(
            settings, payload=disable, employee="Тестов Иван", occurred_at=OCCURRED_AT
        )
