from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.db.seed import (
    ALLOWED_SEED_HEIGHTS,
    EXPECTED_CELL_COUNT,
    SeedDataError,
    load_cell_seed,
)


def test_real_seed_has_126_unique_cells_and_allowed_heights(
    cells_csv_path: Path,
) -> None:
    cells = load_cell_seed(cells_csv_path)

    assert len(cells) == EXPECTED_CELL_COUNT
    assert len({cell.number for cell in cells}) == EXPECTED_CELL_COUNT
    assert {cell.number for cell in cells} == {
        str(number) for number in range(1, 127)
    }
    assert {cell.height_mm for cell in cells} == ALLOWED_SEED_HEIGHTS


def test_seed_distribution_matches_source(cells_csv_path: Path) -> None:
    cells = load_cell_seed(cells_csv_path)
    distribution = {
        height: sum(cell.height_mm == height for cell in cells)
        for height in ALLOWED_SEED_HEIGHTS
    }
    assert distribution == {50: 45, 75: 13, 100: 56, 125: 4, 175: 5, 300: 3}


def test_duplicate_cell_number_is_rejected(
    tmp_path: Path, cells_csv_path: Path
) -> None:
    rows = list(csv.DictReader(cells_csv_path.read_text(encoding="utf-8").splitlines()))
    rows[-1]["number"] = rows[0]["number"]
    invalid_path = tmp_path / "duplicates.csv"
    with invalid_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["number", "height_mm"])
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(SeedDataError, match="повторяющиеся"):
        load_cell_seed(invalid_path)


def test_invalid_height_is_rejected(tmp_path: Path, cells_csv_path: Path) -> None:
    content = cells_csv_path.read_text(encoding="utf-8").replace("1,50", "1,999", 1)
    invalid_path = tmp_path / "invalid-height.csv"
    invalid_path.write_text(content, encoding="utf-8")

    with pytest.raises(SeedDataError, match="недопустимую высоту"):
        load_cell_seed(invalid_path)
