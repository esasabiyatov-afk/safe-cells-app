from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli import main
from app.db.connections import DatabasePaths
from app.config import Settings
from app.db.connections import open_write


def test_init_cli_requires_exact_confirmation(
    tmp_path: Path, cells_csv_path: Path
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"database_directory": str(tmp_path)}), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "init-db",
                "--config",
                str(config_path),
                "--cells-csv",
                str(cells_csv_path),
                "--confirm",
                "WRONG",
            ]
        )

    assert exc_info.value.code == 2
    paths = DatabasePaths.from_settings(
        Settings(database_directory=tmp_path, testing=True)
    )
    assert not paths.working.exists()
    assert not paths.archive.exists()


def test_init_cli_creates_pair_only_after_confirmation(
    tmp_path: Path, cells_csv_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"database_directory": str(tmp_path)}), encoding="utf-8"
    )

    exit_code = main(
        [
            "init-db",
            "--config",
            str(config_path),
            "--cells-csv",
            str(cells_csv_path),
            "--confirm",
            "INITIALIZE",
        ]
    )

    assert exit_code == 0
    assert "Ячеек: 126" in capsys.readouterr().out
    paths = DatabasePaths.from_settings(
        Settings(database_directory=tmp_path, testing=True)
    )
    assert paths.working.is_file()
    assert paths.archive.is_file()


def test_migration_cli_requires_confirmation_and_updates_both_versions(
    settings: Settings, initialized_databases, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"database_directory": str(settings.database_directory)}),
        encoding="utf-8",
    )
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "ALTER TABLE main.contracts RENAME COLUMN id_card_issue_date TO id_card_expiry_date"
        )
        connection.execute(
            "ALTER TABLE archive.contracts_archive RENAME COLUMN id_card_issue_date TO id_card_expiry_date"
        )
        connection.execute("UPDATE main.schema_version SET version=2")
        connection.execute("UPDATE archive.schema_version SET version=2")
        connection.commit()
    with pytest.raises(SystemExit) as exc_info:
        main(["migrate-v3", "--config", str(config_path), "--confirm", "WRONG"])
    assert exc_info.value.code == 2

    assert main([
        "migrate-v3", "--config", str(config_path), "--confirm", "MIGRATE-TO-3"
    ]) == 0
    assert "Версия схемы: 3" in capsys.readouterr().out


def test_v4_migration_cli_requires_confirmation_and_updates_both_versions(
    settings: Settings, initialized_databases, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config-v4.json"
    config_path.write_text(
        json.dumps({"database_directory": str(settings.database_directory)}),
        encoding="utf-8",
    )
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TABLE main.cell_blocks")
        connection.execute("UPDATE main.schema_version SET version=3")
        connection.execute("UPDATE archive.schema_version SET version=3")
        connection.commit()

    with pytest.raises(SystemExit) as exc_info:
        main(["migrate-v4", "--config", str(config_path), "--confirm", "WRONG"])
    assert exc_info.value.code == 2
    assert main([
        "migrate-v4", "--config", str(config_path), "--confirm", "MIGRATE-TO-4"
    ]) == 0
    assert "Версия схемы: 4" in capsys.readouterr().out
