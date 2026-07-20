"""Explicit, backed-up database migrations; never run during normal startup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3
from typing import Callable

from app.config import Settings
from app.db.connections import DatabaseUnavailableError, open_write
from app.db.schema import SCHEMA_VERSION
from app.services.backups import BackupResult, create_backup_pair


class DatabaseMigrationError(RuntimeError):
    """A migration could not be completed safely."""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    from_version: int
    to_version: int
    changed: bool
    backup: BackupResult | None


def migrate_v2_to_v3(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_working_change: Callable[[], None] | None = None,
) -> MigrationResult:
    """Rename the mistaken expiry-date field in both databases atomically."""

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise DatabaseMigrationError("Время миграции должно содержать часовой пояс.")
    try:
        with open_write(settings, attach_archive=True) as connection:
            versions = (
                int(connection.execute("SELECT version FROM main.schema_version WHERE singleton=1").fetchone()[0]),
                int(connection.execute("SELECT version FROM archive.schema_version WHERE singleton=1").fetchone()[0]),
            )
            if versions == (3, 3):
                return MigrationResult(3, 3, False, None)
            if versions != (2, 2):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 2→3."
                )

            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v3",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "ALTER TABLE main.contracts RENAME COLUMN id_card_expiry_date TO id_card_issue_date"
            )
            if after_working_change is not None:
                after_working_change()
            connection.execute(
                "ALTER TABLE archive.contracts_archive RENAME COLUMN id_card_expiry_date TO id_card_issue_date"
            )
            connection.execute(
                "UPDATE main.schema_version SET version=3, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=3, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError("Рабочая база не прошла проверку после миграции.")
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError("Архивная база не прошла проверку после миграции.")
            return MigrationResult(2, 3, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 3. Изменения отменены."
        ) from exc
    except Exception as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 3. Изменения отменены."
        ) from exc


def migrate_v3_to_v4(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_table_create: Callable[[], None] | None = None,
) -> MigrationResult:
    """Add explicit non-contract cell blocks to both-versioned databases."""

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise DatabaseMigrationError("Время миграции должно содержать часовой пояс.")
    try:
        with open_write(settings, attach_archive=True) as connection:
            versions = (
                int(connection.execute(
                    "SELECT version FROM main.schema_version WHERE singleton=1"
                ).fetchone()[0]),
                int(connection.execute(
                    "SELECT version FROM archive.schema_version WHERE singleton=1"
                ).fetchone()[0]),
            )
            if versions == (4, 4):
                return MigrationResult(4, 4, False, None)
            if versions != (3, 3):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 3→4."
                )

            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v4",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            connection.execute("BEGIN IMMEDIATE")
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
                CREATE TRIGGER IF NOT EXISTS main.prevent_contract_on_blocked_cell
                BEFORE INSERT ON contracts
                WHEN EXISTS(
                    SELECT 1 FROM cell_blocks WHERE cell_number = NEW.cell_number
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cell is blocked');
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS main.prevent_block_on_contracted_cell
                BEFORE INSERT ON cell_blocks
                WHEN EXISTS(
                    SELECT 1 FROM contracts WHERE cell_number = NEW.cell_number
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cell has active contract');
                END
                """
            )
            if after_table_create is not None:
                after_table_create()
            connection.execute(
                "UPDATE main.schema_version SET version=4, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=4, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError("Рабочая база не прошла проверку после миграции.")
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError("Архивная база не прошла проверку после миграции.")
            return MigrationResult(3, 4, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 4. Изменения отменены."
        ) from exc
    except Exception as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 4. Изменения отменены."
        ) from exc


def migrate_v4_to_v5(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_data_copy: Callable[[], None] | None = None,
) -> MigrationResult:
    """Replace the bank-only block with a labelled manual occupation."""

    if SCHEMA_VERSION != 5:
        raise DatabaseMigrationError("Эта миграция предназначена только для схемы 5.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise DatabaseMigrationError("Время миграции должно содержать часовой пояс.")
    try:
        with open_write(settings, attach_archive=True) as connection:
            versions = (
                int(connection.execute(
                    "SELECT version FROM main.schema_version WHERE singleton=1"
                ).fetchone()[0]),
                int(connection.execute(
                    "SELECT version FROM archive.schema_version WHERE singleton=1"
                ).fetchone()[0]),
            )
            if versions == (5, 5):
                return MigrationResult(5, 5, False, None)
            if versions != (4, 4):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 4→5."
                )

            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v5",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TRIGGER main.prevent_contract_on_blocked_cell")
            connection.execute("DROP TRIGGER main.prevent_block_on_contracted_cell")
            connection.execute("ALTER TABLE main.cell_blocks RENAME TO cell_blocks_v4")
            connection.execute(
                """
                CREATE TABLE main.cell_blocks(
                    cell_number TEXT PRIMARY KEY REFERENCES cells(number),
                    block_kind TEXT NOT NULL CHECK(block_kind IN ('lost_key', 'manual')),
                    source_contract_id TEXT,
                    occupation_label TEXT,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    CHECK(
                        (
                            block_kind = 'lost_key'
                            AND source_contract_id IS NOT NULL
                            AND occupation_label IS NULL
                        )
                        OR (
                            block_kind = 'manual'
                            AND source_contract_id IS NULL
                            AND length(trim(occupation_label)) BETWEEN 1 AND 80
                        )
                    )
                )
                """
            )
            connection.execute(
                """
                INSERT INTO main.cell_blocks(
                    cell_number, block_kind, source_contract_id,
                    occupation_label, created_at, created_by
                )
                SELECT
                    cell_number,
                    CASE block_kind WHEN 'bank' THEN 'manual' ELSE block_kind END,
                    source_contract_id,
                    CASE block_kind WHEN 'bank' THEN 'Занято банком' ELSE NULL END,
                    created_at,
                    created_by
                FROM main.cell_blocks_v4
                """
            )
            if after_data_copy is not None:
                after_data_copy()
            connection.execute("DROP TABLE main.cell_blocks_v4")
            connection.execute(
                """
                CREATE TRIGGER main.prevent_contract_on_blocked_cell
                BEFORE INSERT ON contracts
                WHEN EXISTS(
                    SELECT 1 FROM cell_blocks WHERE cell_number = NEW.cell_number
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cell is blocked');
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER main.prevent_block_on_contracted_cell
                BEFORE INSERT ON cell_blocks
                WHEN EXISTS(
                    SELECT 1 FROM contracts WHERE cell_number = NEW.cell_number
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cell has active contract');
                END
                """
            )
            connection.execute(
                "UPDATE main.schema_version SET version=5, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=5, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError("Рабочая база не прошла проверку после миграции.")
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError("Архивная база не прошла проверку после миграции.")
            return MigrationResult(4, 5, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 5. Изменения отменены."
        ) from exc
    except Exception as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 5. Изменения отменены."
        ) from exc
