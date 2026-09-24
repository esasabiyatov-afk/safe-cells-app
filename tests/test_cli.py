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


def test_v5_migration_cli_requires_confirmation_and_updates_both_versions(
    settings: Settings, initialized_databases, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config-v5.json"
    config_path.write_text(
        json.dumps({"database_directory": str(settings.database_directory)}),
        encoding="utf-8",
    )
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TRIGGER main.prevent_contract_on_blocked_cell")
        connection.execute("DROP TRIGGER main.prevent_block_on_contracted_cell")
        connection.execute("DROP TABLE main.cell_blocks")
        connection.execute(
            """
            CREATE TABLE main.cell_blocks(
                cell_number TEXT PRIMARY KEY REFERENCES cells(number),
                block_kind TEXT NOT NULL CHECK(block_kind IN ('lost_key', 'bank')),
                source_contract_id TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TRIGGER main.prevent_contract_on_blocked_cell
            BEFORE INSERT ON contracts
            WHEN EXISTS(SELECT 1 FROM cell_blocks WHERE cell_number=NEW.cell_number)
            BEGIN SELECT RAISE(ABORT, 'cell is blocked'); END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER main.prevent_block_on_contracted_cell
            BEFORE INSERT ON cell_blocks
            WHEN EXISTS(SELECT 1 FROM contracts WHERE cell_number=NEW.cell_number)
            BEGIN SELECT RAISE(ABORT, 'cell has active contract'); END
            """
        )
        connection.execute("UPDATE main.schema_version SET version=4")
        connection.execute("UPDATE archive.schema_version SET version=4")
        connection.commit()

    with pytest.raises(SystemExit) as exc_info:
        main(["migrate-v5", "--config", str(config_path), "--confirm", "WRONG"])
    assert exc_info.value.code == 2
    assert main([
        "migrate-v5", "--config", str(config_path), "--confirm", "MIGRATE-TO-5"
    ]) == 0
    assert "Версия схемы: 5" in capsys.readouterr().out


def test_v6_migration_cli_requires_confirmation_and_updates_both_versions(
    settings: Settings, initialized_databases, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config-v6.json"
    config_path.write_text(
        json.dumps({"database_directory": str(settings.database_directory)}),
        encoding="utf-8",
    )
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for database, table in (
            ("main", "contracts"),
            ("archive", "contracts_archive"),
        ):
            connection.execute(
                f"ALTER TABLE {database}.{table} DROP COLUMN reminder_count"
            )
            connection.execute(
                f"ALTER TABLE {database}.{table} DROP COLUMN last_reminded_at"
            )
            connection.execute(
                f"ALTER TABLE {database}.{table} DROP COLUMN client_phone"
            )
        connection.execute("UPDATE main.schema_version SET version=5")
        connection.execute("UPDATE archive.schema_version SET version=5")
        connection.commit()

    with pytest.raises(SystemExit) as exc_info:
        main(["migrate-v6", "--config", str(config_path), "--confirm", "WRONG"])
    assert exc_info.value.code == 2
    assert main([
        "migrate-v6", "--config", str(config_path), "--confirm", "MIGRATE-TO-6"
    ]) == 0
    assert "Версия схемы: 6" in capsys.readouterr().out


def test_v7_migration_cli_requires_confirmation_and_updates_both_versions(
    settings: Settings, initialized_databases, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config-v7.json"
    config_path.write_text(
        json.dumps({"database_directory": str(settings.database_directory)}),
        encoding="utf-8",
    )
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TRIGGER main.prevent_contract_on_inactive_cell")
        connection.execute("DROP TRIGGER main.prevent_block_on_inactive_cell")
        connection.execute("DROP TRIGGER main.prevent_retire_occupied_cell")
        connection.execute(
            """
            CREATE TABLE main.cells_v6(
                number TEXT PRIMARY KEY CHECK(length(trim(number)) > 0),
                height_mm INTEGER NOT NULL CHECK(height_mm > 0),
                width_mm INTEGER CHECK(width_mm IS NULL OR width_mm > 0),
                depth_mm INTEGER CHECK(depth_mm IS NULL OR depth_mm > 0)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO main.cells_v6(number, height_mm, width_mm, depth_mm)
            SELECT number, height_mm, width_mm, depth_mm FROM main.cells
            """
        )
        connection.execute("DROP TABLE main.cells")
        connection.execute("ALTER TABLE main.cells_v6 RENAME TO cells")
        connection.execute("UPDATE main.schema_version SET version=6")
        connection.execute("UPDATE archive.schema_version SET version=6")
        connection.commit()
        connection.execute("PRAGMA foreign_keys=ON")

    with pytest.raises(SystemExit) as exc_info:
        main(["migrate-v7", "--config", str(config_path), "--confirm", "WRONG"])
    assert exc_info.value.code == 2
    assert main([
        "migrate-v7", "--config", str(config_path), "--confirm", "MIGRATE-TO-7"
    ]) == 0
    assert "Версия схемы: 7" in capsys.readouterr().out


def test_v9_migration_cli_requires_confirmation_and_updates_both_versions(
    settings: Settings, initialized_databases, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config-v9.json"
    config_path.write_text(
        json.dumps({"database_directory": str(settings.database_directory)}),
        encoding="utf-8",
    )
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TABLE archive.operation_cancellations")
        connection.execute("UPDATE main.schema_version SET version=8")
        connection.execute("UPDATE archive.schema_version SET version=8")
        connection.commit()

    with pytest.raises(SystemExit) as exc_info:
        main(["migrate-v9", "--config", str(config_path), "--confirm", "WRONG"])
    assert exc_info.value.code == 2
    assert main([
        "migrate-v9", "--config", str(config_path), "--confirm", "MIGRATE-TO-9"
    ]) == 0
    assert "Версия схемы: 9" in capsys.readouterr().out


def test_v10_migration_cli_requires_confirmation_and_updates_both_versions(
    settings: Settings, initialized_databases, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config-v10.json"
    config_path.write_text(
        json.dumps({"database_directory": str(settings.database_directory)}),
        encoding="utf-8",
    )
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE main.schema_version SET version=9"
        )
        connection.execute(
            "UPDATE archive.schema_version SET version=9"
        )
        connection.commit()

    with pytest.raises(SystemExit) as exc_info:
        main(["migrate-v10", "--config", str(config_path), "--confirm", "WRONG"])
    assert exc_info.value.code == 2
    assert main([
        "migrate-v10", "--config", str(config_path), "--confirm", "MIGRATE-TO-10"
    ]) == 0
    assert "Версия схемы: 10" in capsys.readouterr().out
