"""Shared instance markers and a maintenance lock for controlled restore."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
from threading import Lock
import time
from typing import BinaryIO, Iterator
from uuid import uuid4
import weakref

from app.config import Settings


INSTANCE_DIRECTORY_NAME = ".safe_cells_instances"
MAINTENANCE_FILE_NAME = "maintenance.lock"
WRITE_FILE_NAME = "database-write.lock"
LOCK_INITIALIZATION_RETRY_SECONDS = 0.5
LOCK_INITIALIZATION_RETRY_INTERVAL_SECONDS = 0.01


class InstanceCoordinationError(RuntimeError):
    """The shared instance state cannot be checked safely."""


class MaintenanceActiveError(InstanceCoordinationError):
    """A controlled restore is currently in progress."""


def _lock_file(handle: BinaryIO, *, blocking: bool) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        msvcrt.locking(handle.fileno(), mode, 1)
        return

    import fcntl

    flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
    fcntl.flock(handle.fileno(), flags)


def _unlock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _open_lock(path: Path) -> BinaryIO:
    deadline = time.monotonic() + LOCK_INITIALIZATION_RETRY_SECONDS
    while True:
        handle = path.open("a+b")
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            return handle
        except OSError:
            handle.close()
            if time.monotonic() >= deadline:
                raise
            time.sleep(LOCK_INITIALIZATION_RETRY_INTERVAL_SECONDS)


@dataclass(frozen=True, slots=True)
class InstanceState:
    registered: bool
    other_active: int | None
    message: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "registered": self.registered,
            "other_active": self.other_active,
            "message": self.message,
        }


class InstanceCoordinator:
    """Hold one marker lock for the lifetime of a local Flask instance."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.directory = settings.database_directory / INSTANCE_DIRECTORY_NAME
        self.instance_id = str(uuid4())
        self.path = self.directory / f"instance_{self.instance_id}.lock"
        self._handle: BinaryIO | None = None
        self._error: str | None = None
        self._mutex = Lock()

    def start(self) -> None:
        with self._mutex:
            if self._handle is not None:
                return
            try:
                if not self.directory.parent.is_dir():
                    raise OSError("database directory is unavailable")
                ensure_maintenance_inactive(self.settings)
                self.directory.mkdir(exist_ok=True)
                handle = _open_lock(self.path)
                try:
                    _lock_file(handle, blocking=False)
                except Exception:
                    handle.close()
                    raise
                self._handle = handle
                self._error = None
            except (OSError, MaintenanceActiveError):
                self._error = (
                    "Не удалось зарегистрировать локальный экземпляр приложения. "
                    "Восстановление заблокировано."
                )

    def close(self) -> None:
        with self._mutex:
            handle, self._handle = self._handle, None
            if handle is None:
                return
            try:
                _unlock_file(handle)
            finally:
                handle.close()
                try:
                    self.path.unlink(missing_ok=True)
                except OSError:
                    pass

    def other_active_count(self) -> int:
        if self._handle is None:
            raise InstanceCoordinationError(
                self._error or "Локальный экземпляр приложения не зарегистрирован."
            )
        try:
            candidates = list(self.directory.glob("instance_*.lock"))
        except OSError as exc:
            raise InstanceCoordinationError(
                "Не удалось проверить другие экземпляры приложения."
            ) from exc
        active = 0
        for path in candidates:
            if path == self.path:
                continue
            handle: BinaryIO | None = None
            try:
                handle = _open_lock(path)
                _lock_file(handle, blocking=False)
            except OSError:
                active += 1
            else:
                _unlock_file(handle)
                handle.close()
                handle = None
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            finally:
                if handle is not None:
                    handle.close()
        return active

    def state(self) -> InstanceState:
        if self._handle is None:
            return InstanceState(False, None, self._error)
        try:
            return InstanceState(True, self.other_active_count(), None)
        except InstanceCoordinationError as exc:
            return InstanceState(True, None, str(exc))


def attach_instance_coordinator(app, settings: Settings) -> InstanceCoordinator:
    coordinator = InstanceCoordinator(settings)
    coordinator.start()
    app.extensions["safe_cells_instance_coordinator"] = coordinator
    weakref.finalize(app, coordinator.close)
    return coordinator


@contextmanager
def maintenance_lock(settings: Settings) -> Iterator[None]:
    directory = settings.database_directory / INSTANCE_DIRECTORY_NAME
    try:
        directory.mkdir(exist_ok=True)
        handle = _open_lock(directory / MAINTENANCE_FILE_NAME)
        _lock_file(handle, blocking=False)
    except OSError as exc:
        if "handle" in locals():
            handle.close()
        raise MaintenanceActiveError(
            "Другая операция восстановления уже выполняется."
        ) from exc
    try:
        yield
    finally:
        _unlock_file(handle)
        handle.close()


def ensure_maintenance_inactive(settings: Settings) -> None:
    directory = settings.database_directory / INSTANCE_DIRECTORY_NAME
    path = directory / MAINTENANCE_FILE_NAME
    if not path.exists():
        return
    handle: BinaryIO | None = None
    try:
        handle = _open_lock(path)
        _lock_file(handle, blocking=False)
    except OSError as exc:
        raise MaintenanceActiveError(
            "Выполняется контролируемое восстановление. Запись временно заблокирована."
        ) from exc
    else:
        _unlock_file(handle)
    finally:
        if handle is not None:
            handle.close()


@contextmanager
def application_write_lock(settings: Settings) -> Iterator[None]:
    """Serialize application writes and two-file snapshots across local instances."""

    directory = settings.database_directory / INSTANCE_DIRECTORY_NAME
    try:
        directory.mkdir(exist_ok=True)
        handle = _open_lock(directory / WRITE_FILE_NAME)
    except OSError as exc:
        raise InstanceCoordinationError(
            "Не удалось открыть общую блокировку записи."
        ) from exc
    deadline = time.monotonic() + settings.busy_timeout_ms / 1000
    while True:
        try:
            _lock_file(handle, blocking=False)
            break
        except OSError as exc:
            if time.monotonic() >= deadline:
                handle.close()
                raise InstanceCoordinationError(
                    "База сейчас занята другим сотрудником. Повторите позже."
                ) from exc
            time.sleep(0.05)
    try:
        yield
    finally:
        _unlock_file(handle)
        handle.close()
