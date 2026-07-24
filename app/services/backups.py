"""Verified two-database backup sets and controlled restoration."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Callable
from uuid import uuid4

from app.config import Settings
from app.db.connections import (
    DatabaseCorruptionError,
    DatabasePaths,
    validate_database_pair,
)
from app.services.instances import InstanceCoordinationError, maintenance_lock


BACKUP_DIRECTORY_NAME = "backups"
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
WRITE_BLOCK_NAME = "write-block.json"
QUARANTINE_DIRECTORY_NAME = "damaged-originals"
RESTORE_CONFIRMATION = "ВОССТАНОВИТЬ"
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


class BackupError(RuntimeError):
    """A backup set could not be created or verified."""


class BackupBusyError(BackupError):
    """Another writer did not release the databases in time."""


class BackupNetworkError(BackupError):
    """The shared backup location is unavailable."""


class BackupValidationError(BackupError):
    """A published backup set is incomplete or altered."""


class RestoreError(RuntimeError):
    """Controlled restoration could not be completed safely."""


class RestoreValidationError(RestoreError):
    """Restore input or source set is unsafe."""


class RestoreInstancesActiveError(RestoreError):
    """Another local application instance is still active."""


@dataclass(frozen=True, slots=True)
class BackupFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class BackupSet:
    set_id: str
    created_at: str
    operation_id: str
    working: BackupFile
    archive: BackupFile
    directory: Path
    valid: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "set_id": self.set_id,
            "created_at": self.created_at,
            "operation_id": self.operation_id,
            "files": {
                "working": asdict(self.working),
                "archive": asdict(self.archive),
            },
            "valid": self.valid,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class BackupResult:
    working: Path
    archive: Path
    manifest: Path
    set_id: str


@dataclass(frozen=True, slots=True)
class IntegrityStatus:
    working: str
    archive: str
    write_blocked: bool
    message: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RestoreResult:
    set_id: str
    quarantine_id: str
    backup_created: bool
    warning: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _backup_directory(settings: Settings) -> Path:
    return settings.database_directory / BACKUP_DIRECTORY_NAME


def _write_block_path(settings: Settings) -> Path:
    return _backup_directory(settings) / WRITE_BLOCK_NAME


def _readonly_uri(path: Path) -> str:
    return f"{path.absolute().as_uri()}?mode=ro"


def _quick_check(path: Path) -> None:
    connection = sqlite3.connect(
        _readonly_uri(path), uri=True, timeout=15, isolation_level=None
    )
    try:
        rows = connection.execute("PRAGMA quick_check").fetchall()
        if len(rows) != 1 or str(rows[0][0]).lower() != "ok":
            raise sqlite3.DatabaseError("database failed quick_check")
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_info(path: Path) -> BackupFile:
    return BackupFile(path.name, path.stat().st_size, _sha256(path))


def _verify_file_against_manifest(path: Path, expected: BackupFile) -> None:
    try:
        if (
            not path.is_file()
            or path.stat().st_size != expected.size
            or _sha256(path) != expected.sha256
        ):
            raise BackupValidationError(
                "Размер или SHA-256 файла комплекта не совпадает."
            )
        _quick_check(path)
    except BackupValidationError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise BackupValidationError(
            "Файл комплекта не прошёл SQLite quick_check."
        ) from exc


def _backup_database(source: sqlite3.Connection, destination_path: Path, name: str) -> None:
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination, name=name)
    finally:
        destination.close()


def _copy_database_via_backup_api(source_path: Path, destination_path: Path) -> None:
    source = sqlite3.connect(_readonly_uri(source_path), uri=True, isolation_level=None)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _manifest_payload(
    *, set_id: str, created_at: str, operation_id: str,
    working: BackupFile, archive: BackupFile,
) -> dict[str, object]:
    return {
        "format_version": MANIFEST_VERSION,
        "set_id": set_id,
        "created_at": created_at,
        "operation_id": operation_id,
        "files": {"working": asdict(working), "archive": asdict(archive)},
    }


def _parse_file(raw: object, *, role: str) -> BackupFile:
    if not isinstance(raw, dict) or set(raw) != {"name", "size", "sha256"}:
        raise BackupValidationError(f"Неверная запись файла {role} в манифесте.")
    name, size, digest = raw["name"], raw["size"], raw["sha256"]
    if (
        not isinstance(name, str)
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        raise BackupValidationError(f"Неверные метаданные файла {role}.")
    return BackupFile(name, size, digest)


def verify_backup_set(
    directory: Path, settings: Settings, *, expected_set_id: str | None = None
) -> BackupSet:
    manifest_path = directory / MANIFEST_NAME
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupValidationError("Манифест комплекта отсутствует или повреждён.") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "format_version", "set_id", "created_at", "operation_id", "files"
    }:
        raise BackupValidationError("Манифест комплекта имеет неверную структуру.")
    if raw["format_version"] != MANIFEST_VERSION:
        raise BackupValidationError("Версия манифеста не поддерживается.")
    set_id, created_at, operation_id = raw["set_id"], raw["created_at"], raw["operation_id"]
    expected_directory_name = set_id if expected_set_id is None else f".{set_id}.tmp"
    if (
        not isinstance(set_id, str)
        or not SAFE_IDENTIFIER.fullmatch(set_id)
        or (expected_set_id is not None and expected_set_id != set_id)
        or directory.name != expected_directory_name
    ):
        raise BackupValidationError("Идентификатор комплекта не совпадает с каталогом.")
    if not isinstance(operation_id, str) or not SAFE_IDENTIFIER.fullmatch(operation_id):
        raise BackupValidationError("Идентификатор операции в манифесте повреждён.")
    try:
        parsed_at = datetime.fromisoformat(str(created_at))
    except (TypeError, ValueError) as exc:
        raise BackupValidationError("Дата комплекта в манифесте повреждена.") from exc
    if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
        raise BackupValidationError("Дата комплекта должна содержать часовой пояс.")
    files = raw["files"]
    if not isinstance(files, dict) or set(files) != {"working", "archive"}:
        raise BackupValidationError("Манифест должен описывать обе базы.")
    working = _parse_file(files["working"], role="working")
    archive = _parse_file(files["archive"], role="archive")
    if working.name != settings.working_database_name or archive.name != settings.archive_database_name:
        raise BackupValidationError("Имена баз в манифесте не совпадают с конфигурацией.")
    for info in (working, archive):
        _verify_file_against_manifest(directory / info.name, info)
    return BackupSet(set_id, str(created_at), operation_id, working, archive, directory)


def list_backup_sets(settings: Settings, *, include_invalid: bool = True) -> list[BackupSet]:
    directory = _backup_directory(settings)
    if not directory.is_dir():
        return []
    results: list[BackupSet] = []
    try:
        candidates = [path for path in directory.iterdir() if path.is_dir() and not path.name.startswith(".")]
    except OSError as exc:
        raise BackupNetworkError("Не удалось прочитать папку резервных копий.") from exc
    for path in candidates:
        try:
            results.append(verify_backup_set(path, settings))
        except BackupValidationError as exc:
            if include_invalid:
                empty = BackupFile("", 0, "")
                results.append(BackupSet(path.name, "", "", empty, empty, path, False, str(exc)))
    return sorted(results, key=lambda item: (item.created_at, item.set_id), reverse=True)


def has_valid_backup_for_operation(settings: Settings, operation_id: str) -> bool:
    return any(item.valid and item.operation_id == operation_id for item in list_backup_sets(settings))


def _rotate_complete_sets(settings: Settings, *, keep: int = 30) -> None:
    valid_sets = [item for item in list_backup_sets(settings, include_invalid=False) if item.valid]
    for item in valid_sets[keep:]:
        shutil.rmtree(item.directory)


def create_backup_pair(
    source: sqlite3.Connection,
    settings: Settings,
    *,
    operation_id: str,
    occurred_at: datetime,
) -> BackupResult:
    """Publish one verified directory containing both database snapshots."""

    if not isinstance(operation_id, str) or not SAFE_IDENTIFIER.fullmatch(operation_id):
        raise BackupValidationError("Неверный идентификатор операции резервного копирования.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise BackupValidationError("Дата резервной копии должна содержать часовой пояс.")
    backup_directory = _backup_directory(settings)
    try:
        backup_directory.mkdir(exist_ok=True)
    except OSError as exc:
        raise BackupNetworkError("Не удалось открыть папку резервных копий.") from exc
    created_at = occurred_at.astimezone(timezone.utc).isoformat(timespec="seconds")
    set_id = f"{occurred_at.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex}"
    temporary_directory = backup_directory / f".{set_id}.tmp"
    final_directory = backup_directory / set_id
    working_path = temporary_directory / settings.working_database_name
    archive_path = temporary_directory / settings.archive_database_name
    snapshot_started = False

    try:
        temporary_directory.mkdir()
        if source.in_transaction:
            raise sqlite3.OperationalError("backup source already has a transaction")
        source.execute("BEGIN")
        snapshot_started = True
        source.execute(
            "SELECT version FROM main.schema_version WHERE singleton = 1"
        ).fetchone()
        source.execute(
            "SELECT version FROM archive.schema_version WHERE singleton = 1"
        ).fetchone()
        _backup_database(source, working_path, "main")
        _backup_database(source, archive_path, "archive")
        _quick_check(working_path)
        _quick_check(archive_path)
        working = _file_info(working_path)
        archive = _file_info(archive_path)
        (temporary_directory / MANIFEST_NAME).write_text(
            json.dumps(
                _manifest_payload(
                    set_id=set_id, created_at=created_at, operation_id=operation_id,
                    working=working, archive=archive,
                ),
                ensure_ascii=False, sort_keys=True, indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        verify_backup_set(temporary_directory, settings, expected_set_id=set_id)
        # The directory rename is the single publication point for the complete set.
        os.replace(temporary_directory, final_directory)
        verified = verify_backup_set(final_directory, settings)
        _rotate_complete_sets(settings)
        return BackupResult(
            final_directory / verified.working.name,
            final_directory / verified.archive.name,
            final_directory / MANIFEST_NAME,
            set_id,
        )
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise BackupBusyError("База занята другим сотрудником; комплект не опубликован.") from exc
        raise BackupError("Не удалось создать комплект резервной копии.") from exc
    except (OSError, sqlite3.Error, BackupValidationError) as exc:
        if isinstance(exc, BackupValidationError):
            raise
        raise BackupNetworkError("Не удалось создать комплект резервной копии на сетевом диске.") from exc
    finally:
        if snapshot_started and source.in_transaction:
            source.rollback()
        if temporary_directory.exists():
            with suppress(OSError):
                shutil.rmtree(temporary_directory)


def _record_write_block(settings: Settings, *, working: str, archive: str, detected_at: datetime) -> None:
    directory = _backup_directory(settings)
    temporary: Path | None = None
    try:
        directory.mkdir(exist_ok=True)
        temporary = directory / f".{WRITE_BLOCK_NAME}.{uuid4().hex}.tmp"
        temporary.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "detected_at": detected_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
                    "working": working,
                    "archive": archive,
                },
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, _write_block_path(settings))
    except OSError:
        pass
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def check_active_integrity(settings: Settings, *, detected_at: datetime | None = None) -> IntegrityStatus:
    paths = validate_database_pair(settings)
    statuses: dict[str, str] = {}
    for role, path in (("working", paths.working), ("archive", paths.archive)):
        try:
            _quick_check(path)
        except sqlite3.OperationalError:
            statuses[role] = "unavailable"
        except sqlite3.DatabaseError:
            statuses[role] = "corrupt"
        except OSError:
            statuses[role] = "unavailable"
        else:
            statuses[role] = "ok"
    damaged = "corrupt" in statuses.values()
    marker = _write_block_path(settings)
    if damaged:
        _record_write_block(
            settings,
            working=statuses["working"],
            archive=statuses["archive"],
            detected_at=detected_at or datetime.now(timezone.utc),
        )
    blocked = damaged or marker.is_file()
    message = None
    if blocked:
        message = (
            "Обнаружено повреждение базы данных. Операции записи заблокированы; "
            "автоматическое восстановление не выполняется."
        )
    elif "unavailable" in statuses.values():
        message = "Не удалось проверить базы на сетевом диске."
    return IntegrityStatus(statuses["working"], statuses["archive"], blocked, message)


def assert_writes_allowed(settings: Settings) -> None:
    if _write_block_path(settings).is_file():
        raise DatabaseCorruptionError(
            "Операции записи заблокированы из-за обнаруженного повреждения базы. "
            "Откройте настройки резервных копий."
        )
    status = check_active_integrity(settings)
    if status.write_blocked:
        raise DatabaseCorruptionError(status.message or "Операции записи заблокированы.")


def _exclusive_pair_check(paths: DatabasePaths, settings: Settings) -> None:
    connection = sqlite3.connect(
        str(paths.working), timeout=settings.busy_timeout_ms / 1000, isolation_level=None
    )
    try:
        connection.execute(f"PRAGMA busy_timeout={int(settings.busy_timeout_ms)}")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA locking_mode=NORMAL")
        connection.execute("ATTACH DATABASE ? AS archive", (str(paths.archive),))
        connection.execute("PRAGMA archive.journal_mode=DELETE")
        connection.execute("PRAGMA archive.synchronous=FULL")
        connection.execute("PRAGMA archive.locking_mode=NORMAL")
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute("SELECT version FROM main.schema_version WHERE singleton = 1").fetchone()
        connection.execute("SELECT version FROM archive.schema_version WHERE singleton = 1").fetchone()
        connection.rollback()
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise RestoreError(
                "База занята. Закройте другие приложения и повторите восстановление."
            ) from exc
        # A damaged file may not be attachable; the shared maintenance lock and
        # instance markers still prevent application writes during replacement.
    except sqlite3.DatabaseError:
        pass
    finally:
        connection.close()


def restore_backup_set(
    settings: Settings,
    *,
    set_id: str,
    operation_id: str,
    confirmation: str,
    occurred_at: datetime,
    ensure_no_other_instances: Callable[[], int],
) -> RestoreResult:
    """Restore both databases only from one complete verified set."""

    if confirmation != RESTORE_CONFIRMATION:
        raise RestoreValidationError("Требуется явное подтверждение восстановления.")
    if not SAFE_IDENTIFIER.fullmatch(set_id or "") or not SAFE_IDENTIFIER.fullmatch(operation_id or ""):
        raise RestoreValidationError("Неверный идентификатор восстановления.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise RestoreValidationError("Дата восстановления должна содержать часовой пояс.")
    if not _write_block_path(settings).is_file():
        raise RestoreValidationError(
            "Восстановление разрешено только после подтверждённого повреждения базы."
        )
    backup_set = verify_backup_set(_backup_directory(settings) / set_id, settings)
    paths = validate_database_pair(settings)
    restore_id = f"{occurred_at.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex}"
    staged_working = paths.directory / f".{restore_id}.working.restore.tmp"
    staged_archive = paths.directory / f".{restore_id}.archive.restore.tmp"
    quarantine = paths.directory / QUARANTINE_DIRECTORY_NAME / restore_id
    moved_working = moved_archive = published_working = published_archive = False

    try:
        _copy_database_via_backup_api(backup_set.directory / backup_set.working.name, staged_working)
        _copy_database_via_backup_api(backup_set.directory / backup_set.archive.name, staged_archive)
        _verify_file_against_manifest(staged_working, backup_set.working)
        _verify_file_against_manifest(staged_archive, backup_set.archive)
        with maintenance_lock(settings):
            try:
                other_instances = ensure_no_other_instances()
            except InstanceCoordinationError as exc:
                raise RestoreInstancesActiveError(str(exc)) from exc
            if other_instances != 0:
                raise RestoreInstancesActiveError(
                    "Закройте приложение на других компьютерах перед восстановлением."
                )
            _exclusive_pair_check(paths, settings)
            quarantine.mkdir(parents=True)
            quarantined_working = quarantine / f"{paths.working.name}.damaged"
            quarantined_archive = quarantine / f"{paths.archive.name}.damaged"
            os.replace(paths.working, quarantined_working)
            moved_working = True
            os.replace(paths.archive, quarantined_archive)
            moved_archive = True
            os.replace(staged_working, paths.working)
            published_working = True
            os.replace(staged_archive, paths.archive)
            published_archive = True
            _quick_check(paths.working)
            _quick_check(paths.archive)
    except Exception:
        if moved_working or moved_archive:
            with suppress(OSError):
                if published_working:
                    paths.working.unlink(missing_ok=True)
                if published_archive:
                    paths.archive.unlink(missing_ok=True)
                if moved_working:
                    os.replace(quarantine / f"{paths.working.name}.damaged", paths.working)
                if moved_archive:
                    os.replace(quarantine / f"{paths.archive.name}.damaged", paths.archive)
        raise
    finally:
        staged_working.unlink(missing_ok=True)
        staged_archive.unlink(missing_ok=True)

    # The restored archive records only technical recovery metadata, never client data or secrets.
    backup_created = False
    warning: str | None = None
    connection = sqlite3.connect(str(paths.working), isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={int(settings.busy_timeout_ms)}")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA locking_mode=NORMAL")
        connection.execute("ATTACH DATABASE ? AS archive", (str(paths.archive),))
        connection.execute("PRAGMA archive.journal_mode=DELETE")
        connection.execute("PRAGMA archive.synchronous=FULL")
        connection.execute("PRAGMA archive.locking_mode=NORMAL")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO archive.log(
                   log_id, operation_id, occurred_at, employee, action,
                   contract_id, cell_number, changes_json
               ) VALUES(?, ?, ?, 'Администратор восстановления',
                        'admin.restore.completed', NULL, NULL, ?)""",
            (
                str(uuid4()), operation_id, occurred_at.isoformat(timespec="seconds"),
                json.dumps(
                    {"backup_set_id": set_id, "quarantine_id": restore_id},
                    sort_keys=True, separators=(",", ":"),
                ),
            ),
        )
        connection.commit()
        try:
            create_backup_pair(
                connection, settings, operation_id=operation_id, occurred_at=occurred_at
            )
            backup_created = True
        except BackupError:
            warning = (
                "Базы восстановлены и аудит сохранён, но новый контрольный комплект "
                "создать не удалось."
            )
    except Exception as exc:
        _record_write_block(
            settings, working="unknown", archive="unknown", detected_at=occurred_at
        )
        raise RestoreError(
            "Базы восстановлены, но аудит восстановления не подтверждён; запись заблокирована."
        ) from exc
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
    _write_block_path(settings).unlink(missing_ok=True)
    return RestoreResult(set_id, restore_id, backup_created, warning)


def read_recovery_auth(settings: Settings) -> dict[str, str | None]:
    """Read only administrative access data from the newest verified backup."""

    valid = [item for item in list_backup_sets(settings, include_invalid=False) if item.valid]
    if not valid:
        raise BackupValidationError("Нет проверенного комплекта для входа в режим восстановления.")
    working = valid[0].directory / valid[0].working.name
    connection = sqlite3.connect(_readonly_uri(working), uri=True)
    try:
        password = connection.execute(
            "SELECT password_hash FROM admin_credentials WHERE id = 1"
        ).fetchone()
        mode = connection.execute(
            "SELECT value FROM config WHERE key = 'admin_access_mode'"
        ).fetchone()
    finally:
        connection.close()
    password_hash = None if password is None else str(password[0])
    access_mode = (
        ("password" if password_hash is not None else "acknowledgement")
        if mode is None
        else str(mode[0])
    )
    if access_mode == "password" and password_hash is None:
        access_mode = "acknowledgement"
    return {
        "password_hash": password_hash,
        "access_mode": access_mode,
    }
