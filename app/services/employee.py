"""Shared employee directory and process-local employee selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import sqlite3
from threading import Lock
from typing import Any

from app.config import Settings
from app.db.connections import (
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_readonly,
    validate_database_pair,
)


EMPLOYEES_CONFIG_KEY = "employees_json"
MAX_EMPLOYEES = 200


class EmployeeProfileError(ValueError):
    """The shared employee directory or supplied name is invalid."""


class EmployeeDirectoryReadError(RuntimeError):
    """The shared employee directory cannot be read."""


class EmployeeSelectionRequiredError(RuntimeError):
    """No active employee is selected in this local process."""


@dataclass(frozen=True, slots=True)
class EmployeeRecord:
    employee_id: str
    full_name: str
    is_active: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_employee_full_name(value: object) -> str:
    if not isinstance(value, str):
        raise EmployeeProfileError("Укажите фамилию и имя сотрудника.")
    normalized = " ".join(value.split())
    if len(normalized) < 3 or len(normalized) > 128 or len(normalized.split()) < 2:
        raise EmployeeProfileError("Укажите полностью фамилию и имя сотрудника.")
    if any(character in normalized for character in "<>\"{}[]"):
        raise EmployeeProfileError("Фамилия и имя содержат недопустимые символы.")
    return normalized


def decode_employee_config(value: object | None) -> list[EmployeeRecord]:
    if value is None:
        return []
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise EmployeeProfileError("Список сотрудников повреждён.") from exc
    if not isinstance(payload, list) or len(payload) > MAX_EMPLOYEES:
        raise EmployeeProfileError("Список сотрудников повреждён.")
    records: list[EmployeeRecord] = []
    identifiers: set[str] = set()
    names: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict) or set(raw) != {"employee_id", "full_name", "is_active"}:
            raise EmployeeProfileError("Список сотрудников повреждён.")
        employee_id = raw["employee_id"]
        if not isinstance(employee_id, str) or not employee_id or len(employee_id) > 100:
            raise EmployeeProfileError("Список сотрудников повреждён.")
        full_name = validate_employee_full_name(raw["full_name"])
        is_active = raw["is_active"]
        if not isinstance(is_active, bool):
            raise EmployeeProfileError("Список сотрудников повреждён.")
        if employee_id in identifiers or full_name.casefold() in names:
            raise EmployeeProfileError("Список сотрудников содержит дубликат.")
        identifiers.add(employee_id)
        names.add(full_name.casefold())
        records.append(EmployeeRecord(employee_id, full_name, is_active))
    return records


def encode_employee_config(records: list[EmployeeRecord]) -> str:
    return json.dumps(
        [record.to_dict() for record in records],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def list_employees(settings: Settings, *, active_only: bool = False) -> list[EmployeeRecord]:
    try:
        paths = validate_database_pair(settings)
        with open_readonly(paths.working, busy_timeout_ms=settings.busy_timeout_ms) as connection:
            row = connection.execute(
                "SELECT value FROM config WHERE key = ?", (EMPLOYEES_CONFIG_KEY,)
            ).fetchone()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise EmployeeDirectoryReadError(NETWORK_ERROR_MESSAGE) from exc
    try:
        records = decode_employee_config(None if row is None else row["value"])
    except EmployeeProfileError as exc:
        raise EmployeeDirectoryReadError(str(exc)) from exc
    if active_only:
        records = [record for record in records if record.is_active]
    return sorted(records, key=lambda record: record.full_name.casefold())


class EmployeeSelectionManager:
    """Remember the selected employee only until this local process exits."""

    def __init__(self) -> None:
        self._employee_id: str | None = None
        self._lock = Lock()

    def get(self) -> str | None:
        with self._lock:
            return self._employee_id

    def set(self, employee_id: str) -> None:
        with self._lock:
            self._employee_id = employee_id

    def clear(self) -> None:
        with self._lock:
            self._employee_id = None


def select_employee(
    settings: Settings, manager: EmployeeSelectionManager, employee_id: object
) -> EmployeeRecord:
    if not isinstance(employee_id, str) or not employee_id:
        raise EmployeeSelectionRequiredError("Выберите сотрудника.")
    record = next(
        (
            item
            for item in list_employees(settings, active_only=True)
            if item.employee_id == employee_id
        ),
        None,
    )
    if record is None:
        manager.clear()
        raise EmployeeSelectionRequiredError(
            "Сотрудник не найден или отключён. Выберите другого сотрудника."
        )
    manager.set(record.employee_id)
    return record


def get_selected_employee(
    settings: Settings, manager: EmployeeSelectionManager
) -> EmployeeRecord:
    employee_id = manager.get()
    if employee_id is None:
        raise EmployeeSelectionRequiredError("Перед операцией выберите сотрудника.")
    record = next(
        (
            item
            for item in list_employees(settings, active_only=True)
            if item.employee_id == employee_id
        ),
        None,
    )
    if record is None:
        manager.clear()
        raise EmployeeSelectionRequiredError(
            "Выбранный сотрудник отключён. Выберите другого сотрудника."
        )
    return record
