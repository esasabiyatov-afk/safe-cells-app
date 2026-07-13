from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from app import create_app
from app.config import Settings
from app.db.schema import initialize_databases


def _ready_app(settings: Settings, cells_csv_path: Path):
    initialize_databases(settings, cells_csv_path=cells_csv_path)
    app = create_app(settings)
    app.config["TODAY_PROVIDER"] = lambda: date(2026, 7, 1)
    app.config["EMPLOYEE_PROVIDER"] = lambda: "test-user"
    return app


def test_main_page_uses_only_local_assets_and_security_headers(
    settings: Settings, cells_csv_path: Path
) -> None:
    app = _ready_app(settings, cells_csv_path)

    response = app.test_client().get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "test-user" not in html
    assert 'id="employeeSelect"' in html
    assert 'id="adminOpen"' in html
    assert 'id="refreshButton"' not in html
    assert 'id="employeeDialog"' in html
    assert 'id="operationResultDialog"' in html
    assert 'id="operationDocumentList"' in html
    assert "http://" not in html
    assert "https://" not in html
    assert 'src="/static/js/main.js"' in html
    assert 'href="/static/css/main.css"' in html
    assert 'data-rental-url="/api/rental/calculate"' in html
    assert 'data-contract-url="/api/contracts"' in html
    assert 'data-private-url="/api/contracts/private"' in html
    assert 'data-client-name-url="/api/contracts/client-name"' in html
    assert 'data-renewal-quote-url="/api/renewals/calculate"' in html
    assert 'data-renewal-url="/api/renewals"' in html
    assert 'data-closure-quote-url="/api/closures/calculate"' in html
    assert 'data-closure-url="/api/closures"' in html
    assert 'data-private-token="' in html
    assert 'id="rentalContinue"' in html
    assert (
        'class="primary-button" id="rentalContinue" type="button" disabled' in html
    )
    assert 'name="currency"' not in html
    assert "Сумма аренды" in html
    assert '<section class="deposit-panel rental-deposit" aria-label="Залог">' in html
    assert "<span>Залог</span>" in html
    assert 'id="renewAction" type="button">Продлить' in html
    assert 'id="renewalDialog"' in html
    assert 'id="renewalSubmit" type="submit" disabled' in html
    assert 'id="renewalPenaltyPanel" aria-label="Расчёт штрафа" hidden' in html
    assert 'id="closeAction" type="button">Закрыть договор' in html
    assert 'id="closureDialog"' in html
    assert 'id="closureSubmit" type="submit" disabled' in html
    assert "Оплаченная аренда за неиспользованные дни не возвращается" in html
    assert "Потеря ключа" in html
    assert "Штрафные дни" in html
    assert 'id="adminPenaltyRows"' in html
    assert 'id="contractForm"' in html
    assert 'name="client_full_name"' in html
    assert 'name="id_card_number"' in html
    assert 'name="account_number"' in html
    assert 'id="privateDetails" hidden' in html
    assert 'id="privateCreatedBy"' in html
    assert 'id="historyControls" hidden' in html
    assert 'id="renewalHistory" aria-label="История продлений" hidden' in html
    assert "Показать данные" in html
    assert "ЗАО АКБ «Толубай»" in html
    assert ">Депозитарий<" in html
    assert "Локальная банковская система" not in html
    assert "Оперативный контроль аренды" not in html
    assert "Хранилище" not in html
    assert "Все ячейки" not in html
    assert '<dt>ФИО клиента</dt>' not in html
    assert "Повторно сформировать документ" in html
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_main_page_does_not_read_or_embed_employee_identity(
    settings: Settings, cells_csv_path: Path
) -> None:
    app = _ready_app(settings, cells_csv_path)
    app.config["EMPLOYEE_PROVIDER"] = lambda: (_ for _ in ()).throw(
        AssertionError("main page must not resolve employee identity")
    )

    html = app.test_client().get("/").get_data(as_text=True)

    assert 'data-employee-directory-url="/api/employee"' in html
    assert 'data-employee-select-url="/api/employee/select"' in html


def test_cells_api_returns_126_safe_rows(
    settings: Settings, cells_csv_path: Path
) -> None:
    app = _ready_app(settings, cells_csv_path)

    response = app.test_client().get("/api/cells")
    payload = response.get_json()

    assert response.status_code == 200
    assert len(payload["cells"]) == 126
    assert payload["counts"] == {
        "free": 126,
        "normal": 0,
        "expiring": 0,
        "overdue": 0,
    }
    assert "client_full_name" not in payload["cells"][0]
    assert "account_number" not in payload["cells"][0]


def test_private_search_api_uses_post_and_returns_no_personal_fields(
    settings: Settings,
    cells_csv_path: Path,
    insert_test_contract: Callable[..., None],
) -> None:
    app = create_app(settings)
    app.config["TODAY_PROVIDER"] = lambda: date(2026, 7, 1)
    insert_test_contract(
        cell_number="1",
        start_date="2026-07-01",
        end_date="2026-07-09",
        client_name="Секретный Тестовый Клиент",
        account_number="PRIVATE-TEST-ACCOUNT",
    )

    response = app.test_client().post(
        "/api/cells/search", json={"query": "секретный"}
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload == {"matched_numbers": ["1"]}
    assert "Секретный" not in response.get_data(as_text=True)
    assert "PRIVATE-TEST-ACCOUNT" not in response.get_data(as_text=True)
    assert app.test_client().get("/api/cells/search").status_code == 405


def test_search_rejects_invalid_and_oversized_payload(
    settings: Settings, cells_csv_path: Path
) -> None:
    app = _ready_app(settings, cells_csv_path)
    client = app.test_client()

    assert client.post("/api/cells/search", json={}).status_code == 400
    assert client.post(
        "/api/cells/search", json={"query": "x" * 101}
    ).status_code == 400


def test_missing_database_shows_safe_api_error_without_creation(tmp_path: Path) -> None:
    missing = tmp_path / "offline network"
    settings = Settings(database_directory=missing, testing=True)
    app = create_app(settings)

    response = app.test_client().get("/api/cells")

    assert response.status_code == 503
    assert response.get_json() == {
        "message": "Не удалось получить данные с сетевого диска. Проверьте подключение к сети"
    }
    assert not missing.exists()


def test_frontend_assets_are_available_and_contain_refresh_logic(
    settings: Settings, cells_csv_path: Path
) -> None:
    app = _ready_app(settings, cells_csv_path)
    client = app.test_client()

    css = client.get("/static/css/main.css")
    javascript = client.get("/static/js/main.js")
    admin_javascript = client.get("/static/js/admin.js")
    try:
        assert css.status_code == 200
        assert javascript.status_code == 200
        assert admin_javascript.status_code == 200
        stylesheet = css.get_data(as_text=True)
        script = javascript.get_data(as_text=True)
        admin_script = admin_javascript.get_data(as_text=True)
        assert "--free-border:" in stylesheet
        assert "--normal-border:" in stylesheet
        assert "--expiring-border:" in stylesheet
        assert "--overdue-border:" in stylesheet
        assert "border: 2px solid var(--cell-accent)" in stylesheet
        assert "inset 0 5px 0 var(--cell-accent)" in stylesheet
        assert "font-size: 11.5px" in stylesheet
        assert ".legend-dot.free { background: #26833a; }" in stylesheet
        assert ".legend-dot.normal { background: #2476a8; }" in stylesheet
        assert ".legend-dot.expiring { background: #e5a900; }" in stylesheet
        assert ".legend-dot.overdue { background: #c83b2d; }" in stylesheet
        assert "grid-template-columns: repeat(2, 1fr);" in stylesheet
        assert "15_000" in script
        assert "setInterval" in script
        assert "innerHTML" not in script
        assert "clearDisplayedData" in script
        assert "requestRentalQuote" in script
        assert "syncDaysFromDates" in script
        assert "syncEndFromDays" in script
        assert "createOperationId" in script
        assert "submitContract" in script
        assert "activeOperationId" in script
        assert "togglePrivateDetails" in script
        assert '"X-Safe-Cells-Token"' in script
        assert "hidePrivateDetails" in script
        assert "clearPrivateValues" in script
        assert "renderRenewals" in script
        assert "privateCreatedBy" in script
        assert "renewal.created_by" in script
        assert "renewalStartDateValue" in script
        assert "dayAfterOldEnd > renewalDate" in script
        assert "elements.renewalPenaltyPanel.hidden = true" in script
        assert "showOperationResult" in script
        assert "operationDocumentList" in script
        assert "Операция сохранена, но документы не сформированы" in script
        assert "refreshButton" not in script
        assert "@media (max-width: 1600px)" in stylesheet
        assert ".rental-deposit" in stylesheet
        assert ".dialog-actions" in stylesheet
        assert "penaltyTariffIndex" in admin_script
        assert "row.period_from_days === 1 && row.period_to_days === 30" in admin_script
        assert "penaltyInput.addEventListener" in admin_script
    finally:
        css.close()
        javascript.close()
        admin_javascript.close()
