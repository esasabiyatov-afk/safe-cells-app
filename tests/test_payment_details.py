from __future__ import annotations

import pytest

from app.services.payment_details import (
    build_payment_copy,
    fact_days_text,
    payment_cell_number,
    payment_client_name,
)


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("Абрамов Александр Дмитриевич", "Абрамов А. Д."),
        ("Аманова Залия", "Аманова З."),
        ("Ан Ульяна", "Ан У."),
        ("Жаныбек уулу Эсенбек", "Жаныбек У. Э."),
        ("Мадина", "Мадина"),
    ],
)
def test_payment_client_name_uses_full_first_part_and_initials(
    full_name: str,
    expected: str,
) -> None:
    assert payment_client_name(full_name) == expected


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (1, "1 факт. день"),
        (2, "2 факт. дня"),
        (5, "5 факт. дней"),
        (11, "11 факт. дней"),
        (21, "21 факт. день"),
        (24, "24 факт. дня"),
        (365, "365 факт. дней"),
    ],
)
def test_fact_days_text_uses_correct_declension(days: int, expected: str) -> None:
    assert fact_days_text(days) == expected


def test_payment_copy_formats_opening_and_leading_zero() -> None:
    result = build_payment_copy(
        action_kind="opening",
        client_full_name="Абрамов Александр Дмитриевич",
        cell_number="4",
        rent_days=365,
        rent_amount=2555,
    )

    assert payment_cell_number("4") == "04"
    assert result == {
        "rent": {
            "purpose": (
                "Комиссия за ячейку №04 Абрамов А. Д. (365 факт. дней)"
            ),
            "amount": 2555,
            "amount_label": "Сумма аренды",
        },
        "penalty": None,
    }


def test_payment_copy_formats_renewal_and_separate_penalty() -> None:
    result = build_payment_copy(
        action_kind="renewal",
        client_full_name="Абрамов Александр Дмитриевич",
        cell_number="104",
        rent_days=30,
        rent_amount=450,
        penalty_days=2,
        penalty_amount=30,
    )

    assert result["rent"] == {
        "purpose": "Комиссия за ячейку №104 Абрамов А. Д. (30 факт. дней)",
        "amount": 450,
        "amount_label": "Сумма продления",
    }
    assert result["penalty"] == {
        "purpose": "Штраф за ячейку №104 Абрамов А. Д. (2 факт. дня)",
        "amount": 30,
        "amount_label": "Сумма штрафа",
    }
