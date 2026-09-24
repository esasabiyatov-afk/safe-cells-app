from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3

import pytest

from app.db.connections import open_readonly, open_write
from app.db.migrations import (
    DatabaseMigrationError,
    migrate_v2_to_v3,
    migrate_v3_to_v4,
    migrate_v4_to_v5,
    migrate_v5_to_v6,
    migrate_v6_to_v7,
    migrate_v7_to_v8,
    migrate_v8_to_v9,
    migrate_v9_to_v10,
    migrate_v10_to_v11,
    migrate_v11_to_v12,
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


def _downgrade_fixture_to_v4(settings) -> None:
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
                created_by TEXT NOT NULL,
                CHECK(
                    (block_kind = 'lost_key' AND source_contract_id IS NOT NULL)
                    OR (block_kind = 'bank' AND source_contract_id IS NULL)
                )
            )
            """
        )
        connection.execute(
            """
            INSERT INTO main.cell_blocks(
                cell_number, block_kind, source_contract_id, created_at, created_by
            ) VALUES('1', 'bank', NULL, ?, 'Тестовый Сотрудник')
            """,
            (WHEN.isoformat(timespec="seconds"),),
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


def _downgrade_fixture_to_v5(settings) -> None:
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


def _downgrade_fixture_to_v6(settings) -> None:
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


def _downgrade_fixture_to_v7_tariffs(settings) -> None:
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE main.tariffs_v7(
                height_mm INTEGER NOT NULL CHECK(height_mm > 0),
                period_from_days INTEGER NOT NULL CHECK(period_from_days >= 1),
                period_to_days INTEGER,
                price_per_day_minor INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                PRIMARY KEY(height_mm, period_from_days)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO main.tariffs_v7(
                height_mm, period_from_days, period_to_days,
                price_per_day_minor, updated_at, updated_by
            )
            SELECT height_mm, period_from_days, period_to_days,
                   price_per_day_minor, updated_at, updated_by
            FROM main.tariffs
            """
        )
        connection.execute("DROP TABLE main.tariffs")
        connection.execute("ALTER TABLE main.tariffs_v7 RENAME TO tariffs")
        connection.execute(
            """
            UPDATE main.config SET value=?
            WHERE key='penalty_manual_rates_json'
            """,
            (
                json.dumps(
                    {
                        "50": 15,
                        "75": 17,
                        "100": 17,
                        "125": 20,
                        "175": 25,
                        "300": 30,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        connection.execute("UPDATE main.schema_version SET version=7")
        connection.execute("UPDATE archive.schema_version SET version=7")
        connection.commit()


def _downgrade_fixture_to_v8(settings) -> None:
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DROP TABLE archive.operation_cancellations")
        connection.execute("UPDATE main.schema_version SET version=8")
        connection.execute("UPDATE archive.schema_version SET version=8")
        connection.commit()


def _downgrade_fixture_to_v9(settings) -> None:
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            ALTER TABLE archive.operation_cancellations
            RENAME TO operation_cancellations_v10
            """
        )
        connection.execute(
            "DROP INDEX archive.idx_operation_cancellations_contract"
        )
        connection.execute(
            """
            CREATE TABLE archive.operation_cancellations(
                cancellation_id TEXT PRIMARY KEY,
                cancellation_operation_id TEXT NOT NULL UNIQUE,
                original_operation_id TEXT NOT NULL UNIQUE,
                original_action TEXT NOT NULL CHECK(
                    original_action IN ('contract.created', 'contract.renewed')
                ),
                contract_id TEXT NOT NULL,
                cell_number TEXT NOT NULL,
                reason_code TEXT NOT NULL CHECK(
                    reason_code IN (
                        'client_changed', 'change_term', 'input_error'
                    )
                ),
                cancelled_at TEXT NOT NULL,
                cancelled_by TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO archive.operation_cancellations
            SELECT * FROM archive.operation_cancellations_v10
            """
        )
        connection.execute(
            "DROP TABLE archive.operation_cancellations_v10"
        )
        connection.execute(
            """
            CREATE INDEX archive.idx_operation_cancellations_contract
            ON operation_cancellations(contract_id)
            """
        )
        connection.execute("UPDATE main.schema_version SET version=9")
        connection.execute("UPDATE archive.schema_version SET version=9")
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
    with closing(sqlite3.connect(result.backup.working)) as backup:
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
    with closing(sqlite3.connect(result.backup.working)) as backup:
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


def test_explicit_v5_migration_preserves_legacy_bank_block_as_manual_label(
    settings, initialized_databases
):
    _downgrade_fixture_to_v4(settings)

    result = migrate_v4_to_v5(settings, occurred_at=WHEN)

    assert result.changed and result.from_version == 4 and result.to_version == 5
    assert result.backup is not None
    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute("SELECT version FROM main.schema_version").fetchone()[0],
            connection.execute("SELECT version FROM archive.schema_version").fetchone()[0],
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA main.table_info(cell_blocks)")
        }
        block = connection.execute(
            "SELECT block_kind, occupation_label FROM main.cell_blocks WHERE cell_number='1'"
        ).fetchone()
    assert versions == (5, 5)
    assert "occupation_label" in columns
    assert tuple(block) == ("manual", "Занято банком")
    with closing(sqlite3.connect(result.backup.working)) as backup:
        backup_block = backup.execute(
            "SELECT block_kind FROM cell_blocks WHERE cell_number='1'"
        ).fetchone()
        assert backup_block[0] == "bank"


def test_v5_migration_rolls_back_pair_after_partial_failure(
    settings, initialized_databases
):
    _downgrade_fixture_to_v4(settings)

    with pytest.raises(DatabaseMigrationError):
        migrate_v4_to_v5(
            settings,
            occurred_at=WHEN,
            after_data_copy=lambda: (_ for _ in ()).throw(RuntimeError("test")),
        )

    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute("SELECT version FROM main.schema_version").fetchone()[0],
            connection.execute("SELECT version FROM archive.schema_version").fetchone()[0],
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA main.table_info(cell_blocks)")
        }
        block_kind = connection.execute(
            "SELECT block_kind FROM main.cell_blocks WHERE cell_number='1'"
        ).fetchone()[0]
    assert versions == (4, 4)
    assert "occupation_label" not in columns
    assert block_kind == "bank"


def test_explicit_v6_migration_preserves_existing_contracts_and_adds_reminders(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="41", end_date="2026-07-30")
    _downgrade_fixture_to_v5(settings)

    result = migrate_v5_to_v6(settings, occurred_at=WHEN)

    assert result.changed and result.from_version == 5 and result.to_version == 6
    assert result.backup is not None
    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        main_columns = {
            row[1] for row in connection.execute(
                "PRAGMA main.table_info(contracts)"
            )
        }
        archive_columns = {
            row[1] for row in connection.execute(
                "PRAGMA archive.table_info(contracts_archive)"
            )
        }
        contract = connection.execute(
            """
            SELECT client_full_name, client_phone, last_reminded_at, reminder_count
            FROM main.contracts WHERE cell_number='41'
            """
        ).fetchone()
    assert versions == (6, 6)
    assert {"client_phone", "last_reminded_at", "reminder_count"} <= main_columns
    assert {"client_phone", "last_reminded_at", "reminder_count"} <= archive_columns
    assert tuple(contract) == ("Тестовый Клиент", None, None, 0)


def test_v6_migration_rolls_back_both_databases_after_partial_failure(
    settings, initialized_databases
):
    _downgrade_fixture_to_v5(settings)

    with pytest.raises(DatabaseMigrationError):
        migrate_v5_to_v6(
            settings,
            occurred_at=WHEN,
            after_working_change=lambda: (_ for _ in ()).throw(
                RuntimeError("test")
            ),
        )

    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        main_columns = {
            row[1] for row in connection.execute(
                "PRAGMA main.table_info(contracts)"
            )
        }
        archive_columns = {
            row[1] for row in connection.execute(
                "PRAGMA archive.table_info(contracts_archive)"
            )
        }
    assert versions == (5, 5)
    assert "client_phone" not in main_columns
    assert "client_phone" not in archive_columns


def test_explicit_v7_migration_preserves_cells_and_adds_lifecycle(
    settings, initialized_databases
):
    _downgrade_fixture_to_v6(settings)

    result = migrate_v6_to_v7(settings, occurred_at=WHEN)

    assert result.changed and result.from_version == 6 and result.to_version == 7
    assert result.backup is not None
    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA main.table_info(cells)")
        }
        active_count = connection.execute(
            "SELECT COUNT(*) FROM main.cells WHERE is_active=1"
        ).fetchone()[0]
    assert versions == (7, 7)
    assert {"is_active", "retired_at", "retired_by", "retirement_reason"} <= columns
    assert active_count == 126


def test_v7_migration_rolls_back_pair_after_partial_failure(
    settings, initialized_databases
):
    _downgrade_fixture_to_v6(settings)

    with pytest.raises(DatabaseMigrationError):
        migrate_v6_to_v7(
            settings,
            occurred_at=WHEN,
            after_working_change=lambda: (_ for _ in ()).throw(
                RuntimeError("test")
            ),
        )

    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA main.table_info(cells)")
        }
    assert versions == (6, 6)
    assert "is_active" not in columns


def test_v8_migration_preserves_tariffs_and_adds_full_dimensions(
    settings, initialized_databases
):
    _downgrade_fixture_to_v7_tariffs(settings)

    result = migrate_v7_to_v8(settings, occurred_at=WHEN)

    assert result.changed and result.from_version == 7 and result.to_version == 8
    assert result.backup is not None
    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA main.table_info(tariffs)"
            )
        }
        tariff = connection.execute(
            """
            SELECT width_mm, depth_mm, price_per_day_minor
            FROM main.tariffs
            WHERE height_mm=50 AND period_from_days=1
            """
        ).fetchone()
        penalty = connection.execute(
            """
            SELECT value FROM main.config
            WHERE key='penalty_manual_rates_json'
            """
        ).fetchone()[0]
    assert versions == (8, 8)
    assert {"width_mm", "depth_mm"} <= columns
    assert tuple(tariff) == (220, 330, 15)
    assert json.loads(penalty)["50x220x330"] == 15


def test_v8_migration_rolls_back_pair_after_partial_failure(
    settings, initialized_databases
):
    _downgrade_fixture_to_v7_tariffs(settings)

    with pytest.raises(DatabaseMigrationError):
        migrate_v7_to_v8(
            settings,
            occurred_at=WHEN,
            after_working_change=lambda: (_ for _ in ()).throw(
                RuntimeError("test")
            ),
        )

    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA main.table_info(tariffs)"
            )
        }
    assert versions == (7, 7)
    assert "width_mm" not in columns
    assert "depth_mm" not in columns


def test_v9_migration_preserves_data_and_adds_cancellation_registry(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-08-01")
    _downgrade_fixture_to_v8(settings)

    result = migrate_v8_to_v9(settings, occurred_at=WHEN)

    assert result.changed and result.from_version == 8 and result.to_version == 9
    assert result.backup is not None
    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        table = connection.execute(
            """
            SELECT 1 FROM archive.sqlite_master
            WHERE type='table' AND name='operation_cancellations'
            """
        ).fetchone()
        contract = connection.execute(
            "SELECT client_full_name FROM main.contracts WHERE cell_number='1'"
        ).fetchone()
    assert versions == (9, 9)
    assert table is not None
    assert contract[0] == "Тестовый Клиент"
    with closing(sqlite3.connect(result.backup.archive)) as backup:
        assert backup.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='operation_cancellations'
            """
        ).fetchone() is None


def test_v9_migration_rolls_back_pair_after_partial_failure(
    settings, initialized_databases
):
    _downgrade_fixture_to_v8(settings)

    with pytest.raises(DatabaseMigrationError):
        migrate_v8_to_v9(
            settings,
            occurred_at=WHEN,
            after_table_create=lambda: (_ for _ in ()).throw(
                RuntimeError("test")
            ),
        )

    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        table = connection.execute(
            """
            SELECT 1 FROM archive.sqlite_master
            WHERE type='table' AND name='operation_cancellations'
            """
        ).fetchone()
    assert versions == (8, 8)
    assert table is None


def test_v10_migration_preserves_cancellations_and_allows_closure(
    settings, initialized_databases
):
    _downgrade_fixture_to_v9(settings)
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO archive.operation_cancellations(
                cancellation_id, cancellation_operation_id,
                original_operation_id, original_action, contract_id,
                cell_number, reason_code, cancelled_at, cancelled_by
            ) VALUES(
                'cancel-1', 'cancel-op-1', 'original-op-1',
                'contract.renewed', 'contract-1', '1', 'change_term',
                ?, 'Тестовый Сотрудник'
            )
            """,
            (WHEN.isoformat(timespec="seconds"),),
        )
        connection.commit()

    result = migrate_v9_to_v10(settings, occurred_at=WHEN)

    assert result.changed and result.from_version == 9 and result.to_version == 10
    assert result.backup is not None
    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        preserved = connection.execute(
            """
            SELECT original_action FROM archive.operation_cancellations
            WHERE cancellation_id='cancel-1'
            """
        ).fetchone()
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO archive.operation_cancellations(
                cancellation_id, cancellation_operation_id,
                original_operation_id, original_action, contract_id,
                cell_number, reason_code, cancelled_at, cancelled_by
            ) VALUES(
                'cancel-2', 'cancel-op-2', 'original-op-2',
                'contract.closed', 'contract-2', '2', 'client_changed',
                ?, 'Тестовый Сотрудник'
            )
            """,
            (WHEN.isoformat(timespec="seconds"),),
        )
        connection.commit()
    assert versions == (10, 10)
    assert preserved[0] == "contract.renewed"
    with closing(sqlite3.connect(result.backup.archive)) as backup:
        sql = backup.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type='table' AND name='operation_cancellations'
            """
        ).fetchone()[0]
    assert "contract.closed" not in sql


def test_v10_migration_rolls_back_pair_after_partial_failure(
    settings, initialized_databases
):
    _downgrade_fixture_to_v9(settings)

    with pytest.raises(DatabaseMigrationError):
        migrate_v9_to_v10(
            settings,
            occurred_at=WHEN,
            after_table_replace=lambda: (_ for _ in ()).throw(
                RuntimeError("test")
            ),
        )

    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute(
                "SELECT version FROM main.schema_version"
            ).fetchone()[0],
            connection.execute(
                "SELECT version FROM archive.schema_version"
            ).fetchone()[0],
        )
        sql = connection.execute(
            """
            SELECT sql FROM archive.sqlite_master
            WHERE type='table' AND name='operation_cancellations'
            """
        ).fetchone()[0]
    assert versions == (9, 9)
    assert "contract.closed" not in sql


def test_v11_migration_adds_abs_customer_id_without_losing_contracts(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-08-01")
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "ALTER TABLE main.contracts DROP COLUMN abs_customer_id"
        )
        connection.execute(
            "ALTER TABLE archive.contracts_archive DROP COLUMN abs_customer_id"
        )
        connection.execute("UPDATE main.schema_version SET version=10")
        connection.execute("UPDATE archive.schema_version SET version=10")
        connection.commit()

    result = migrate_v10_to_v11(settings, occurred_at=WHEN)

    assert result.changed and result.to_version == 11
    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute("SELECT version FROM main.schema_version").fetchone()[0],
            connection.execute("SELECT version FROM archive.schema_version").fetchone()[0],
        )
        contract = connection.execute(
            "SELECT client_full_name, abs_customer_id FROM main.contracts"
        ).fetchone()
    assert versions == (11, 11)
    assert contract["client_full_name"] == "Тестовый Клиент"
    assert contract["abs_customer_id"] is None


def test_v12_migration_adds_second_phone_and_abs_timeout_without_data_loss(
    settings, initialized_databases, insert_test_contract
):
    insert_test_contract(cell_number="1", end_date="2026-08-01")
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "ALTER TABLE main.contracts DROP COLUMN client_whatsapp_phone"
        )
        connection.execute(
            "ALTER TABLE archive.contracts_archive DROP COLUMN client_whatsapp_phone"
        )
        connection.execute("DELETE FROM main.config WHERE key='abs_session_minutes'")
        connection.execute("UPDATE main.schema_version SET version=11")
        connection.execute("UPDATE archive.schema_version SET version=11")
        connection.commit()

    result = migrate_v11_to_v12(settings, occurred_at=WHEN)

    assert result.changed and result.to_version == 12
    assert result.backup is not None
    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute("SELECT version FROM main.schema_version").fetchone()[0],
            connection.execute("SELECT version FROM archive.schema_version").fetchone()[0],
        )
        contract = connection.execute(
            "SELECT client_full_name, client_whatsapp_phone FROM main.contracts"
        ).fetchone()
        timeout = connection.execute(
            "SELECT value FROM main.config WHERE key='abs_session_minutes'"
        ).fetchone()[0]
    assert versions == (12, 12)
    assert contract["client_full_name"] == "Тестовый Клиент"
    assert contract["client_whatsapp_phone"] is None
    assert timeout == "60"


def test_v12_migration_rolls_back_both_databases_after_partial_failure(
    settings, initialized_databases
):
    with open_write(settings, attach_archive=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "ALTER TABLE main.contracts DROP COLUMN client_whatsapp_phone"
        )
        connection.execute(
            "ALTER TABLE archive.contracts_archive DROP COLUMN client_whatsapp_phone"
        )
        connection.execute("DELETE FROM main.config WHERE key='abs_session_minutes'")
        connection.execute("UPDATE main.schema_version SET version=11")
        connection.execute("UPDATE archive.schema_version SET version=11")
        connection.commit()

    with pytest.raises(DatabaseMigrationError):
        migrate_v11_to_v12(
            settings,
            occurred_at=WHEN,
            after_working_change=lambda: (_ for _ in ()).throw(RuntimeError("test")),
        )

    with open_write(settings, attach_archive=True) as connection:
        versions = (
            connection.execute("SELECT version FROM main.schema_version").fetchone()[0],
            connection.execute("SELECT version FROM archive.schema_version").fetchone()[0],
        )
        working_columns = {
            row[1] for row in connection.execute("PRAGMA main.table_info(contracts)")
        }
        archive_columns = {
            row[1]
            for row in connection.execute("PRAGMA archive.table_info(contracts_archive)")
        }
    assert versions == (11, 11)
    assert "client_whatsapp_phone" not in working_columns
    assert "client_whatsapp_phone" not in archive_columns
