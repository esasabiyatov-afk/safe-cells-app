from __future__ import annotations

from pathlib import Path

from app import create_app
from app.config import Settings
from app.db.schema import initialize_databases


def test_health_reports_schema_versions(
    settings: Settings, cells_csv_path: Path
) -> None:
    initialize_databases(settings, cells_csv_path=cells_csv_path)
    app = create_app(settings)

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "schema_versions": {"archive": 3, "working": 3},
    }


def test_app_creation_and_health_do_not_create_missing_database(tmp_path: Path) -> None:
    missing = tmp_path / "missing network path"
    settings = Settings(database_directory=missing, testing=True)
    app = create_app(settings)

    response = app.test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "unavailable",
        "message": "Не удалось получить данные с сетевого диска. Проверьте подключение к сети",
    }
    assert not missing.exists()
