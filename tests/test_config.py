from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import ConfigError, Settings, load_settings


def test_load_settings_reads_valid_json_without_creating_database(tmp_path: Path) -> None:
    database_directory = tmp_path / "configured shared folder"
    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        json.dumps(
            {
                "database_directory": str(database_directory),
                "working_database_name": "working.sqlite3",
                "archive_database_name": "archive.sqlite3",
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(config_path, testing=True)

    assert settings.database_directory == database_directory
    assert settings.working_database_name == "working.sqlite3"
    assert settings.archive_database_name == "archive.sqlite3"
    assert not database_directory.exists()


@pytest.mark.parametrize(
    "working_name",
    ["", "../working.sqlite3", "folder/working.sqlite3", "working.db"],
)
def test_settings_rejects_unsafe_working_database_name(
    tmp_path: Path, working_name: str
) -> None:
    with pytest.raises(ConfigError):
        Settings(
            database_directory=tmp_path,
            working_database_name=working_name,
            testing=True,
        )


def test_settings_rejects_same_database_names(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="разные имена"):
        Settings(
            database_directory=tmp_path,
            working_database_name="same.sqlite3",
            archive_database_name="SAME.sqlite3",
            testing=True,
        )


def test_production_busy_timeout_cannot_be_weakened(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="15000"):
        Settings(database_directory=tmp_path, busy_timeout_ms=50)


def test_test_settings_can_use_short_busy_timeout(tmp_path: Path) -> None:
    settings = Settings(
        database_directory=tmp_path, busy_timeout_ms=50, testing=True
    )
    assert settings.busy_timeout_ms == 50


def test_settings_rejects_non_integer_busy_timeout(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="целым числом"):
        Settings(
            database_directory=tmp_path,
            busy_timeout_ms="15000",  # type: ignore[arg-type]
            testing=True,
        )


def test_missing_config_file_is_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="не найден"):
        load_settings(tmp_path / "missing.json")
