from pathlib import Path

from app import create_app
from app.services.employee import (
    EmployeeProfileError,
    get_employee_full_name,
    save_employee_full_name,
)
import pytest


def test_profile_remembers_exact_windows_account(tmp_path: Path):
    path = tmp_path / "profiles.json"
    assert get_employee_full_name(path, "x") is None
    assert save_employee_full_name(path, "x", "  Иванов   Иван  ") == "Иванов Иван"
    save_employee_full_name(path, "z", "Петров Пётр")
    assert get_employee_full_name(path, "x") == "Иванов Иван"
    assert get_employee_full_name(path, "z") == "Петров Пётр"
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("value", ["", "Иванов", "<Иванов> Иван"])
def test_profile_rejects_incomplete_or_unsafe_name(tmp_path: Path, value: str):
    with pytest.raises(EmployeeProfileError):
        save_employee_full_name(tmp_path / "profiles.json", "x", value)


def test_profile_api_prompts_once_and_remembers(settings, initialized_databases, tmp_path: Path):
    app = create_app(settings)
    profile_path = tmp_path / "profiles.json"
    app.config.update(
        EMPLOYEE_PROVIDER=lambda: "x",
        EMPLOYEE_PROFILE_PATH=profile_path,
    )
    client = app.test_client()
    html = client.get("/").get_data(as_text=True)
    assert 'data-employee-profile-required="true"' in html
    assert client.get("/api/employee/profile").get_json()["profile_required"] is True

    response = client.post(
        "/api/employee/profile",
        headers={"X-Safe-Cells-Token": app.extensions["safe_cells_private_token"]},
        json={"full_name": "Иванов Иван"},
    )
    assert response.status_code == 200
    assert response.get_json()["full_name"] == "Иванов Иван"
    assert client.get("/api/employee/profile").get_json()["profile_required"] is False
    html = client.get("/").get_data(as_text=True)
    assert 'data-employee-profile-required="false"' in html
    assert "Иванов Иван" in html
