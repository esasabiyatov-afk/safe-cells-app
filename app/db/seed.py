"""Validated seed data for cells, tariffs, and initial config."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import sqlite3


EXPECTED_CELL_COUNT = 126
ALLOWED_SEED_HEIGHTS = frozenset({50, 75, 100, 125, 175, 300})


class SeedDataError(ValueError):
    """Raised when seed data is incomplete or conflicts with the database."""


@dataclass(frozen=True, slots=True)
class CellSeed:
    number: str
    height_mm: int


TARIFF_RATES: dict[int, tuple[int, int, int, int]] = {
    50: (15, 10, 8, 7),
    75: (17, 13, 11, 8),
    100: (17, 13, 11, 8),
    125: (20, 15, 13, 10),
    175: (25, 20, 15, 13),
    300: (30, 25, 20, 17),
}
TARIFF_PERIODS: tuple[tuple[int, int | None], ...] = (
    (1, 30),
    (31, 90),
    (91, 180),
    (181, None),
)
INITIAL_CONFIG: dict[str, str] = {
    "expiring_soon_days": "7",
    "deposit_amount_minor": "",
    "currency_code": "",
    "currency_scale": "",
}


def load_cell_seed(csv_path: Path | str) -> tuple[CellSeed, ...]:
    path = Path(csv_path)
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != ["number", "height_mm"]:
                raise SeedDataError(
                    "CSV ячеек должен содержать столбцы number,height_mm."
                )
            cells: list[CellSeed] = []
            for row in reader:
                try:
                    number = str(int(row["number"]))
                    height = int(row["height_mm"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise SeedDataError("CSV ячеек содержит неверное значение.") from exc
                cells.append(CellSeed(number=number, height_mm=height))
    except OSError as exc:
        raise SeedDataError(f"Не удалось прочитать seed-файл: {path}") from exc

    numbers = [cell.number for cell in cells]
    if len(cells) != EXPECTED_CELL_COUNT:
        raise SeedDataError(f"Ожидалось {EXPECTED_CELL_COUNT} ячеек, получено {len(cells)}.")
    if len(set(numbers)) != len(numbers):
        raise SeedDataError("CSV ячеек содержит повторяющиеся номера.")
    expected_numbers = {str(number) for number in range(1, EXPECTED_CELL_COUNT + 1)}
    if set(numbers) != expected_numbers:
        raise SeedDataError("CSV должен содержать номера ячеек от 1 до 126 без пропусков.")
    invalid_heights = {cell.height_mm for cell in cells} - ALLOWED_SEED_HEIGHTS
    if invalid_heights:
        raise SeedDataError("CSV ячеек содержит недопустимую высоту.")
    return tuple(cells)


def seed_working_database(
    connection: sqlite3.Connection,
    cells: tuple[CellSeed, ...],
    *,
    applied_at: str,
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO main.vault_defaults(id, width_mm, depth_mm) VALUES(1, 220, 330)"
    )

    for cell in cells:
        connection.execute(
            "INSERT OR IGNORE INTO main.cells(number, height_mm) VALUES(?, ?)",
            (cell.number, cell.height_mm),
        )
        stored = connection.execute(
            "SELECT height_mm FROM main.cells WHERE number = ?", (cell.number,)
        ).fetchone()
        if stored is None or int(stored[0]) != cell.height_mm:
            raise SeedDataError(
                f"Высота существующей ячейки {cell.number} не совпадает с seed-файлом."
            )

    for height, rates in TARIFF_RATES.items():
        for (period_from, period_to), rate in zip(TARIFF_PERIODS, rates, strict=True):
            connection.execute(
                """
                INSERT OR IGNORE INTO main.tariffs(
                    height_mm, period_from_days, period_to_days,
                    price_per_day_minor, updated_at, updated_by
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (height, period_from, period_to, rate, applied_at, "system-seed"),
            )

    for key, value in INITIAL_CONFIG.items():
        connection.execute(
            """
            INSERT OR IGNORE INTO main.config(key, value, updated_at, updated_by)
            VALUES(?, ?, ?, ?)
            """,
            (key, value, applied_at, "system-seed"),
        )
