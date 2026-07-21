from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from http.client import HTTPConnection
import json
from pathlib import Path
import re
import socket
from threading import Event
import time

import pytest

from app import create_app
from app.config import Settings
from app.db.schema import initialize_databases
from app.runtime import (
    BrowserLifecycle,
    LOOPBACK_HOST,
    RuntimeValidationError,
    StartupError,
    default_config_path,
    load_startup_settings,
    run_portable,
)


VALID_TAB_ONE = "a" * 32
VALID_TAB_TWO = "b" * 32
TOKEN_PATTERN = re.compile(r'data-private-token="([^"]+)"')


def _prepare_runtime(
    tmp_path: Path,
    cells_csv_path: Path,
) -> tuple[Path, Settings]:
    database_directory = tmp_path / "shared"
    database_directory.mkdir()
    settings = Settings(database_directory=database_directory, testing=True)
    initialize_databases(settings, cells_csv_path=cells_csv_path)
    (database_directory / "templates").mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"database_directory": str(database_directory)}),
        encoding="utf-8",
    )
    return config_path, settings


def _wait_ready(path: Path, *, timeout: float = 5.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        time.sleep(0.02)
    raise AssertionError("local server did not publish its ready state")


def _request(
    state: dict[str, object],
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, object] | None = None,
) -> tuple[int, bytes]:
    connection = HTTPConnection(str(state["host"]), int(state["port"]), timeout=3)
    headers: dict[str, str] = {}
    body: bytes | None = None
    if token is not None:
        headers["X-Safe-Cells-Token"] = token
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _token(state: dict[str, object]) -> str:
    status, body = _request(state, "GET", "/")
    assert status == 200
    match = TOKEN_PATTERN.search(body.decode("utf-8"))
    assert match is not None
    return match.group(1)


def _shutdown(state: dict[str, object], token: str) -> None:
    status, _ = _request(state, "POST", "/api/runtime/shutdown", token=token)
    assert status == 200


def test_frozen_default_config_is_beside_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "portable" / "safe-cells.exe"
    monkeypatch.setattr("app.runtime.sys.frozen", True, raising=False)
    monkeypatch.setattr("app.runtime.sys.executable", str(executable))

    assert default_config_path() == executable.parent / "config.json"


def test_startup_requires_existing_pair_and_templates(
    tmp_path: Path, cells_csv_path: Path
) -> None:
    config_path, settings = _prepare_runtime(tmp_path, cells_csv_path)

    loaded = load_startup_settings(config_path)

    assert loaded.database_directory == settings.database_directory
    (settings.database_directory / "templates").rmdir()
    with pytest.raises(StartupError, match="templates"):
        load_startup_settings(config_path)


def test_startup_does_not_create_missing_shared_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing shared"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"database_directory": str(missing)}), encoding="utf-8"
    )

    with pytest.raises(StartupError, match="сетевого диска"):
        load_startup_settings(config_path)

    assert not missing.exists()


def test_invalid_tab_identifier_is_rejected() -> None:
    lifecycle = BrowserLifecycle()
    try:
        with pytest.raises(RuntimeValidationError):
            lifecycle.heartbeat("client name must never be a tab id")
    finally:
        lifecycle.close()


def test_reload_reconnect_cancels_pending_shutdown() -> None:
    stopped = Event()
    lifecycle = BrowserLifecycle(
        shutdown_grace_seconds=0.08,
        heartbeat_timeout_seconds=1.0,
    )
    lifecycle.set_shutdown_callback(stopped.set)

    lifecycle.heartbeat(VALID_TAB_ONE)
    lifecycle.disconnect(VALID_TAB_ONE)
    time.sleep(0.02)
    lifecycle.heartbeat(VALID_TAB_TWO)

    assert not stopped.wait(0.1)
    lifecycle.disconnect(VALID_TAB_TWO)
    assert stopped.wait(0.3)


def test_stale_tab_eventually_stops_its_server() -> None:
    stopped = Event()
    lifecycle = BrowserLifecycle(
        shutdown_grace_seconds=0.02,
        heartbeat_timeout_seconds=0.05,
    )
    lifecycle.set_shutdown_callback(stopped.set)

    lifecycle.heartbeat(VALID_TAB_ONE)

    assert stopped.wait(0.4)


def test_explicit_shutdown_cannot_be_cancelled_by_another_tab() -> None:
    stopped = Event()
    lifecycle = BrowserLifecycle(
        shutdown_grace_seconds=1,
        heartbeat_timeout_seconds=1,
    )
    lifecycle.set_shutdown_callback(stopped.set)
    lifecycle.heartbeat(VALID_TAB_ONE)

    lifecycle.request_shutdown()

    with pytest.raises(RuntimeValidationError, match="завершается"):
        lifecycle.heartbeat(VALID_TAB_TWO)
    assert stopped.wait(0.5)


def test_runtime_api_requires_own_instance_token(
    settings: Settings, cells_csv_path: Path
) -> None:
    initialize_databases(settings, cells_csv_path=cells_csv_path)
    lifecycle = BrowserLifecycle(shutdown_grace_seconds=1)
    app = create_app(settings, runtime_lifecycle=lifecycle)
    token = app.extensions["safe_cells_private_token"]
    client = app.test_client()
    try:
        assert 'data-runtime-enabled="true"' in client.get("/").get_data(as_text=True)
        assert client.post(
            "/api/runtime/heartbeat",
            json={"tab_id": VALID_TAB_ONE},
            headers={"X-Safe-Cells-Token": "wrong"},
        ).status_code == 403
        assert client.post(
            "/api/runtime/heartbeat",
            json={},
            headers={"X-Safe-Cells-Token": token},
        ).status_code == 400
        response = client.post(
            "/api/runtime/heartbeat",
            json={"tab_id": VALID_TAB_ONE},
            headers={"X-Safe-Cells-Token": token},
        )
        assert response.status_code == 200
        assert lifecycle.active_tab_count() == 1
        disconnected = client.post(
            "/api/runtime/disconnect",
            json={"tab_id": VALID_TAB_ONE, "token": token},
        )
        assert disconnected.status_code == 200
        assert token not in disconnected.get_data(as_text=True)
        assert lifecycle.active_tab_count() == 0
    finally:
        lifecycle.close()
        app.extensions["safe_cells_instance_coordinator"].close()


def test_three_loopback_instances_use_free_ports_and_stop_independently(
    tmp_path: Path, cells_csv_path: Path
) -> None:
    config_path, _settings = _prepare_runtime(tmp_path, cells_csv_path)
    ready_paths = [tmp_path / f"ready-{index}.json" for index in range(3)]
    futures: list[Future[int]] = []
    states: list[dict[str, object]] = []
    tokens: list[str] = []

    with socket.socket() as occupied:
        occupied.bind((LOOPBACK_HOST, 0))
        occupied.listen()
        occupied_port = occupied.getsockname()[1]

        with ThreadPoolExecutor(max_workers=3) as executor:
            try:
                for ready_path in ready_paths:
                    futures.append(
                        executor.submit(
                            run_portable,
                            config_path=config_path,
                            open_browser=False,
                            ready_file=ready_path,
                        )
                    )
                states = [_wait_ready(path) for path in ready_paths]
                tokens = [_token(state) for state in states]

                ports = {int(state["port"]) for state in states}
                assert len(ports) == 3
                assert occupied_port not in ports
                assert {state["host"] for state in states} == {LOOPBACK_HOST}
                for state in states:
                    status, payload = _request(state, "GET", "/health")
                    assert status == 200
                    assert json.loads(payload)["status"] == "ok"

                _shutdown(states[0], tokens[0])
                assert futures[0].result(timeout=5) == 0
                status, _ = _request(states[1], "GET", "/health")
                assert status == 200
            finally:
                for index in range(1, len(states)):
                    if not futures[index].done():
                        _shutdown(states[index], tokens[index])
                for future in futures:
                    assert future.result(timeout=5) == 0

    for ready_path in ready_paths:
        assert not ready_path.exists()
