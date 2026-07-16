from datetime import datetime
from pathlib import Path
import sqlite3

import pytest

from app.db.connections import open_readonly, open_write
from app.db.migrations import (
    DatabaseMigrationError,
    migrate_v2_to_v3,
    migrate_v3_to_v4,
)


WHEN = datetime.fromisoformat("2026-07-13T12:00:00+06:00")


def _downgrade_fixture_to_v2(settings) -> None:
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


def _downgrade_fixture_to_v3(settings) -> None:
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TABLE main.cell_blocks")
        connection.execute("UPDATE main.schema_version SET version=3")
        connection.execute("UPDATE archive.schema_version SET version=3")
        connection.commit()


def test_explicit_v3_migration_backs_up_and_preserves_contract(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="41", end_date="2026-07-30")
    _downgrade_fixture_to_v2(settings)

    result = migrate_v2_to_v3(settings, occurred_at=WHEN)

    assert result.changed and result.from_version == 2 and result.to_version == 3
    assert result.backup is not None
    assert result.backup.working.is_file() and result.backup.archive.is_file()
    with open_readonly(settings.database_directory / settings.working_database_name) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(contracts)")}
        row = connection.execute("SELECT id_card_issue_date FROM contracts WHERE cell_number='41'").fetchone()
        version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
    assert "id_card_issue_date" in columns and "id_card_expiry_date" not in columns
    assert row[0] == "2017-09-12" and version == 3
    with sqlite3.connect(result.backup.working) as backup:
        backup_columns = {row[1] for row in backup.execute("PRAGMA table_info(contracts)")}
        assert "id_card_expiry_date" in backup_columns
        assert backup.execute("SELECT version FROM schema_version").fetchone()[0] == 2


def test_v3_migration_rolls_back_both_databases_after_partial_failure(
    settings, initialized_databases
):
    _downgrade_fixture_to_v2(settings)
    with pytest.raises(DatabaseMigrationError):
        migrate_v2_to_v3(
            settings,
            occurred_at=WHEN,
            after_working_change=lambda: (_ for _ in ()).throw(RuntimeError("test")),
        )
    with open_write(settings, attach_archive=True) as connection:
        main_columns = {row[1] for row in connection.execute("PRAGMA main.table_info(contracts)")}
        archive_columns = {row[1] for row in connection.execute("PRAGMA archive.table_info(contracts_archive)")}
        versions = (
            connection.execute("SELECT version FROM main.schema_version").fetchone()[0],
            connection.execute("SELECT version FROM archive.schema_version").fetchone()[0],
        )
    assert "id_card_expiry_date" in main_columns
    assert "id_card_expiry_date" in archive_columns
    assert versions == (2, 2)


def test_explicit_v4_migration_backs_up_and_adds_cell_blocks(
    settings, initialized_databases
):
    _downgrade_fixture_to_v3(settings)

    result = migrate_v3_to_v4(settings, occurred_at=WHEN)

    assert result.changed and result.from_version == 3 and result.to_version == 4
    assert result.backup is not None
    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute("SELECT version FROM main.schema_version").fetchone()[0],
            connection.execute("SELECT version FROM archive.schema_version").fetchone()[0],
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA main.table_info(cell_blocks)")
        }
    assert versions == (4, 4)
    assert columns == {
        "cell_number",
        "block_kind",
        "source_contract_id",
        "created_at",
        "created_by",
    }
    with sqlite3.connect(result.backup.working) as backup:
        assert backup.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cell_blocks'"
        ).fetchone() is None


def test_v4_migration_rolls_back_pair_after_partial_failure(
    settings, initialized_databases
):
    _downgrade_fixture_to_v3(settings)

    with pytest.raises(DatabaseMigrationError):
        migrate_v3_to_v4(
            settings,
            occurred_at=WHEN,
            after_table_create=lambda: (_ for _ in ()).throw(RuntimeError("test")),
        )

    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute("SELECT version FROM main.schema_version").fetchone()[0],
            connection.execute("SELECT version FROM archive.schema_version").fetchone()[0],
        )
        table = connection.execute(
            "SELECT 1 FROM main.sqlite_master WHERE type='table' AND name='cell_blocks'"
        ).fetchone()
    assert versions == (3, 3)
    assert table is None
