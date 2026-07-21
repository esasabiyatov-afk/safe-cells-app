"""Portable loopback launcher and browser-tab lifecycle management."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from threading import Lock, Timer
import time
from typing import Callable, Sequence
import webbrowser

from werkzeug.serving import BaseWSGIServer, make_server

from app import create_app
from app.config import ConfigError, Settings, load_settings
from app.db.connections import (
    DatabaseUnavailableError,
    check_database_pair,
    validate_database_pair,
)
from app.db.schema import SCHEMA_VERSION
from app.services.backups import check_active_integrity


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_SHUTDOWN_GRACE_SECONDS = 5.0
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 35.0
TAB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


class RuntimeValidationError(ValueError):
    """A browser lifecycle request is malformed or unavailable."""


class StartupError(RuntimeError):
    """The portable application cannot start safely."""


@dataclass(frozen=True, slots=True)
class RuntimeReadyState:
    pid: int
    host: str
    port: int

    def to_dict(self) -> dict[str, object]:
        return {"pid": self.pid, "host": self.host, "port": self.port}


class BrowserLifecycle:
    """Track this process' browser tabs and stop only this local server."""

    def __init__(
        self,
        *,
        shutdown_grace_seconds: float = DEFAULT_SHUTDOWN_GRACE_SECONDS,
        heartbeat_timeout_seconds: float = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if shutdown_grace_seconds < 0:
            raise ValueError("shutdown_grace_seconds must not be negative")
        if heartbeat_timeout_seconds <= 0:
            raise ValueError("heartbeat_timeout_seconds must be positive")
        self.shutdown_grace_seconds = shutdown_grace_seconds
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._monotonic = monotonic
        self._tabs: dict[str, float] = {}
        self._shutdown_callback: Callable[[], None] | None = None
        self._shutdown_timer: Timer | None = None
        self._watchdog_timer: Timer | None = None
        self._ever_connected = False
        self._shutdown_requested = False
        self._closed = False
        self._mutex = Lock()

    @staticmethod
    def validate_tab_id(tab_id: object) -> str:
        if not isinstance(tab_id, str) or not TAB_ID_PATTERN.fullmatch(tab_id):
            raise RuntimeValidationError("Идентификатор вкладки передан неверно.")
        return tab_id

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        with self._mutex:
            self._shutdown_callback = callback

    def heartbeat(self, tab_id: object) -> None:
        valid_tab_id = self.validate_tab_id(tab_id)
        with self._mutex:
            if self._closed or self._shutdown_requested:
                raise RuntimeValidationError("Локальный экземпляр уже завершается.")
            self._ever_connected = True
            self._tabs[valid_tab_id] = self._monotonic()
            self._cancel_shutdown_locked()
            self._schedule_watchdog_locked()

    def disconnect(self, tab_id: object) -> None:
        valid_tab_id = self.validate_tab_id(tab_id)
        with self._mutex:
            if self._closed or self._shutdown_requested:
                return
            self._tabs.pop(valid_tab_id, None)
            self._schedule_watchdog_locked()
            if self._ever_connected and not self._tabs:
                self._schedule_shutdown_locked()

    def request_shutdown(self) -> None:
        """Schedule an explicit exit after the HTTP response can be returned."""

        with self._mutex:
            if self._closed:
                return
            self._shutdown_requested = True
            self._tabs.clear()
            self._cancel_watchdog_locked()
            self._cancel_shutdown_locked()
            self._shutdown_timer = self._new_timer(0.15, self._finish_shutdown)

    def active_tab_count(self) -> int:
        with self._mutex:
            return len(self._tabs)

    def close(self) -> None:
        with self._mutex:
            self._closed = True
            self._tabs.clear()
            self._cancel_shutdown_locked()
            self._cancel_watchdog_locked()

    def _new_timer(self, delay: float, callback: Callable[[], None]) -> Timer:
        timer = Timer(delay, callback)
        timer.daemon = True
        timer.start()
        return timer

    def _cancel_shutdown_locked(self) -> None:
        if self._shutdown_timer is not None:
            self._shutdown_timer.cancel()
            self._shutdown_timer = None

    def _cancel_watchdog_locked(self) -> None:
        if self._watchdog_timer is not None:
            self._watchdog_timer.cancel()
            self._watchdog_timer = None

    def _schedule_watchdog_locked(self) -> None:
        self._cancel_watchdog_locked()
        if not self._tabs:
            return
        oldest = min(self._tabs.values())
        delay = max(
            0.05,
            oldest + self.heartbeat_timeout_seconds - self._monotonic(),
        )
        self._watchdog_timer = self._new_timer(delay, self._expire_stale_tabs)

    def _expire_stale_tabs(self) -> None:
        with self._mutex:
            if self._closed:
                return
            self._watchdog_timer = None
            cutoff = self._monotonic() - self.heartbeat_timeout_seconds
            self._tabs = {
                tab_id: last_seen
                for tab_id, last_seen in self._tabs.items()
                if last_seen > cutoff
            }
            if self._tabs:
                self._schedule_watchdog_locked()
            elif self._ever_connected:
                self._schedule_shutdown_locked()

    def _schedule_shutdown_locked(self) -> None:
        self._cancel_shutdown_locked()
        self._shutdown_timer = self._new_timer(
            self.shutdown_grace_seconds,
            self._finish_shutdown,
        )

    def _finish_shutdown(self) -> None:
        callback: Callable[[], None] | None
        with self._mutex:
            self._shutdown_timer = None
            if self._closed or (self._tabs and not self._shutdown_requested):
                return
            self._closed = True
            self._cancel_watchdog_locked()
            callback = self._shutdown_callback
        if callback is not None:
            callback()


def default_config_path() -> Path:
    """Use a portable config beside the EXE and a local config in source mode."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config.json"
    return Path.cwd() / "config.local.json"


def load_startup_settings(config_path: Path) -> Settings:
    """Validate configured shared resources without creating replacements."""

    try:
        settings = load_settings(config_path)
        validate_database_pair(settings)
        template_directory = settings.database_directory / "templates"
        if not template_directory.is_dir():
            raise ConfigError(
                "В общей папке не найден каталог templates с утверждёнными шаблонами."
            )
        integrity = check_active_integrity(settings)
        if "unavailable" in {integrity.working, integrity.archive}:
            raise DatabaseUnavailableError(
                "Не удалось получить данные с сетевого диска. Проверьте подключение к сети"
            )
        if "corrupt" not in {integrity.working, integrity.archive}:
            versions = check_database_pair(settings)
            if set(versions.values()) != {SCHEMA_VERSION}:
                raise ConfigError(
                    "Версия баз требует явного административного обновления."
                )
    except (ConfigError, DatabaseUnavailableError) as exc:
        raise StartupError(str(exc)) from exc
    except OSError as exc:
        raise StartupError(
            "Не удалось получить данные с сетевого диска. Проверьте подключение к сети"
        ) from exc
    return settings


def _write_ready_file(path: Path, state: RuntimeReadyState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(state.to_dict(), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _show_message(title: str, message: str, *, error: bool) -> None:
    if os.name == "nt":
        import ctypes

        style = 0x00000010 if error else 0x00000040
        ctypes.windll.user32.MessageBoxW(None, message, title, style)
        return
    print(f"{title}: {message}", file=sys.stderr)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("порт должен быть целым числом") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("порт должен быть от 0 до 65535")
    return port


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Сейфовые ячейки")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Путь к локальному JSON-файлу конфигурации.",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=0,
        help="Локальный порт; 0 означает автоматический выбор свободного порта.",
    )
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ready-file", type=Path, default=None, help=argparse.SUPPRESS)
    return parser


def run_portable(
    *,
    config_path: Path,
    port: int = 0,
    open_browser: bool = True,
    ready_file: Path | None = None,
    browser_opener: Callable[[str], bool] = webbrowser.open,
    server_factory: Callable[..., BaseWSGIServer] = make_server,
) -> int:
    settings = load_startup_settings(config_path)
    lifecycle = BrowserLifecycle()
    app = create_app(settings, runtime_lifecycle=lifecycle)
    server = server_factory(LOOPBACK_HOST, port, app, threaded=True)
    lifecycle.set_shutdown_callback(server.shutdown)
    state = RuntimeReadyState(os.getpid(), LOOPBACK_HOST, int(server.server_port))
    url = f"http://{state.host}:{state.port}/"
    coordinator = app.extensions["safe_cells_instance_coordinator"]

    try:
        if ready_file is not None:
            _write_ready_file(ready_file, state)
        if open_browser and not browser_opener(url):
            _show_message(
                "Сейфовые ячейки",
                f"Браузер не открылся автоматически. Откройте адрес {url}",
                error=False,
            )
        server.serve_forever()
    finally:
        lifecycle.close()
        coordinator.close()
        server.server_close()
        if ready_file is not None:
            try:
                ready_file.unlink(missing_ok=True)
            except OSError:
                pass
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    config_path = args.config if args.config is not None else default_config_path()
    try:
        return run_portable(
            config_path=config_path,
            port=args.port,
            open_browser=not args.no_browser,
            ready_file=args.ready_file,
        )
    except StartupError as exc:
        _show_message("Сейфовые ячейки — ошибка запуска", str(exc), error=True)
        return 2
    except OSError:
        _show_message(
            "Сейфовые ячейки — ошибка запуска",
            "Не удалось запустить локальное приложение. Перезапустите ярлык или обратитесь к администратору.",
            error=True,
        )
        return 3
