"""Canonical full physical sizes used by cells, tariffs, and penalties."""

from __future__ import annotations

from typing import TypeAlias


SizeKey: TypeAlias = tuple[int, int, int]


def size_key(height_mm: int, width_mm: int, depth_mm: int) -> str:
    return f"{int(height_mm)}x{int(width_mm)}x{int(depth_mm)}"


def parse_size_key(value: object) -> SizeKey:
    if not isinstance(value, str):
        raise ValueError("Неверный размер ячейки.")
    parts = value.split("x")
    if len(parts) != 3:
        raise ValueError("Неверный размер ячейки.")
    try:
        result = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ValueError("Неверный размер ячейки.") from exc
    if any(part <= 0 for part in result):
        raise ValueError("Неверный размер ячейки.")
    return result  # type: ignore[return-value]


def size_label(size: SizeKey) -> str:
    height, width, depth = size
    return f"{height} × {width} × {depth} мм"
