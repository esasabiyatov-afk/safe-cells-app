"""One-time copy fields for posting a rental operation in the ABS."""

from __future__ import annotations


def payment_client_name(full_name: object) -> str:
    """Return the first name part in full and up to two following initials."""

    parts = " ".join(str(full_name or "").split()).split()
    if not parts:
        raise ValueError("Не удалось подготовить ФИО для назначения платежа.")
    initials = " ".join(f"{part[0].upper()}." for part in parts[1:3] if part)
    return f"{parts[0]} {initials}".strip()


def payment_cell_number(cell_number: object) -> str:
    """Print one-digit cell numbers with the bank-approved leading zero."""

    normalized = str(cell_number or "").strip()
    if not normalized:
        raise ValueError("Не удалось подготовить номер ячейки для проводки.")
    if len(normalized) == 1 and normalized.isdecimal():
        return f"0{normalized}"
    return normalized


def fact_days_text(days: object) -> str:
    """Format the factual-day phrase with Russian declension."""

    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError("Не удалось подготовить срок для назначения платежа.")
    remainder_100 = days % 100
    remainder_10 = days % 10
    if 11 <= remainder_100 <= 14:
        word = "дней"
    elif remainder_10 == 1:
        word = "день"
    elif 2 <= remainder_10 <= 4:
        word = "дня"
    else:
        word = "дней"
    return f"{days} факт. {word}"


def build_payment_copy(
    *,
    action_kind: str,
    client_full_name: object,
    cell_number: object,
    rent_days: int,
    rent_amount: int,
    penalty_days: int = 0,
    penalty_amount: int = 0,
) -> dict[str, object]:
    """Build separate purpose and numeric amount fields for manual ABS posting."""

    if action_kind not in {"opening", "renewal"}:
        raise ValueError("Неизвестный вид операции для проводки.")
    if isinstance(rent_amount, bool) or not isinstance(rent_amount, int) or rent_amount < 0:
        raise ValueError("Не удалось подготовить сумму аренды для проводки.")
    if (
        isinstance(penalty_days, bool)
        or not isinstance(penalty_days, int)
        or penalty_days < 0
        or isinstance(penalty_amount, bool)
        or not isinstance(penalty_amount, int)
        or penalty_amount < 0
    ):
        raise ValueError("Не удалось подготовить штраф для проводки.")
    if penalty_days == 0 and penalty_amount != 0:
        raise ValueError("Дни и сумма штрафа не соответствуют друг другу.")

    short_name = payment_client_name(client_full_name)
    printed_cell = payment_cell_number(cell_number)
    rent_purpose = (
        f"Комиссия за ячейку №{printed_cell} {short_name} "
        f"({fact_days_text(rent_days)})"
    )
    penalty = None
    if penalty_days > 0:
        penalty = {
            "purpose": (
                f"Штраф за ячейку №{printed_cell} {short_name} "
                f"({fact_days_text(penalty_days)})"
            ),
            "amount": penalty_amount,
            "amount_label": "Сумма штрафа",
        }
    return {
        "rent": {
            "purpose": rent_purpose,
            "amount": rent_amount,
            "amount_label": (
                "Сумма аренды" if action_kind == "opening" else "Сумма продления"
            ),
        },
        "penalty": penalty,
    }
