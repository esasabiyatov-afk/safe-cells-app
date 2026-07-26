"""Launch the copied EXE in an isolated folder and verify its local HTTP flow."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.db.connections import open_write
from app.db.schema import initialize_databases
from app.services.backups import list_backup_sets
from app.services.employee import EmployeeRecord, EMPLOYEES_CONFIG_KEY, encode_employee_config
from docx import Document


TOKEN_PATTERN = re.compile(r'data-private-token="([^"]+)"')


def _assert_gui_subsystem(executable: Path) -> None:
    with executable.open("rb") as handle:
        if handle.read(2) != b"MZ":
            raise RuntimeError("Собранный файл не является Windows EXE.")
        handle.seek(0x3C)
        pe_offset = struct.unpack("<I", handle.read(4))[0]
        handle.seek(pe_offset)
        if handle.read(4) != b"PE\0\0":
            raise RuntimeError("У собранного файла неверный PE-заголовок.")
        handle.seek(20, 1)
        optional_header = handle.tell()
        handle.seek(optional_header + 68)
        subsystem = struct.unpack("<H", handle.read(2))[0]
    if subsystem != 2:
        raise RuntimeError("EXE собран как консольное, а не оконное приложение.")


def _wait_ready(path: Path, process: subprocess.Popen[bytes]) -> dict[str, object]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        if process.poll() is not None:
            raise RuntimeError(f"EXE завершился до запуска HTTP: код {process.returncode}")
        time.sleep(0.1)
    raise RuntimeError("EXE не запустил локальный HTTP за 60 секунд.")


def _request(
    state: dict[str, object],
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, object] | None = None,
) -> tuple[int, bytes]:
    connection = HTTPConnection(str(state["host"]), int(state["port"]), timeout=5)
    headers: dict[str, str] = {"X-Safe-Cells-Token": token} if token else {}
    body: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exe",
        type=Path,
        default=PROJECT_ROOT / "dist" / "safe-cells-portable" / "safe-cells.exe",
    )
    args = parser.parse_args()
    executable = args.exe.resolve()
    if not executable.is_file():
        parser.error("safe-cells.exe не найден; сначала выполните build_portable.ps1")
    _assert_gui_subsystem(executable)

    with tempfile.TemporaryDirectory(
        prefix="safe-cells-stage12-", ignore_cleanup_errors=True
    ) as temporary:
        root = Path(temporary)
        portable = root / "portable"
        shared = root / "shared"
        portable.mkdir()
        shared.mkdir()
        copied_executable = portable / "safe-cells.exe"
        shutil.copy2(executable, copied_executable)

        settings = Settings(database_directory=shared, testing=True)
        initialize_databases(
            settings,
            cells_csv_path=PROJECT_ROOT / "data" / "cell_heights.csv",
        )
        templates = shared / "templates"
        templates.mkdir()
        template = Document()
        template.add_paragraph("ТЕСТОВЫЙ ДОКУМЕНТ: [Сейф.Номер]")
        template.save(templates / "portable-opening.docx")
        employee = EmployeeRecord(str(uuid4()), "Тестов Иван", True)
        with open_write(settings) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE config SET value = ? WHERE key = ?",
                (encode_employee_config([employee]), EMPLOYEES_CONFIG_KEY),
            )
            connection.execute(
                "INSERT INTO document_templates VALUES(?, 'opening', ?, ?, ?, 1, ?, ?)",
                (
                    "portable-opening",
                    "ТЕСТОВЫЙ ДОКУМЕНТ",
                    "portable-opening.docx",
                    json.dumps(["Сейф.Номер"], ensure_ascii=False),
                    "2026-07-01T09:00:00+06:00",
                    "test-setup",
                ),
            )
            connection.commit()
        (portable / "config.json").write_text(
            json.dumps({"database_directory": str(shared)}),
            encoding="utf-8",
        )
        ready_file = root / "ready.json"

        environment = os.environ.copy()
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        system_root = Path(environment.get("SystemRoot", r"C:\Windows"))
        environment["PATH"] = os.pathsep.join(
            [str(system_root / "System32"), str(system_root)]
        )
        environment["PYTHONNOUSERSITE"] = "1"
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        state: dict[str, object] | None = None
        token: str | None = None
        process = subprocess.Popen(
            [
                str(copied_executable),
                "--no-browser",
                "--ready-file",
                str(ready_file),
            ],
            cwd=portable,
            env=environment,
            creationflags=creation_flags,
        )
        try:
            state = _wait_ready(ready_file, process)
            if state.get("host") != "127.0.0.1":
                raise RuntimeError("EXE слушает не loopback-интерфейс.")
            if set(state) != {"host", "pid", "port"}:
                raise RuntimeError("Файл готовности содержит лишние или секретные данные.")
            status, health = _request(state, "GET", "/health")
            if status != 200 or json.loads(health).get("status") != "ok":
                raise RuntimeError("Проверка /health собранного EXE не прошла.")
            status, page = _request(state, "GET", "/")
            html = page.decode("utf-8")
            if status != 200 or "http://" in html or "https://" in html:
                raise RuntimeError("Главная страница содержит внешний ресурс или недоступна.")
            token_match = TOKEN_PATTERN.search(html)
            if token_match is None:
                raise RuntimeError("В HTML отсутствует токен локального экземпляра.")
            token = token_match.group(1)

            status, employees = _request(state, "GET", "/api/employee")
            if status != 200 or len(json.loads(employees)["employees"]) != 1:
                raise RuntimeError("Справочник сотрудников в EXE недоступен.")
            status, _ = _request(
                state,
                "POST",
                "/api/employee/select",
                token=token,
                payload={"employee_id": employee.employee_id},
            )
            if status != 200:
                raise RuntimeError("EXE не сохранил локальный выбор сотрудника.")

            today = date.today()
            initial_end = today + timedelta(days=1)
            status, quote = _request(
                state,
                "POST",
                "/api/rental/calculate",
                payload={
                    "cell_number": "1",
                    "start_date": today.isoformat(),
                    "end_date": initial_end.isoformat(),
                    "rent_days": 2,
                },
            )
            if status != 200 or json.loads(quote)["rent_days"] != 2:
                raise RuntimeError("Калькулятор аренды в EXE не работает.")

            status, opened = _request(
                state,
                "POST",
                "/api/contracts",
                payload={
                    "operation_id": str(uuid4()),
                    "cell_number": "1",
                    "client_full_name": "Тестовый Клиент Portable",
                    "client_phone": "+996 (555) 000-001",
                    "id_card_number": "TEST-ID-PORTABLE",
                    "id_card_issuer": "Тестовый орган",
                    "id_card_issue_date": "2017-09-12",
                    "account_number": "TEST-ACCOUNT-PORTABLE",
                    "start_date": today.isoformat(),
                    "end_date": initial_end.isoformat(),
                    "rent_days": 2,
                },
            )
            opened_payload = json.loads(opened)
            if status != 201 or len(opened_payload.get("documents", [])) != 1:
                raise RuntimeError("Открытие договора или DOCX в EXE не работает.")
            contract_ref = opened_payload["contract_id"]
            document_info = opened_payload["documents"][0]
            status, generated_docx = _request(
                state,
                "POST",
                "/api/documents/download",
                token=token,
                payload={"download_id": document_info["download_id"]},
            )
            if status != 200 or not generated_docx.startswith(b"PK"):
                raise RuntimeError("EXE не выдал сформированный DOCX через браузер.")

            renewed_end = initial_end + timedelta(days=5)
            renewal_payload = {
                "operation_id": str(uuid4()),
                "cell_number": "1",
                "contract_ref": contract_ref,
                "expected_end_date": initial_end.isoformat(),
                "new_end_date": renewed_end.isoformat(),
                "renewal_days": 5,
            }
            status, renewal = _request(
                state,
                "POST",
                "/api/renewals",
                payload=renewal_payload,
            )
            if status != 201 or json.loads(renewal)["new_end_date"] != renewed_end.isoformat():
                raise RuntimeError("Продление договора в EXE не работает.")

            status, closed = _request(
                state,
                "POST",
                "/api/closures",
                payload={
                    "operation_id": str(uuid4()),
                    "cell_number": "1",
                    "contract_ref": contract_ref,
                    "expected_end_date": renewed_end.isoformat(),
                    "reason_code": "standard",
                },
            )
            if status != 201 or json.loads(closed)["cell_number"] != "1":
                raise RuntimeError("Закрытие договора в EXE не работает.")

            journal_filters = {
                "cell_number": "",
                "action": "",
                "date_from": "",
                "date_to": "",
                "client_name": "",
                "employee": "",
            }
            status, journal = _request(
                state,
                "POST",
                "/api/journal",
                payload={**journal_filters, "page": 1, "page_size": 50},
            )
            if status != 200 or json.loads(journal)["pagination"]["total"] < 3:
                raise RuntimeError("Журнал в EXE не показывает полный цикл договора.")
            status, report = _request(
                state,
                "POST",
                "/api/journal/report",
                payload=journal_filters,
            )
            if status != 200 or not report.startswith(b"PK"):
                raise RuntimeError("EXE не сформировал Excel-выписку.")

            status, _ = _request(
                state,
                "POST",
                "/api/runtime/shutdown",
                token=token,
            )
            if status != 200:
                raise RuntimeError("EXE отклонил завершение своего экземпляра.")
            if process.wait(timeout=10) != 0:
                raise RuntimeError("EXE завершился с ошибкой.")
            if ready_file.exists():
                raise RuntimeError("EXE не удалил временный файл готовности.")
            if len(list_backup_sets(settings)) < 3:
                raise RuntimeError("Полный цикл EXE не создал резервные комплекты.")
        finally:
            if state is not None and token is not None:
                try:
                    _request(
                        state,
                        "POST",
                        "/api/runtime/shutdown",
                        token=token,
                    )
                except OSError:
                    pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    print("Portable smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
