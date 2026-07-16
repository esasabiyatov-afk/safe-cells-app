"""Short-lived SQLite connections with network-safe settings."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterator

from app.config import Settings


NETWORK_ERROR_MESSAGE = (
    "Не удалось получить данные с сетевого диска. Проверьте подключение к сети"
)


class DatabaseUnavailableError(RuntimeError):
    """Raised when the configured database pair cannot be safely used."""


class DatabaseCorruptionError(DatabaseUnavailableError):
    """Raised when integrity checks have blocked all write operations."""


class DatabaseMaintenanceError(DatabaseUnavailableError):
    """Raised while a controlled restore owns the shared maintenance lock."""


@dataclass(frozen=True, slots=True)
class DatabasePaths:
    directory: Path
    working: Path
    archive: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> "DatabasePaths":
        directory = settings.database_directory
        return cls(
            directory=directory,
            working=directory / settings.working_database_name,
            archive=directory / settings.archive_database_name,
        )


def validate_database_directory(settings: Settings) -> DatabasePaths:
    """Validate the configured directory without creating anything."""

    paths = DatabasePaths.from_settings(settings)
    try:
        if not paths.directory.is_dir():
            raise DatabaseUnavailableError(NETWORK_ERROR_MESSAGE)
    except OSError as exc:
        raise DatabaseUnavailableError(NETWORK_ERROR_MESSAGE) from exc
    return paths


def validate_database_pair(settings: Settings) -> DatabasePaths:
    """Require both existing databases; never create a local replacement."""

    paths = validate_database_directory(settings)
    try:
        if not paths.working.is_file() or not paths.archive.is_file():
            raise DatabaseUnavailableError(NETWORK_ERROR_MESSAGE)
    except OSError as exc:
        raise DatabaseUnavailableError(NETWORK_ERROR_MESSAGE) from exc
    return paths


def _readonly_uri(path: Path) -> str:
    return f"{path.absolute().as_uri()}?mode=ro"


@contextmanager
def open_readonly(path: Path, *, busy_timeout_ms: int = 15_000) -> Iterator[sqlite3.Connection]:
    """Open a read-only URI connection and close it immediately after use."""

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            _readonly_uri(path),
            uri=True,
            timeout=busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        connection.execute("PRAGMA query_only=ON")
    except (OSError, sqlite3.Error) as exc:
        if connection is not None:
            connection.close()
        raise DatabaseUnavailableError(NETWORK_ERROR_MESSAGE) from exc

    try:
        yield connection
    finally:
        connection.close()


def _configure_write_connection(
    connection: sqlite3.Connection, *, busy_timeout_ms: int
) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    connection.execute("PRAGMA main.journal_mode=DELETE")
    connection.execute("PRAGMA main.synchronous=FULL")
    connection.execute("PRAGMA main.locking_mode=NORMAL")


@contextmanager
def open_write(
    settings: Settings,
    *,
    attach_archive: bool = False,
    bypass_integrity_guard: bool = False,
    bypass_maintenance_guard: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Open a short write-capable connection without starting a transaction."""

    if not bypass_maintenance_guard:
        from app.services.instances import MaintenanceActiveError, ensure_maintenance_inactive

        try:
            ensure_maintenance_inactive(settings)
        except MaintenanceActiveError as exc:
            raise DatabaseMaintenanceError(str(exc)) from exc
    if not bypass_integrity_guard:
        from app.services.backups import (
            DatabaseCorruptionError as BackupDatabaseCorruptionError,
            assert_writes_allowed,
        )

        try:
            assert_writes_allowed(settings)
        except BackupDatabaseCorruptionError as exc:
            raise DatabaseCorruptionError(str(exc)) from exc
    from app.services.instances import InstanceCoordinationError, application_write_lock

    paths = validate_database_pair(settings)
    write_guard = application_write_lock(settings)
    try:
        write_guard.__enter__()
    except InstanceCoordinationError as exc:
        if "занята" in str(exc).lower():
            raise sqlite3.OperationalError("database is locked") from exc
        raise DatabaseUnavailableError(str(exc)) from exc
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            str(paths.working),
            timeout=settings.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        _configure_write_connection(
            connection, busy_timeout_ms=settings.busy_timeout_ms
        )
        if attach_archive:
            connection.execute("ATTACH DATABASE ? AS archive", (str(paths.archive),))
            connection.execute("PRAGMA archive.journal_mode=DELETE")
            connection.execute("PRAGMA archive.synchronous=FULL")
            connection.execute("PRAGMA archive.locking_mode=NORMAL")
        yield connection
    finally:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        write_guard.__exit__(None, None, None)


def check_database_pair(settings: Settings) -> dict[str, int]:
    """Read schema versions using two separate read-only connections."""

    paths = validate_database_pair(settings)
    try:
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            working_version = connection.execute(
                "SELECT version FROM schema_version WHERE singleton = 1"
            ).fetchone()
        with open_readonly(
            paths.archive, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            archive_version = connection.execute(
                "SELECT version FROM schema_version WHERE singleton = 1"
            ).fetchone()
    except DatabaseUnavailableError:
        raise
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError(NETWORK_ERROR_MESSAGE) from exc

    if working_version is None or archive_version is None:
        raise DatabaseUnavailableError(NETWORK_ERROR_MESSAGE)
    return {
        "working": int(working_version["version"]),
        "archive": int(archive_version["version"]),
    }
