"""Idempotent, explicitly invoked initialization of the database pair."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
from uuid import uuid4

from app.config import Settings
from app.db.connections import (
    DatabasePaths,
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    validate_database_directory,
)
from app.db.seed import load_cell_seed, seed_working_database


SCHEMA_VERSION = 3


class DatabaseInitializationError(RuntimeError):
    """Raised when explicit initialization cannot safely complete."""


@dataclass(frozen=True, slots=True)
class InitializationResult:
    working_database: Path
    archive_database: Path
    cell_count: int
    tariff_count: int
    schema_version: int
    created: bool


WORKING_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS main.schema_version(
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        version INTEGER NOT NULL CHECK(version >= 1),
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS main.vault_defaults(
        id INTEGER PRIMARY KEY CHECK(id = 1),
        width_mm INTEGER NOT NULL CHECK(width_mm > 0),
        depth_mm INTEGER NOT NULL CHECK(depth_mm > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS main.cells(
        number TEXT PRIMARY KEY CHECK(length(trim(number)) > 0),
        height_mm INTEGER NOT NULL CHECK(height_mm > 0),
        width_mm INTEGER CHECK(width_mm IS NULL OR width_mm > 0),
        depth_mm INTEGER CHECK(depth_mm IS NULL OR depth_mm > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS main.tariffs(
        height_mm INTEGER NOT NULL CHECK(height_mm > 0),
        period_from_days INTEGER NOT NULL CHECK(period_from_days >= 1),
        period_to_days INTEGER CHECK(
            period_to_days IS NULL OR period_to_days >= period_from_days
        ),
        price_per_day_minor INTEGER NOT NULL CHECK(price_per_day_minor >= 0),
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        PRIMARY KEY(height_mm, period_from_days)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS main.config(
        key TEXT PRIMARY KEY CHECK(length(trim(key)) > 0),
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS main.contracts(
        contract_id TEXT PRIMARY KEY,
        cell_number TEXT NOT NULL UNIQUE REFERENCES cells(number),
        client_full_name TEXT NOT NULL CHECK(length(trim(client_full_name)) > 0),
        id_card_number TEXT NOT NULL CHECK(length(trim(id_card_number)) > 0),
        id_card_issuer TEXT NOT NULL CHECK(length(trim(id_card_issuer)) > 0),
        id_card_issue_date TEXT NOT NULL,
        account_number TEXT NOT NULL CHECK(length(trim(account_number)) > 0),
        extra_fields_json TEXT NOT NULL DEFAULT '{}',
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL CHECK(end_date >= start_date),
        rent_days INTEGER NOT NULL CHECK(rent_days >= 1),
        price_per_day_minor INTEGER NOT NULL CHECK(price_per_day_minor >= 0),
        rent_price_minor INTEGER NOT NULL CHECK(
            rent_price_minor = rent_days * price_per_day_minor
        ),
        deposit_amount_minor INTEGER NOT NULL CHECK(deposit_amount_minor >= 0),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS main.admin_credentials(
        id INTEGER PRIMARY KEY CHECK(id = 1),
        password_hash TEXT NOT NULL,
        changed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS main.document_templates(
        template_id TEXT PRIMARY KEY,
        document_type TEXT NOT NULL,
        display_name TEXT NOT NULL,
        relative_file_name TEXT NOT NULL,
        required_placeholders_json TEXT NOT NULL,
        is_active INTEGER NOT NULL CHECK(is_active IN (0, 1)),
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    )
    """,
)


ARCHIVE_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS archive.schema_version(
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        version INTEGER NOT NULL CHECK(version >= 1),
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archive.contracts_archive(
        contract_id TEXT PRIMARY KEY,
        cell_number TEXT NOT NULL,
        client_full_name TEXT NOT NULL,
        id_card_number TEXT NOT NULL,
        id_card_issuer TEXT NOT NULL,
        id_card_issue_date TEXT NOT NULL,
        account_number TEXT NOT NULL,
        extra_fields_json TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        rent_days INTEGER NOT NULL CHECK(rent_days >= 1),
        price_per_day_minor INTEGER NOT NULL CHECK(price_per_day_minor >= 0),
        rent_price_minor INTEGER NOT NULL CHECK(rent_price_minor >= 0),
        deposit_amount_minor INTEGER NOT NULL CHECK(deposit_amount_minor >= 0),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        closed_at TEXT NOT NULL,
        close_date TEXT NOT NULL,
        close_reason TEXT NOT NULL,
        close_kind TEXT NOT NULL CHECK(close_kind IN ('early', 'on_time', 'overdue')),
        unused_days INTEGER NOT NULL CHECK(unused_days >= 0),
        penalty_days INTEGER NOT NULL CHECK(penalty_days >= 0),
        penalty_rate_minor INTEGER NOT NULL CHECK(penalty_rate_minor >= 0),
        penalty_amount_minor INTEGER NOT NULL CHECK(penalty_amount_minor >= 0),
        deposit_refund_minor INTEGER NOT NULL CHECK(deposit_refund_minor >= 0),
        closed_by TEXT NOT NULL,
        operation_id TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS archive.renewals(
        renewal_id TEXT PRIMARY KEY,
        contract_id TEXT NOT NULL,
        cell_number TEXT NOT NULL,
        old_end_date TEXT NOT NULL,
        renewal_date TEXT NOT NULL,
        new_start_date TEXT NOT NULL,
        new_end_date TEXT NOT NULL CHECK(new_end_date >= new_start_date),
        renewal_days INTEGER NOT NULL CHECK(renewal_days >= 1),
        price_per_day_minor INTEGER NOT NULL CHECK(price_per_day_minor >= 0),
        renewal_price_minor INTEGER NOT NULL CHECK(renewal_price_minor >= 0),
        penalty_days INTEGER NOT NULL CHECK(penalty_days >= 0),
        penalty_rate_minor INTEGER NOT NULL CHECK(penalty_rate_minor >= 0),
        penalty_amount_minor INTEGER NOT NULL CHECK(penalty_amount_minor >= 0),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        operation_id TEXT NOT NULL UNIQUE
    )
    """,
    "CREATE INDEX IF NOT EXISTS archive.idx_renewals_contract ON renewals(contract_id)",
    """
    CREATE TABLE IF NOT EXISTS archive.log(
        log_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL UNIQUE,
        occurred_at TEXT NOT NULL,
        employee TEXT NOT NULL,
        action TEXT NOT NULL,
        contract_id TEXT,
        cell_number TEXT,
        changes_json TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS archive.idx_log_contract ON log(contract_id)",
    "CREATE INDEX IF NOT EXISTS archive.idx_log_cell ON log(cell_number)",
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _configure_initialization_connection(
    connection: sqlite3.Connection, *, busy_timeout_ms: int
) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    connection.execute("PRAGMA main.journal_mode=DELETE")
    connection.execute("PRAGMA main.synchronous=FULL")
    connection.execute("PRAGMA main.locking_mode=NORMAL")
    connection.execute("PRAGMA archive.journal_mode=DELETE")
    connection.execute("PRAGMA archive.synchronous=FULL")
    connection.execute("PRAGMA archive.locking_mode=NORMAL")


def _initialize_pair(
    paths: DatabasePaths,
    settings: Settings,
    *,
    cells_csv_path: Path,
) -> None:
    cells = load_cell_seed(cells_csv_path)
    applied_at = _timestamp()
    connection = sqlite3.connect(
        str(paths.working),
        timeout=settings.busy_timeout_ms / 1000,
        isolation_level=None,
    )
    try:
        connection.execute("ATTACH DATABASE ? AS archive", (str(paths.archive),))
        _configure_initialization_connection(
            connection, busy_timeout_ms=settings.busy_timeout_ms
        )
        connection.execute("BEGIN IMMEDIATE")
        for statement in WORKING_SCHEMA:
            connection.execute(statement)
        for statement in ARCHIVE_SCHEMA:
            connection.execute(statement)
        working_version = connection.execute(
            "SELECT version FROM main.schema_version WHERE singleton = 1"
        ).fetchone()
        archive_version = connection.execute(
            "SELECT version FROM archive.schema_version WHERE singleton = 1"
        ).fetchone()
        if working_version is not None and int(working_version[0]) != SCHEMA_VERSION:
            raise DatabaseInitializationError(
                "Версия рабочей базы несовместима с этой версией приложения."
            )
        if archive_version is not None and int(archive_version[0]) != SCHEMA_VERSION:
            raise DatabaseInitializationError(
                "Версия архивной базы несовместима с этой версией приложения."
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO main.schema_version(singleton, version, applied_at)
            VALUES(1, ?, ?)
            """,
            (SCHEMA_VERSION, applied_at),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO archive.schema_version(singleton, version, applied_at)
            VALUES(1, ?, ?)
            """,
            (SCHEMA_VERSION, applied_at),
        )
        seed_working_database(
            connection,
            cells,
            applied_at=applied_at,
            template_directory=settings.database_directory / "templates",
        )
        connection.commit()

        if connection.execute("PRAGMA main.quick_check").fetchone()[0] != "ok":
            raise DatabaseInitializationError("Рабочая база не прошла quick_check.")
        if connection.execute("PRAGMA archive.quick_check").fetchone()[0] != "ok":
            raise DatabaseInitializationError("Архивная база не прошла quick_check.")
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _initialization_result(paths: DatabasePaths, *, created: bool) -> InitializationResult:
    connection = sqlite3.connect(f"{paths.working.absolute().as_uri()}?mode=ro", uri=True)
    try:
        cell_count = int(connection.execute("SELECT COUNT(*) FROM cells").fetchone()[0])
        tariff_count = int(
            connection.execute("SELECT COUNT(*) FROM tariffs").fetchone()[0]
        )
        version = int(
            connection.execute(
                "SELECT version FROM schema_version WHERE singleton = 1"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    return InitializationResult(
        working_database=paths.working,
        archive_database=paths.archive,
        cell_count=cell_count,
        tariff_count=tariff_count,
        schema_version=version,
        created=created,
    )


def initialize_databases(
    settings: Settings,
    *,
    cells_csv_path: Path | str,
) -> InitializationResult:
    """Explicitly create or idempotently verify/seed both databases."""

    paths = validate_database_directory(settings)
    working_exists = paths.working.exists()
    archive_exists = paths.archive.exists()
    if working_exists != archive_exists:
        raise DatabaseInitializationError(
            "Найдена только одна из двух баз. Инициализация остановлена без изменений."
        )

    if working_exists:
        try:
            _initialize_pair(paths, settings, cells_csv_path=Path(cells_csv_path))
            return _initialization_result(paths, created=False)
        except (OSError, sqlite3.Error) as exc:
            raise DatabaseInitializationError(NETWORK_ERROR_MESSAGE) from exc

    token = uuid4().hex
    temporary_paths = DatabasePaths(
        directory=paths.directory,
        working=paths.directory / f".{paths.working.name}.{token}.initializing",
        archive=paths.directory / f".{paths.archive.name}.{token}.initializing",
    )
    archive_moved = False
    try:
        _initialize_pair(
            temporary_paths, settings, cells_csv_path=Path(cells_csv_path)
        )
        os.replace(temporary_paths.archive, paths.archive)
        archive_moved = True
        os.replace(temporary_paths.working, paths.working)
        return _initialization_result(paths, created=True)
    except (OSError, sqlite3.Error) as exc:
        if archive_moved and paths.archive.exists() and not paths.working.exists():
            paths.archive.unlink(missing_ok=True)
        raise DatabaseInitializationError(NETWORK_ERROR_MESSAGE) from exc
    finally:
        temporary_paths.working.unlink(missing_ok=True)
        temporary_paths.archive.unlink(missing_ok=True)
