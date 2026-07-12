"""Windows employee identity and remembered local display names."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
from uuid import uuid4


def get_employee_username() -> str:
    """Return the current Windows account name without logging it."""

    try:
        username = getpass.getuser().strip()
    except (ImportError, KeyError, OSError):
        username = ""
    return username or "Не определён"


class EmployeeProfileError(ValueError):
    """The local employee profile is invalid or cannot be saved."""


def default_employee_profile_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "SafeCells" / "employee-profiles.json"
    return Path.home() / ".safe-cells" / "employee-profiles.json"


def validate_employee_full_name(value: object) -> str:
    if not isinstance(value, str):
        raise EmployeeProfileError("Укажите фамилию и имя сотрудника.")
    normalized = " ".join(value.split())
    if len(normalized) < 3 or len(normalized) > 128 or len(normalized.split()) < 2:
        raise EmployeeProfileError("Укажите полностью фамилию и имя сотрудника.")
    if any(character in normalized for character in "<>\"{}[]"):
        raise EmployeeProfileError("Фамилия и имя содержат недопустимые символы.")
    return normalized


def _read_profiles(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EmployeeProfileError(
            "Не удалось прочитать локальный профиль сотрудника."
        ) from exc
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in payload.items()
    ):
        raise EmployeeProfileError("Локальный профиль сотрудника повреждён.")
    return payload


def get_employee_full_name(path: Path, username: str) -> str | None:
    value = _read_profiles(Path(path)).get(username)
    return validate_employee_full_name(value) if value is not None else None


def save_employee_full_name(path: Path, username: str, full_name: object) -> str:
    """Atomically remember a full name outside the shared database."""

    normalized = validate_employee_full_name(full_name)
    target = Path(path)
    profiles = _read_profiles(target)
    profiles[username] = normalized
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(profiles, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise EmployeeProfileError(
            "Не удалось сохранить локальный профиль сотрудника."
        ) from exc
    return normalized
