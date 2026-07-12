"""Consistent SQLite Backup API snapshots after successful writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3

from app.config import Settings


@dataclass(frozen=True, slots=True)
class BackupResult:
    working: Path
    archive: Path


def _quick_check(path: Path) -> None:
    connection = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("Backup failed quick_check")
    finally:
        connection.close()


def _rotate_complete_pairs(directory: Path, *, keep: int = 30) -> None:
    working_by_stem = {
        path.name.removesuffix(".working.sqlite3"): path
        for path in directory.glob("*.working.sqlite3")
    }
    archive_by_stem = {
        path.name.removesuffix(".archive.sqlite3"): path
        for path in directory.glob("*.archive.sqlite3")
    }
    complete_stems = sorted(set(working_by_stem) & set(archive_by_stem), reverse=True)
    for stem in complete_stems[keep:]:
        working_by_stem[stem].unlink(missing_ok=True)
        archive_by_stem[stem].unlink(missing_ok=True)


def create_backup_pair(
    source: sqlite3.Connection,
    settings: Settings,
    *,
    operation_id: str,
    occurred_at: datetime,
) -> BackupResult:
    """Back up main and attached archive databases to verified temporary files."""

    backup_directory = settings.database_directory / "backups"
    backup_directory.mkdir(exist_ok=True)
    timestamp = occurred_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{timestamp}_{operation_id}"
    final_working = backup_directory / f"{stem}.working.sqlite3"
    final_archive = backup_directory / f"{stem}.archive.sqlite3"
    temporary_working = backup_directory / f".{stem}.working.tmp"
    temporary_archive = backup_directory / f".{stem}.archive.tmp"
    snapshot_started = False

    try:
        if source.in_transaction:
            raise sqlite3.OperationalError("Backup source already has a transaction")
        source.execute("BEGIN")
        snapshot_started = True
        source.execute(
            "SELECT version FROM main.schema_version WHERE singleton = 1"
        ).fetchone()
        source.execute(
            "SELECT version FROM archive.schema_version WHERE singleton = 1"
        ).fetchone()
        destination = sqlite3.connect(temporary_working)
        try:
            source.backup(destination, name="main")
        finally:
            destination.close()
        destination = sqlite3.connect(temporary_archive)
        try:
            source.backup(destination, name="archive")
        finally:
            destination.close()
        _quick_check(temporary_working)
        _quick_check(temporary_archive)
        os.replace(temporary_working, final_working)
        os.replace(temporary_archive, final_archive)
        _rotate_complete_pairs(backup_directory)
        return BackupResult(working=final_working, archive=final_archive)
    except Exception:
        final_working.unlink(missing_ok=True)
        final_archive.unlink(missing_ok=True)
        raise
    finally:
        if snapshot_started and source.in_transaction:
            source.rollback()
        temporary_working.unlink(missing_ok=True)
        temporary_archive.unlink(missing_ok=True)
