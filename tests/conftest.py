from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db.schema import InitializationResult, initialize_databases


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cells_csv_path() -> Path:
    return PROJECT_ROOT / "data" / "cell_heights.csv"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    database_directory = tmp_path / "shared test data"
    database_directory.mkdir()
    return Settings(database_directory=database_directory, testing=True)


@pytest.fixture
def initialized_databases(
    settings: Settings, cells_csv_path: Path
) -> InitializationResult:
    return initialize_databases(settings, cells_csv_path=cells_csv_path)
