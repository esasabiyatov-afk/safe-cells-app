"""Validated selection of linked or independent penalty rates."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.services.sizes import SizeKey, parse_size_key, size_key


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


def _active_sizes(connection: sqlite3.Connection) -> set[SizeKey]:
    return {
        (int(row[0]), int(row[1]), int(row[2]))
        for row in connection.execute(
            """
            SELECT DISTINCT cells.height_mm,
                   COALESCE(cells.width_mm, defaults.width_mm),
                   COALESCE(cells.depth_mm, defaults.depth_mm)
            FROM cells CROSS JOIN vault_defaults defaults
        WHERE defaults.id = 1
            """
        ).fetchall()
    }


def _linked_rates(connection: sqlite3.Connection) -> dict[SizeKey, int]:
    rows = connection.execute(
        """
        SELECT height_mm, width_mm, depth_mm, price_per_day_minor
        FROM tariffs
        WHERE period_from_days = 1
        ORDER BY height_mm, width_mm, depth_mm
        """
    ).fetchall()
    rates: dict[SizeKey, int] = {}
    for row in rows:
        size = (
            int(row["height_mm"]),
            int(row["width_mm"]),
            int(row["depth_mm"]),
        )
        rate = int(row["price_per_day_minor"])
        if size in rates or rate < 0 or rate > MAX_PENALTY_RATE:
            raise PenaltyRateConfigurationError(
                "Первые тарифные диапазоны для расчёта штрафа повреждены."
            )
        rates[size] = rate
    sizes = _active_sizes(connection)
    if not sizes or set(rates) != sizes:
        raise PenaltyRateConfigurationError(
            "Нужен первый тарифный диапазон для каждого размера ячейки."
        )
    return rates


def decode_manual_rates(
    value: object, *, sizes: set[SizeKey]
) -> dict[SizeKey, int]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise PenaltyRateConfigurationError(
            "Ручные штрафные ставки повреждены."
        ) from exc
    if not isinstance(decoded, dict):
        raise PenaltyRateConfigurationError("Ручные штрафные ставки повреждены.")
    rates: dict[SizeKey, int] = {}
    for raw_size, raw_rate in decoded.items():
        try:
            size = parse_size_key(raw_size)
        except ValueError as exc:
            raise PenaltyRateConfigurationError(
                "Размер ручной штрафной ставки указан неверно."
            ) from exc
        if isinstance(raw_rate, bool) or not isinstance(raw_rate, int):
            raise PenaltyRateConfigurationError(
                "Ручная штрафная ставка должна быть целым числом."
            )
        if raw_rate < 0 or raw_rate > MAX_PENALTY_RATE:
            raise PenaltyRateConfigurationError(
                "Ручная штрафная ставка указана вне допустимого диапазона."
            )
        if size in rates:
            raise PenaltyRateConfigurationError(
                "Ручная штрафная ставка одного размера повторяется."
            )
        rates[size] = raw_rate
    if set(rates) != sizes:
        raise PenaltyRateConfigurationError(
            "Нужна ручная штрафная ставка для каждого размера ячейки."
        )
    return rates


def encode_manual_rates(rates: dict[SizeKey, int]) -> str:
    return json.dumps(
        {size_key(*size): rates[size] for size in sorted(rates)},
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
        else decode_manual_rates(raw_manual, sizes=set(linked_rates))
    )
    return {
        "mode": mode,
        "manual_rates": [
            {
                "height_mm": size[0],
                "width_mm": size[1],
                "depth_mm": size[2],
                "price_per_day_minor": manual_rates[size],
            }
            for size in sorted(manual_rates)
        ],
    }


def resolve_penalty_rate(
    connection: sqlite3.Connection, *, height_mm: int,
    width_mm: int, depth_mm: int,
) -> int:
    settings = get_penalty_settings(connection)
    if settings["mode"] == PENALTY_RATE_MODE_LINKED:
        rates = _linked_rates(connection)
    else:
        rates = {
            (
                int(row["height_mm"]),
                int(row["width_mm"]),
                int(row["depth_mm"]),
            ): int(row["price_per_day_minor"])
            for row in settings["manual_rates"]
        }
    try:
        return rates[(height_mm, width_mm, depth_mm)]
    except KeyError as exc:
        raise PenaltyRateConfigurationError(
            "Для размера ячейки не найдена штрафная ставка."
        ) from exc
