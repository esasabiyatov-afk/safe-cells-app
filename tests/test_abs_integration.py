from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from app import create_app
from app.config import Settings
from app.db.schema import initialize_databases
from app.db.connections import open_readonly, open_write
from app.services import abs_integration
from app.services.abs_integration import (
    AbsSessionManager,
    AbsSessionRequiredError,
    AbsCustomerData,
    refresh_linked_contracts,
)


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class FakeSession:
    def __init__(self) -> None:
        self.verify = True
        self.headers: dict[str, str] = {}
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[str] = []
        self.closed = False

    def get(self, url, **_kwargs):
        self.gets.append(url)
        if "SignIn" in url:
            return FakeResponse(
                '<input name="__RequestVerificationToken" value="csrf-test">'
            )
        if "Details" in url:
            return FakeResponse(
                """
                <script>
                {"ProgramID":15,"Name":"Тестовый депозит"}
                var data = {"Deposits":[{"MainAccountNo":"TEST-ACC-777",
                "ProgramID":15,"CurrencyID":417,"DepositAccountStatusID":1,
                "MainBalance":1250.5}]};
                </script>
                """
            )
        return FakeResponse(
            """
            <input name="GeneralInfoModel.CustomerId" value="777">
            <input name="GeneralInfoModel.Surname" value="Аманова">
            <input name="GeneralInfoModel.CustomerName" value="Залия">
            <input name="GeneralInfoModel.DocumentSeries" value="ID ">
            <input name="GeneralInfoModel.DocumentNo" value="123 456">
            <input name="GeneralInfoModel.IssueDate" value="15.05.2019">
            <input name="GeneralInfoModel.IssueAuthority" value="Тестовый орган">
            <input name="AdditionalInfoModel.ContactPhone1" value="+996 555 000 111">
            <input name="AdditionalInfoModel.WhatsAppPhone" value="+996 700 000 222">
            """
        )

    def post(self, url, data=None, headers=None, **_kwargs):
        self.posts.append((url, dict(data or {})))
        if "SignIn" in url:
            return FakeResponse("ok")
        return FakeResponse(
            """
            <table><tbody>
              <tr><td><a href="/Customers/Edit?customerID=777">Открыть</a></td>
                  <td>Аманова Залия</td><td>01.01.1990</td></tr>
              <tr><td><a href="/Customers/Edit?customerID=778">Открыть</a></td>
                  <td>Аманова Залия Н.</td><td>02.02.1991</td></tr>
            </tbody></table>
            """
        )

    def close(self):
        self.closed = True


def test_abs_login_search_and_customer_mapping(monkeypatch) -> None:
    fake_session = FakeSession()
    monkeypatch.setattr(abs_integration.requests, "Session", lambda: fake_session)
    manager = AbsSessionManager()

    manager.login("worker", "secret", "Тестовый Сотрудник")
    assert fake_session.verify is False
    assert fake_session.posts[0][1] == {
        "UserName": "worker",
        "Password": "secret",
        "__RequestVerificationToken": "csrf-test",
    }

    results = manager.search("Аманова Залия", "Тестовый Сотрудник")
    assert [result.customer_id for result in results] == ["777", "778"]
    search_payload = fake_session.posts[1][1]
    assert search_payload["SearchSurname"] == "Аманова"
    assert search_payload["SearchCustomerName"] == "Залия"

    customer = manager.customer("777", "Тестовый Сотрудник")
    assert customer.client_full_name == "Аманова Залия"
    assert customer.client_phone == "+996 555 000 111"
    assert customer.client_whatsapp_phone == "+996 700 000 222"
    assert customer.id_card_number == "ID123456"
    assert customer.id_card_issue_date == "2019-05-15"
    assert customer.account_number == ""
    assert len(customer.accounts) == 1
    assert customer.accounts[0].account_no == "TEST-ACC-777"
    assert customer.accounts[0].product == "Тестовый депозит"
    assert customer.accounts[0].currency == "KGS"


def test_abs_search_supports_customer_id_and_kyrgyz_surname(monkeypatch) -> None:
    fake_session = FakeSession()
    monkeypatch.setattr(abs_integration.requests, "Session", lambda: fake_session)
    manager = AbsSessionManager()
    manager.login("worker", "secret", "employee")

    manager.search("12345", "employee")
    assert fake_session.posts[-1][1]["SearchCustomerID"] == "12345"

    manager.search("Эсенбек уулу Асан", "employee")
    payload = fake_session.posts[-1][1]
    assert payload["SearchSurname"] == "Эсенбек уулу"
    assert payload["SearchCustomerName"] == "Асан"
    assert payload["SearchOtchestvo"] == ""


def test_abs_session_is_bound_to_current_employee() -> None:
    manager = AbsSessionManager()
    with pytest.raises(AbsSessionRequiredError):
        manager.search("123", "Другой Сотрудник")


def test_abs_session_expires_after_configured_minutes(monkeypatch) -> None:
    fake_session = FakeSession()
    monkeypatch.setattr(abs_integration.requests, "Session", lambda: fake_session)
    current = [100.0]
    manager = AbsSessionManager(clock=lambda: current[0])
    manager.login("worker", "secret", "employee", lifetime_minutes=60)

    current[0] = 3_699.0
    assert manager.is_authenticated("employee") is True
    current[0] = 3_700.0
    with pytest.raises(AbsSessionRequiredError, match="заново"):
        manager.search("123", "employee")
    assert manager.is_authenticated("employee") is False
    assert fake_session.closed is True


def test_abs_login_refreshes_linked_contract_without_replacing_account(
    settings, initialized_databases, insert_test_contract
) -> None:
    insert_test_contract(cell_number="1", end_date="2026-08-01")
    with open_write(settings) as connection:
        connection.execute(
            "UPDATE contracts SET abs_customer_id='777', account_number='EXCEL-ACCOUNT', "
            "client_whatsapp_phone='+996 700 999 999' "
            "WHERE cell_number='1'"
        )
        connection.commit()

    class SyncManager:
        def customer(self, customer_id, employee_name):
            assert (customer_id, employee_name) == ("777", "Сотрудник Теста")
            return AbsCustomerData(
                abs_customer_id="777",
                client_full_name="Тестовый Клиент Обновлённый",
                client_phone="+996 555 000 111",
                client_whatsapp_phone="+996 700 000 222",
                account_number="ABS-ACCOUNT-NOT-USED",
                id_card_number="TEST-ID-2",
                id_card_issuer="Тестовый орган 2",
                id_card_issue_date="2020-01-02",
            )

    result = refresh_linked_contracts(
        settings,
        manager=SyncManager(),
        employee_name="Сотрудник Теста",
        occurred_at=datetime.fromisoformat("2026-07-31T12:00:00+06:00"),
    )

    assert result.updated_count == 1
    with open_readonly(
        settings.database_directory / settings.working_database_name
    ) as connection:
        contract = connection.execute(
            "SELECT * FROM contracts WHERE cell_number='1'"
        ).fetchone()
    assert contract["client_full_name"] == "Тестовый Клиент Обновлённый"
    assert contract["id_card_number"] == "TEST-ID-2"
    assert contract["client_phone"] == "+996 555 000 111"
    assert contract["client_whatsapp_phone"] == "+996 700 000 222"
    assert contract["account_number"] == "EXCEL-ACCOUNT"
    assert result.linked_count == 1


class RouteManager:
    def __init__(self) -> None:
        self.login_values = None

    def is_authenticated(self, employee_name):
        return employee_name == "test-user"

    def login(self, login, password, employee_name):
        self.login_values = (login, password, employee_name)

    def search(self, query, employee_name):
        return [
            abs_integration.AbsCustomerSearchResult(
                customer_id="777", summary=f"{query} / {employee_name}"
            )
        ]

    def customer(self, customer_id, _employee_name):
        return abs_integration.AbsCustomerData(
            abs_customer_id=customer_id,
            client_full_name="Тестовый Клиент",
            client_phone="+996000000000",
            account_number="TEST-ACCOUNT",
            id_card_number="TEST-ID",
            id_card_issuer="Тестовый орган",
            id_card_issue_date="2026-01-01",
        )


def _ready_app(settings: Settings, cells_csv_path: Path):
    initialize_databases(settings, cells_csv_path=cells_csv_path)
    app = create_app(settings)
    app.config["TODAY_PROVIDER"] = lambda: date(2026, 7, 1)
    app.config["EMPLOYEE_PROVIDER"] = lambda: "test-user"
    app.extensions["safe_cells_abs_session"] = RouteManager()
    return app


def test_abs_routes_require_private_token(
    settings: Settings, cells_csv_path: Path
) -> None:
    app = _ready_app(settings, cells_csv_path)
    response = app.test_client().get("/api/abs/status")
    assert response.status_code == 403


def test_abs_routes_login_search_and_load_customer(
    settings: Settings, cells_csv_path: Path
) -> None:
    app = _ready_app(settings, cells_csv_path)
    token = app.extensions["safe_cells_private_token"]
    headers = {"X-Safe-Cells-Token": token}
    client = app.test_client()

    login = client.post(
        "/api/abs/login",
        json={"login": "worker", "password": "secret"},
        headers=headers,
    )
    assert login.status_code == 200
    assert app.extensions["safe_cells_abs_session"].login_values == (
        "worker",
        "secret",
        "test-user",
    )

    search = client.post(
        "/api/abs/search", json={"query": "Тест"}, headers=headers
    )
    assert search.status_code == 200
    assert search.get_json()["results"][0]["customer_id"] == "777"

    customer = client.post(
        "/api/abs/customer", json={"customer_id": "777"}, headers=headers
    )
    assert customer.status_code == 200
    assert customer.get_json()["account_number"] == "TEST-ACCOUNT"

    refresh = client.post("/api/abs/refresh-linked", json={}, headers=headers)
    assert refresh.status_code == 200
    assert refresh.get_json() == {
        "linked_count": 0,
        "skipped_count": 0,
        "updated_count": 0,
        "warning": None,
    }
