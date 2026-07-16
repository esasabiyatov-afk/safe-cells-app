from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from threading import Event
import time
from uuid import uuid4

import pytest

from app import create_app
from app.config import Settings
from app.db.connections import DatabaseCorruptionError, open_readonly, open_write
from app.services import backups
from app.services.backups import (
    BackupBusyError,
    BackupNetworkError,
    BackupValidationError,
    RESTORE_CONFIRMATION,
    RestoreInstancesActiveError,
    check_active_integrity,
    create_backup_pair,
    list_backup_sets,
    restore_backup_set,
    verify_backup_set,
)
from app.services.instances import InstanceCoordinator


OCCURRED_AT = datetime(2026, 7, 16, 9, 0, tzinfo=timezone(timedelta(hours=6)))


def _create_set(settings: Settings, *, occurred_at: datetime = OCCURRED_AT):
    operation_id = str(uuid4())
    with open_write(settings, attach_archive=True) as connection:
        result = create_backup_pair(
            connection,
            settings,
            operation_id=operation_id,
            occurred_at=occurred_at,
        )
    return operation_id, result


def _corrupt(path: Path) -> None:
    path.write_bytes(b"TEST-DAMAGED-SQLITE")


def test_successful_two_database_set_has_verified_manifest(
    settings: Settings, initialized_databases,
) -> None:
    operation_id, result = _create_set(settings)

    item = verify_backup_set(result.manifest.parent, settings)
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))

    assert item.valid is True
    assert item.operation_id == operation_id
    assert result.working.is_file() and result.archive.is_file()
    assert manifest["files"]["working"]["size"] == result.working.stat().st_size
    assert len(manifest["files"]["working"]["sha256"]) == 64
    assert len(manifest["files"]["archive"]["sha256"]) == 64
    assert not list((settings.database_directory / "backups").glob(".*.tmp"))


def test_failure_between_two_copies_publishes_nothing(
    settings: Settings, initialized_databases, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = backups._backup_database
    calls = 0

    def fail_second(source, destination, name):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated network interruption")
        original(source, destination, name)

    monkeypatch.setattr(backups, "_backup_database", fail_second)
    with open_write(settings, attach_archive=True) as connection:
        with pytest.raises(BackupNetworkError):
            create_backup_pair(
                connection, settings,
                operation_id=str(uuid4()), occurred_at=OCCURRED_AT,
            )

    assert list_backup_sets(settings) == []
    backup_dir = settings.database_directory / "backups"
    assert not [item for item in backup_dir.iterdir() if item.is_dir()]


def test_locked_copy_is_clear_and_not_published(
    settings: Settings, initialized_databases, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backups,
        "_backup_database",
        lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )
    with open_write(settings, attach_archive=True) as connection:
        with pytest.raises(BackupBusyError, match="занята"):
            create_backup_pair(
                connection, settings,
                operation_id=str(uuid4()), occurred_at=OCCURRED_AT,
            )
    assert list_backup_sets(settings) == []


@pytest.mark.parametrize("tamper", ["database", "manifest"])
def test_damaged_copy_or_wrong_sha_is_never_valid(
    settings: Settings, initialized_databases, tamper: str,
) -> None:
    _, result = _create_set(settings)
    if tamper == "database":
        with result.working.open("ab") as output:
            output.write(b"changed")
    else:
        manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
        manifest["files"]["archive"]["sha256"] = "0" * 64
        result.manifest.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupValidationError):
        verify_backup_set(result.manifest.parent, settings)
    listed = list_backup_sets(settings)
    assert len(listed) == 1 and listed[0].valid is False


def test_rotation_keeps_latest_thirty_complete_sets_only(
    settings: Settings, initialized_databases,
) -> None:
    for index in range(31):
        _create_set(settings, occurred_at=OCCURRED_AT + timedelta(seconds=index))

    complete = [item for item in list_backup_sets(settings) if item.valid]
    assert len(complete) == 30
    assert complete[0].created_at > complete[-1].created_at
    assert all((item.directory / "manifest.json").is_file() for item in complete)


def test_unavailable_backup_path_does_not_create_local_replacement(tmp_path: Path) -> None:
    missing = tmp_path / "missing network directory"
    settings = Settings(database_directory=missing, testing=True)
    source = sqlite3.connect(":memory:", isolation_level=None)
    source.execute("CREATE TABLE schema_version(singleton INTEGER, version INTEGER)")
    source.execute("INSERT INTO schema_version VALUES(1, 3)")
    source.execute("ATTACH DATABASE ':memory:' AS archive")
    source.execute("CREATE TABLE archive.schema_version(singleton INTEGER, version INTEGER)")
    source.execute("INSERT INTO archive.schema_version VALUES(1, 3)")
    try:
        with pytest.raises(BackupNetworkError):
            create_backup_pair(
                source, settings,
                operation_id=str(uuid4()), occurred_at=OCCURRED_AT,
            )
    finally:
        source.close()
    assert not missing.exists()


def test_concurrent_application_write_waits_until_both_snapshots_are_complete(
    settings: Settings, initialized_databases, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_copy_ready = Event()
    release_backup = Event()
    writer_finished = Event()
    original = backups._backup_database

    def paused_copy(source, destination, name):
        original(source, destination, name)
        if name == "main":
            first_copy_ready.set()
            assert release_backup.wait(5)

    monkeypatch.setattr(backups, "_backup_database", paused_copy)

    def backup_job():
        return _create_set(settings)[1]

    def writer_job():
        assert first_copy_ready.wait(5)
        with open_write(settings, attach_archive=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO config(key, value, updated_at, updated_by)
                   VALUES('concurrent_test', 'after', ?, 'test')""",
                (OCCURRED_AT.isoformat(),),
            )
            connection.execute(
                """INSERT INTO archive.log(
                       log_id, operation_id, occurred_at, employee, action,
                       contract_id, cell_number, changes_json
                   ) VALUES(?, ?, ?, 'test', 'test.concurrent', NULL, NULL, '{}')""",
                (str(uuid4()), str(uuid4()), OCCURRED_AT.isoformat()),
            )
            connection.commit()
        writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        backup_future = pool.submit(backup_job)
        writer_future = pool.submit(writer_job)
        assert first_copy_ready.wait(5)
        time.sleep(0.1)
        assert writer_finished.is_set() is False
        release_backup.set()
        result = backup_future.result(timeout=10)
        writer_future.result(timeout=10)

    with open_readonly(result.working) as connection:
        assert connection.execute(
            "SELECT 1 FROM config WHERE key='concurrent_test'"
        ).fetchone() is None
    with open_readonly(result.archive) as connection:
        assert connection.execute(
            "SELECT 1 FROM log WHERE action='test.concurrent'"
        ).fetchone() is None


def test_corruption_creates_persistent_write_block(
    settings: Settings, initialized_databases,
) -> None:
    _corrupt(settings.database_directory / settings.archive_database_name)

    status = check_active_integrity(settings, detected_at=OCCURRED_AT)
    assert status.archive == "corrupt"
    assert status.write_blocked is True
    with pytest.raises(DatabaseCorruptionError, match="заблокированы"):
        with open_write(settings):
            pass
    assert (settings.database_directory / "backups" / "write-block.json").is_file()


def test_restore_uses_one_verified_set_and_preserves_damaged_originals(
    settings: Settings, initialized_databases,
) -> None:
    _, result = _create_set(settings)
    active_archive = settings.database_directory / settings.archive_database_name
    _corrupt(active_archive)
    check_active_integrity(settings, detected_at=OCCURRED_AT)
    coordinator = InstanceCoordinator(settings)
    coordinator.start()
    operation_id = str(uuid4())
    try:
        restored = restore_backup_set(
            settings,
            set_id=result.set_id,
            operation_id=operation_id,
            confirmation=RESTORE_CONFIRMATION,
            occurred_at=OCCURRED_AT + timedelta(minutes=1),
            ensure_no_other_instances=coordinator.other_active_count,
        )
    finally:
        coordinator.close()

    assert restored.backup_created is True
    quarantine = (
        settings.database_directory / "damaged-originals" / restored.quarantine_id
    )
    assert (quarantine / f"{settings.working_database_name}.damaged").is_file()
    assert (quarantine / f"{settings.archive_database_name}.damaged").read_bytes() == b"TEST-DAMAGED-SQLITE"
    assert not (settings.database_directory / "backups" / "write-block.json").exists()
    with open_readonly(active_archive) as connection:
        audit = connection.execute(
            "SELECT employee, changes_json FROM log WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
    assert audit["employee"] == "Администратор восстановления"
    assert json.loads(audit["changes_json"]) == {
        "backup_set_id": result.set_id,
        "quarantine_id": restored.quarantine_id,
    }


def test_restore_rejects_invalid_set_before_touching_active_files(
    settings: Settings, initialized_databases,
) -> None:
    _, result = _create_set(settings)
    _corrupt(result.archive)
    active_archive = settings.database_directory / settings.archive_database_name
    _corrupt(active_archive)
    check_active_integrity(settings, detected_at=OCCURRED_AT)
    before = active_archive.read_bytes()
    coordinator = InstanceCoordinator(settings)
    coordinator.start()
    try:
        with pytest.raises(BackupValidationError):
            restore_backup_set(
                settings,
                set_id=result.set_id,
                operation_id=str(uuid4()),
                confirmation=RESTORE_CONFIRMATION,
                occurred_at=OCCURRED_AT,
                ensure_no_other_instances=coordinator.other_active_count,
            )
    finally:
        coordinator.close()
    assert active_archive.read_bytes() == before


def test_restore_is_forbidden_while_another_instance_is_active(
    settings: Settings, initialized_databases,
) -> None:
    _, result = _create_set(settings)
    _corrupt(settings.database_directory / settings.archive_database_name)
    check_active_integrity(settings, detected_at=OCCURRED_AT)
    current = InstanceCoordinator(settings)
    other = InstanceCoordinator(settings)
    current.start()
    other.start()
    try:
        with pytest.raises(RestoreInstancesActiveError, match="других компьютерах"):
            restore_backup_set(
                settings,
                set_id=result.set_id,
                operation_id=str(uuid4()),
                confirmation=RESTORE_CONFIRMATION,
                occurred_at=OCCURRED_AT,
                ensure_no_other_instances=current.other_active_count,
            )
    finally:
        other.close()
        current.close()


def test_manifest_and_restore_audit_contain_no_client_data_password_or_path(
    settings: Settings, initialized_databases,
) -> None:
    operation_id, result = _create_set(settings)
    text = result.manifest.read_text(encoding="utf-8")
    for marker in (
        "TEST-CLIENT-SECRET", "TEST-ID-SECRET", "TEST-ACCOUNT-SECRET",
        "TestAdmin-Secret", str(settings.database_directory),
    ):
        assert marker not in text
    assert operation_id in text


def test_active_databases_are_never_copied_or_replaced_during_normal_backup() -> None:
    source = Path(backups.__file__).read_text(encoding="utf-8")
    assert "shutil.copy" not in source
    create_source = source.split("def create_backup_pair", 1)[1].split(
        "def _record_write_block", 1
    )[0]
    assert "os.replace(paths.working" not in create_source
    assert "os.replace(paths.archive" not in create_source


def test_admin_can_view_integrity_and_restore_only_after_explicit_confirmation(
    settings: Settings, initialized_databases,
) -> None:
    app = create_app(settings)
    app.config.update(
        EMPLOYEE_PROVIDER=lambda: "test-admin",
        TIMESTAMP_PROVIDER=lambda: OCCURRED_AT,
    )
    client = app.test_client()
    setup = client.post(
        "/api/admin/setup",
        json={
            "operation_id": str(uuid4()),
            "password": "TestAdmin-Backup-2026",
            "password_confirmation": "TestAdmin-Backup-2026",
        },
    )
    token = setup.get_json()["token"]
    headers = {"X-Safe-Cells-Admin-Token": token}
    assert client.get("/api/admin/backups").status_code == 401

    active_archive = settings.database_directory / settings.archive_database_name
    _corrupt(active_archive)
    status = client.get("/api/admin/backups", headers=headers)
    assert status.status_code == 200
    payload = status.get_json()
    assert payload["integrity"]["write_blocked"] is True
    assert payload["restore_allowed"] is True
    set_id = next(item["set_id"] for item in payload["sets"] if item["valid"])

    denied = client.post(
        "/api/admin/backups/restore",
        headers=headers,
        json={
            "operation_id": str(uuid4()),
            "set_id": set_id,
            "confirmation": "нет",
        },
    )
    assert denied.status_code == 400
    restored = client.post(
        "/api/admin/backups/restore",
        headers=headers,
        json={
            "operation_id": str(uuid4()),
            "set_id": set_id,
            "confirmation": RESTORE_CONFIRMATION,
        },
    )
    assert restored.status_code == 200
    assert restored.get_json()["backup_created"] is True
