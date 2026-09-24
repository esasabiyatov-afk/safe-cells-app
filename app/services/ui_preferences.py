"""Shared application-only display preferences stored in the config table."""

from __future__ import annotations

import sqlite3
from typing import Any


DISPLAY_DATE_WORDS_KEY = "display_date_words"
SHOW_UI_HINTS_KEY = "show_ui_hints"
UI_PREFERENCE_KEYS = frozenset({DISPLAY_DATE_WORDS_KEY, SHOW_UI_HINTS_KEY})
DEFAULT_UI_PREFERENCES = {
    DISPLAY_DATE_WORDS_KEY: True,
    SHOW_UI_HINTS_KEY: True,
}


class UiPreferenceError(ValueError):
    """A stored display preference has an unsupported value."""


def parse_config_bool(value: object, *, key: str) -> bool:
    normalized = str(value).strip()
    if normalized == "1":
        return True
    if normalized == "0":
        return False
    raise UiPreferenceError(f"Некорректная настройка интерфейса «{key}».")


def get_ui_preferences(connection: sqlite3.Connection) -> dict[str, bool]:
    """Read preferences with safe defaults for databases created before them."""

    preferences = dict(DEFAULT_UI_PREFERENCES)
    placeholders = ",".join("?" for _ in UI_PREFERENCE_KEYS)
    rows = connection.execute(
        f"SELECT key, value FROM config WHERE key IN ({placeholders})",
        tuple(sorted(UI_PREFERENCE_KEYS)),
    ).fetchall()
    for row in rows:
        key = str(row["key"])
        preferences[key] = parse_config_bool(row["value"], key=key)
    return preferences


def validate_ui_preferences(value: dict[str, Any]) -> dict[str, bool]:
    preferences: dict[str, bool] = {}
    for key in UI_PREFERENCE_KEYS:
        item = value.get(key)
        if not isinstance(item, bool):
            raise UiPreferenceError(f"Настройка интерфейса «{key}» указана неверно.")
        preferences[key] = item
    return preferences


def encode_config_bool(value: bool) -> str:
    return "1" if value else "0"
