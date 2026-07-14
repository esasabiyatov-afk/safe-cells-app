"""Validated selection of linked or independent penalty rates."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


PENALTY_RATE_MODE_KEY = "penalty_rate_mode"
PENALTY_MANUAL_RATES_KEY = "penalty_manual_rates_json"
PENALTY_RATE_MODE_LINKED = "linked"
PENALTY_RATE_MODE_MANUAL = "manual"
PENALTY_RATE_MODES = frozenset(
    {PENALTY_RATE_MODE_LINKED, PENALTY_RATE_MODE_MANUAL}
)
MAX_PENALTY_RATE = 10_000_000


class PenaltyRateConfigurationError(RuntimeError):
    """Penalty settings are absent, malformed, or inconsistent."""


def _linked_rates(connection: sqlite3.Connection) -> dict[int, int]:
    rows = connection.execute(
        """
        SELECT height_mm, price_per_day_minor
        FROM tariffs
        WHERE period_from_days = 1 AND period_to_days = 30
        ORDER BY height_mm
        """
    ).fetchall()
    rates: dict[int, int] = {}
    for row in rows:
        height = int(row["height_mm"])
        rate = int(row["price_per_day_minor"])
        if height in rates or rate < 0 or rate > MAX_PENALTY_RATE:
            raise PenaltyRateConfigurationError(
                "Тарифы 1–30 дней для расчёта штрафа повреждены."
            )
        rates[height] = rate
    heights = {
        int(row["height_mm"])
        for row in connection.execute(
            "SELECT DISTINCT height_mm FROM cells ORDER BY height_mm"
        ).fetchall()
    }
    if not heights or set(rates) != heights:
        raise PenaltyRateConfigurationError(
            "Нужен тариф 1–30 дней для каждой высоты ячейки."
        )
    return rates


def decode_manual_rates(value: object, *, heights: set[int]) -> dict[int, int]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise PenaltyRateConfigurationError(
            "Ручные штрафные ставки повреждены."
        ) from exc
    if not isinstance(decoded, dict):
        raise PenaltyRateConfigurationError("Ручные штрафные ставки повреждены.")
    rates: dict[int, int] = {}
    for raw_height, raw_rate in decoded.items():
        try:
            height = int(raw_height)
        except (TypeError, ValueError) as exc:
            raise PenaltyRateConfigurationError(
                "Высота ручной штрафной ставки указана неверно."
            ) from exc
        if isinstance(raw_rate, bool) or not isinstance(raw_rate, int):
            raise PenaltyRateConfigurationError(
                "Ручная штрафная ставка должна быть целым числом."
            )
        if raw_rate < 0 or raw_rate > MAX_PENALTY_RATE:
            raise PenaltyRateConfigurationError(
                "Ручная штрафная ставка указана вне допустимого диапазона."
            )
        if height in rates:
            raise PenaltyRateConfigurationError(
                "Ручная штрафная ставка для одной высоты повторяется."
            )
        rates[height] = raw_rate
    if set(rates) != heights:
        raise PenaltyRateConfigurationError(
            "Нужна ручная штрафная ставка для каждой высоты ячейки."
        )
    return rates


def encode_manual_rates(rates: dict[int, int]) -> str:
    return json.dumps(
        {str(height): rates[height] for height in sorted(rates)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def get_penalty_settings(connection: sqlite3.Connection) -> dict[str, Any]:
    linked_rates = _linked_rates(connection)
    rows = {
        str(row["key"]): str(row["value"])
        for row in connection.execute(
            "SELECT key, value FROM config WHERE key IN (?, ?)",
            (PENALTY_RATE_MODE_KEY, PENALTY_MANUAL_RATES_KEY),
        ).fetchall()
    }
    mode = rows.get(PENALTY_RATE_MODE_KEY, PENALTY_RATE_MODE_LINKED)
    if mode not in PENALTY_RATE_MODES:
        raise PenaltyRateConfigurationError("Режим штрафной ставки повреждён.")
    raw_manual = rows.get(PENALTY_MANUAL_RATES_KEY)
    if raw_manual is None and mode == PENALTY_RATE_MODE_MANUAL:
        raise PenaltyRateConfigurationError(
            "Для ручного режима не сохранены штрафные ставки."
        )
    manual_rates = (
        linked_rates
        if raw_manual is None
        else decode_manual_rates(raw_manual, heights=set(linked_rates))
    )
    return {
        "mode": mode,
        "manual_rates": [
            {"height_mm": height, "price_per_day_minor": manual_rates[height]}
            for height in sorted(manual_rates)
        ],
    }


def resolve_penalty_rate(
    connection: sqlite3.Connection, *, height_mm: int
) -> int:
    settings = get_penalty_settings(connection)
    if settings["mode"] == PENALTY_RATE_MODE_LINKED:
        rates = _linked_rates(connection)
    else:
        rates = {
            int(row["height_mm"]): int(row["price_per_day_minor"])
            for row in settings["manual_rates"]
        }
    try:
        return rates[height_mm]
    except KeyError as exc:
        raise PenaltyRateConfigurationError(
            "Для высоты ячейки не найдена штрафная ставка."
        ) from exc
