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
    assert "test-user" in html
    assert "http://" not in html
    assert "https://" not in html
    assert 'src="/static/js/main.js"' in html
    assert 'href="/static/css/main.css"' in html
    assert 'data-rental-url="/api/rental/calculate"' in html
    assert 'data-contract-url="/api/contracts"' in html
    assert 'data-private-url="/api/contracts/private"' in html
    assert 'data-renewal-quote-url="/api/renewals/calculate"' in html
    assert 'data-renewal-url="/api/renewals"' in html
    assert 'data-private-token="' in html
    assert 'id="rentalContinue"' in html
    assert (
        'class="primary-button" id="rentalContinue" type="button" disabled' in html
    )
    assert 'name="currency"' not in html
    assert "Сумма аренды" in html
    assert "Залог отдельно" in html
    assert "Не входит в сумму аренды" in html
    assert 'id="renewAction" type="button">Продлить' in html
    assert 'id="renewalDialog"' in html
    assert 'id="renewalSubmit" type="submit" disabled' in html
    assert "Штрафные дни" in html
    assert 'id="contractForm"' in html
    assert 'name="client_full_name"' in html
    assert 'name="id_card_number"' in html
    assert 'name="account_number"' in html
    assert 'id="privateDetails" hidden' in html
    assert 'id="historyControls" hidden' in html
    assert 'id="renewalHistory" aria-label="История продлений" hidden' in html
    assert "Показать данные" in html
    assert "Повторно сформировать документ" in html
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_employee_name_is_escaped(
    settings: Settings, cells_csv_path: Path
) -> None:
    app = _ready_app(settings, cells_csv_path)
    app.config["EMPLOYEE_PROVIDER"] = lambda: "<script>test</script>"

    html = app.test_client().get("/").get_data(as_text=True)

    assert "<script>test</script>" not in html
    assert "&lt;script&gt;test&lt;/script&gt;" in html


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
    try:
        assert css.status_code == 200
        assert javascript.status_code == 200
        stylesheet = css.get_data(as_text=True)
        script = javascript.get_data(as_text=True)
        assert "--free-border:" in stylesheet
        assert "--normal-border:" in stylesheet
        assert "--expiring-border:" in stylesheet
        assert "--overdue-border:" in stylesheet
        assert "border: 2px solid var(--cell-accent)" in stylesheet
        assert "inset 0 5px 0 var(--cell-accent)" in stylesheet
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
    finally:
        css.close()
        javascript.close()
