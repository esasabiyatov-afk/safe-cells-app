"""Validated seed data for cells, tariffs, and initial config."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
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
    "deposit_amount_minor": "1500",
    "admin_access_mode": "acknowledgement",
    "employees_json": "[]",
    "currency_code": "KGS",
    "currency_scale": "0",
    "penalty_rate_mode": "linked",
    "penalty_manual_rates_json": json.dumps(
        {str(height): rates[0] for height, rates in TARIFF_RATES.items()},
        sort_keys=True,
        separators=(",", ":"),
    ),
}

DOCUMENT_TEMPLATE_SEEDS: tuple[
    tuple[str, str, str, str, tuple[str, ...]], ...
] = (
    (
        "opening-transfer-act",
        "opening",
        "Акт приема передач сейф",
        "Акт приема передач сейф.docx",
        ("Дата.Сегодня", "Клиент.ФИО", "Сейф.Номер", "Система.Пользователь", "Счет.Номер"),
    ),
    (
        "opening-individual-safe-contract",
        "opening",
        "Договор индивидуального сейфа ф.л",
        "Договор индивидуального сейфа ф.л.docx",
        (
            "Дата.Сегодня", "Дата.СегодняК", "Договор.Конец", "Договор.КонецК",
            "Договор.Начало", "Договор.НачалоК", "Залог.Пропись",
            "Залог.ПрописьК", "Залог.Цифр", "Клиент.Документ.Выдан",
            "Клиент.Документ.ДатаВыдачи", "Клиент.Документ.Номер", "Клиент.ФИО",
            "Сейф.Номер", "Сейф.Размер", "Система.Пользователь", "Сумма", "Счет.Номер",
        ),
    ),
    (
        "opening-order",
        "opening",
        "Распоряжение Открытие сейф",
        "Распоряжение Открытие сейф.docx",
        ("Дата.Сегодня", "Сейф.Номер", "Счет.Номер"),
    ),
    (
        "renewal-addendum",
        "renewal",
        "Доп. соглашение сейф ф.л",
        "Доп. соглашение сейф ф.л.docx",
        (
            "Дата.Сегодня", "Дата.СегодняК", "Договор.НачалоД", "Договор.НачалоДК",
            "Клиент.Документ.Выдан", "Клиент.Документ.ДатаВыдачи",
            "Клиент.Документ.Номер", "Клиент.ФИО", "Продление.Конец",
            "Продление.КонецК", "Продление.Начало", "Продление.НачалоК",
            "Продление.Срок", "Продление.Сумма", "Сейф.Номер",
            "Система.Пользователь", "Счет.Номер",
        ),
    ),
    (
        "closing-order",
        "closing",
        "Распоряжение Закрытие сейф",
        "Распоряжение Закрытие сейф.docx",
        ("Дата.Сегодня", "Залог.Пропись", "Залог.Цифр", "Сейф.Номер", "Счет.Номер"),
    ),
)


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
    template_directory: Path | None = None,
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
        connection.execute(
            """
            UPDATE main.config
            SET value = ?, updated_at = ?, updated_by = ?
            WHERE key = ? AND value = '' AND updated_by = 'system-seed'
            """,
            (value, applied_at, "system-seed", key),
        )

    if template_directory is not None:
        for template_id, document_type, display_name, file_name, required in DOCUMENT_TEMPLATE_SEEDS:
            if not (template_directory / file_name).is_file():
                continue
            connection.execute(
                """INSERT OR IGNORE INTO main.document_templates(
                       template_id, document_type, display_name, relative_file_name,
                       required_placeholders_json, is_active, updated_at, updated_by
                   ) VALUES(?, ?, ?, ?, ?, 1, ?, 'system-seed')""",
                (
                    template_id,
                    document_type,
                    display_name,
                    file_name,
                    json.dumps(required, ensure_ascii=False),
                    applied_at,
                ),
            )
