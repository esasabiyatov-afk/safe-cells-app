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

    if SCHEMA_VERSION < 5:
        raise DatabaseMigrationError("Эта миграция требует схему приложения не ниже 5.")
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


def migrate_v5_to_v6(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_working_change: Callable[[], None] | None = None,
) -> MigrationResult:
    """Add client phone and per-contract WhatsApp reminder state."""

    if SCHEMA_VERSION < 6:
        raise DatabaseMigrationError("Эта миграция предназначена только для схемы 6.")
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
            if versions == (6, 6):
                return MigrationResult(6, 6, False, None)
            if versions != (5, 5):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 5→6."
                )

            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v6",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ALTER TABLE main.contracts ADD COLUMN client_phone TEXT")
            connection.execute(
                "ALTER TABLE main.contracts ADD COLUMN last_reminded_at TEXT"
            )
            connection.execute(
                """
                ALTER TABLE main.contracts
                ADD COLUMN reminder_count INTEGER NOT NULL DEFAULT 0
                CHECK(reminder_count >= 0)
                """
            )
            if after_working_change is not None:
                after_working_change()
            connection.execute(
                "ALTER TABLE archive.contracts_archive ADD COLUMN client_phone TEXT"
            )
            connection.execute(
                """
                ALTER TABLE archive.contracts_archive
                ADD COLUMN last_reminded_at TEXT
                """
            )
            connection.execute(
                """
                ALTER TABLE archive.contracts_archive
                ADD COLUMN reminder_count INTEGER NOT NULL DEFAULT 0
                CHECK(reminder_count >= 0)
                """
            )
            connection.execute(
                "UPDATE main.schema_version SET version=6, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=6, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Рабочая база не прошла проверку после миграции."
                )
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Архивная база не прошла проверку после миграции."
                )
            return MigrationResult(5, 6, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 6. Изменения отменены."
        ) from exc
    except Exception as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 6. Изменения отменены."
        ) from exc


def migrate_v6_to_v7(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_working_change: Callable[[], None] | None = None,
) -> MigrationResult:
    """Add the lifecycle state used to retire physical cells safely."""

    if SCHEMA_VERSION < 7:
        raise DatabaseMigrationError("Эта миграция предназначена только для схемы 7.")
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
            if versions == (7, 7):
                return MigrationResult(7, 7, False, None)
            if versions != (6, 6):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 6→7."
                )

            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v7",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "ALTER TABLE main.cells ADD COLUMN is_active INTEGER NOT NULL "
                "DEFAULT 1 CHECK(is_active IN (0, 1))"
            )
            connection.execute("ALTER TABLE main.cells ADD COLUMN retired_at TEXT")
            connection.execute("ALTER TABLE main.cells ADD COLUMN retired_by TEXT")
            connection.execute(
                "ALTER TABLE main.cells ADD COLUMN retirement_reason TEXT"
            )
            connection.execute(
                """
                CREATE TRIGGER main.prevent_contract_on_inactive_cell
                BEFORE INSERT ON contracts
                WHEN EXISTS(
                    SELECT 1 FROM cells
                    WHERE number = NEW.cell_number AND is_active = 0
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cell is inactive');
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER main.prevent_block_on_inactive_cell
                BEFORE INSERT ON cell_blocks
                WHEN EXISTS(
                    SELECT 1 FROM cells
                    WHERE number = NEW.cell_number AND is_active = 0
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cell is inactive');
                END
                """
            )
            connection.execute(
                """
                CREATE TRIGGER main.prevent_retire_occupied_cell
                BEFORE UPDATE OF is_active ON cells
                WHEN NEW.is_active = 0 AND (
                    EXISTS(
                        SELECT 1 FROM contracts WHERE cell_number = NEW.number
                    )
                    OR EXISTS(
                        SELECT 1 FROM cell_blocks WHERE cell_number = NEW.number
                    )
                )
                BEGIN
                    SELECT RAISE(ABORT, 'occupied cell cannot be retired');
                END
                """
            )
            if after_working_change is not None:
                after_working_change()
            connection.execute(
                "UPDATE main.schema_version SET version=7, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=7, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Рабочая база не прошла проверку после миграции."
                )
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Архивная база не прошла проверку после миграции."
                )
            return MigrationResult(6, 7, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error, RuntimeError) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 7. Изменения отменены."
        ) from exc


def migrate_v7_to_v8(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_working_change: Callable[[], None] | None = None,
) -> MigrationResult:
    """Make tariffs and manual penalty rates depend on the full physical size."""

    if SCHEMA_VERSION < 8:
        raise DatabaseMigrationError("Эта миграция требует схему не ниже версии 8.")
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
            if versions == (8, 8):
                return MigrationResult(8, 8, False, None)
            if versions != (7, 7):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 7→8."
                )
            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v8",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            defaults = connection.execute(
                "SELECT width_mm, depth_mm FROM main.vault_defaults WHERE id=1"
            ).fetchone()
            if defaults is None:
                raise DatabaseMigrationError("Общие размеры депозитария отсутствуют.")
            width_mm, depth_mm = int(defaults[0]), int(defaults[1])
            old_penalty = connection.execute(
                "SELECT value FROM main.config WHERE key='penalty_manual_rates_json'"
            ).fetchone()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE main.tariffs_v8(
                    height_mm INTEGER NOT NULL CHECK(height_mm > 0),
                    width_mm INTEGER NOT NULL CHECK(width_mm > 0),
                    depth_mm INTEGER NOT NULL CHECK(depth_mm > 0),
                    period_from_days INTEGER NOT NULL CHECK(period_from_days >= 1),
                    period_to_days INTEGER CHECK(
                        period_to_days IS NULL
                        OR period_to_days >= period_from_days
                    ),
                    price_per_day_minor INTEGER NOT NULL
                        CHECK(price_per_day_minor >= 0),
                    updated_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    PRIMARY KEY(
                        height_mm, width_mm, depth_mm, period_from_days
                    )
                )
                """
            )
            connection.execute(
                """
                INSERT INTO main.tariffs_v8(
                    height_mm, width_mm, depth_mm, period_from_days,
                    period_to_days, price_per_day_minor, updated_at, updated_by
                )
                SELECT height_mm, ?, ?, period_from_days, period_to_days,
                       price_per_day_minor, updated_at, updated_by
                FROM main.tariffs
                """,
                (width_mm, depth_mm),
            )
            connection.execute("DROP TABLE main.tariffs")
            connection.execute("ALTER TABLE main.tariffs_v8 RENAME TO tariffs")
            if old_penalty is not None:
                import json

                try:
                    decoded = json.loads(str(old_penalty[0]))
                    converted = {
                        f"{int(height)}x{width_mm}x{depth_mm}": int(rate)
                        for height, rate in decoded.items()
                    }
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise DatabaseMigrationError(
                        "Ручные штрафные ставки повреждены."
                    ) from exc
                connection.execute(
                    """
                    UPDATE main.config
                    SET value=?, updated_at=?, updated_by='schema-v8'
                    WHERE key='penalty_manual_rates_json'
                    """,
                    (
                        json.dumps(
                            converted,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        timestamp,
                    ),
                )
            if after_working_change is not None:
                after_working_change()
            connection.execute(
                "UPDATE main.schema_version SET version=8, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=8, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Рабочая база не прошла проверку после миграции."
                )
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Архивная база не прошла проверку после миграции."
                )
            return MigrationResult(7, 8, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 8. Изменения отменены."
        ) from exc
    except Exception as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 8. Изменения отменены."
        ) from exc


def migrate_v8_to_v9(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_table_create: Callable[[], None] | None = None,
) -> MigrationResult:
    """Add an append-only registry for cancelled openings and renewals."""

    if SCHEMA_VERSION < 9:
        raise DatabaseMigrationError("Эта миграция требует схему не ниже версии 9.")
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
            if versions == (9, 9):
                return MigrationResult(9, 9, False, None)
            if versions != (8, 8):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 8→9."
                )
            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v9",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            connection.execute("BEGIN IMMEDIATE")
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
                CREATE INDEX archive.idx_operation_cancellations_contract
                ON operation_cancellations(contract_id)
                """
            )
            if after_table_create is not None:
                after_table_create()
            connection.execute(
                "UPDATE main.schema_version SET version=9, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=9, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Рабочая база не прошла проверку после миграции."
                )
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Архивная база не прошла проверку после миграции."
                )
            return MigrationResult(8, 9, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error, RuntimeError) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 9. Изменения отменены."
        ) from exc


def migrate_v9_to_v10(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_table_replace: Callable[[], None] | None = None,
) -> MigrationResult:
    """Allow the cancellation registry to reference contract closures."""

    if SCHEMA_VERSION < 10:
        raise DatabaseMigrationError("Эта миграция требует схему не ниже версии 10.")
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
            if versions == (10, 10):
                return MigrationResult(10, 10, False, None)
            if versions != (9, 9):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 9→10."
                )
            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v10",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                ALTER TABLE archive.operation_cancellations
                RENAME TO operation_cancellations_v9
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
                        original_action IN (
                            'contract.created', 'contract.renewed',
                            'contract.closed'
                        )
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
                INSERT INTO archive.operation_cancellations(
                    cancellation_id, cancellation_operation_id,
                    original_operation_id, original_action, contract_id,
                    cell_number, reason_code, cancelled_at, cancelled_by
                )
                SELECT
                    cancellation_id, cancellation_operation_id,
                    original_operation_id, original_action, contract_id,
                    cell_number, reason_code, cancelled_at, cancelled_by
                FROM archive.operation_cancellations_v9
                """
            )
            connection.execute(
                "DROP TABLE archive.operation_cancellations_v9"
            )
            connection.execute(
                """
                CREATE INDEX archive.idx_operation_cancellations_contract
                ON operation_cancellations(contract_id)
                """
            )
            if after_table_replace is not None:
                after_table_replace()
            connection.execute(
                "UPDATE main.schema_version SET version=10, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=10, applied_at=? WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Рабочая база не прошла проверку после миграции."
                )
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Архивная база не прошла проверку после миграции."
                )
            return MigrationResult(9, 10, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error, RuntimeError) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 10. Изменения отменены."
        ) from exc


def migrate_v10_to_v11(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_working_change: Callable[[], None] | None = None,
) -> MigrationResult:
    """Store the stable ABS customer identifier with active and closed contracts."""

    if SCHEMA_VERSION < 11:
        raise DatabaseMigrationError("Эта миграция требует схему не ниже версии 11.")
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
            if versions == (11, 11):
                return MigrationResult(11, 11, False, None)
            if versions != (10, 10):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 10→11."
                )
            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v11",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "ALTER TABLE main.contracts ADD COLUMN abs_customer_id TEXT"
            )
            if after_working_change is not None:
                after_working_change()
            connection.execute(
                "ALTER TABLE archive.contracts_archive "
                "ADD COLUMN abs_customer_id TEXT"
            )
            connection.execute(
                "UPDATE main.schema_version SET version=11, applied_at=? "
                "WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=11, applied_at=? "
                "WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Рабочая база не прошла проверку после миграции."
                )
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Архивная база не прошла проверку после миграции."
                )
            return MigrationResult(10, 11, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error, RuntimeError) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 11. Изменения отменены."
        ) from exc


def migrate_v11_to_v12(
    settings: Settings,
    *,
    occurred_at: datetime,
    after_working_change: Callable[[], None] | None = None,
) -> MigrationResult:
    """Store both client phones and configure the ABS session duration."""

    if SCHEMA_VERSION < 12:
        raise DatabaseMigrationError("Эта миграция требует схему не ниже версии 12.")
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
            if versions == (12, 12):
                return MigrationResult(12, 12, False, None)
            if versions != (11, 11):
                raise DatabaseMigrationError(
                    "Версии рабочей и архивной баз не соответствуют миграции 11→12."
                )
            backup = create_backup_pair(
                connection,
                settings,
                operation_id="before-schema-v12",
                occurred_at=occurred_at,
            )
            timestamp = occurred_at.isoformat(timespec="seconds")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "ALTER TABLE main.contracts ADD COLUMN client_whatsapp_phone TEXT"
            )
            connection.execute(
                "INSERT OR IGNORE INTO main.config(key, value, updated_at, updated_by) "
                "VALUES('abs_session_minutes', '60', ?, 'Миграция схемы')",
                (timestamp,),
            )
            if after_working_change is not None:
                after_working_change()
            connection.execute(
                "ALTER TABLE archive.contracts_archive "
                "ADD COLUMN client_whatsapp_phone TEXT"
            )
            connection.execute(
                "UPDATE main.schema_version SET version=12, applied_at=? "
                "WHERE singleton=1",
                (timestamp,),
            )
            connection.execute(
                "UPDATE archive.schema_version SET version=12, applied_at=? "
                "WHERE singleton=1",
                (timestamp,),
            )
            connection.commit()
            if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Рабочая база не прошла проверку после миграции."
                )
            if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
                raise DatabaseMigrationError(
                    "Архивная база не прошла проверку после миграции."
                )
            return MigrationResult(11, 12, True, backup)
    except DatabaseMigrationError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error, RuntimeError) as exc:
        raise DatabaseMigrationError(
            "Не удалось безопасно обновить базы до версии 12. Изменения отменены."
        ) from exc
