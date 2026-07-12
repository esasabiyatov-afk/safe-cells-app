"""Authoritative read-only rental calculations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import sqlite3
from typing import Any

from app.config import Settings
from app.db.connections import (
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_readonly,
    validate_database_pair,
)


class RentalValidationError(ValueError):
    """User input cannot form a valid rental period."""


class CellUnavailableError(RuntimeError):
    """The requested cell does not exist or is already occupied."""


class RentalReadError(RuntimeError):
    """The database cannot be read safely."""


class RentalDataError(RuntimeError):
    """Tariff or money settings violate required invariants."""


@dataclass(frozen=True, slots=True)
class RentalQuote:
    cell_number: str
    height_mm: int
    start_date: str
    end_date: str
    rent_days: int
    period_from_days: int
    period_to_days: int | None
    price_per_day: int
    rent_price: int
    deposit_amount: int
    currency_code: str = "KGS"
    currency_label: str = "сом"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_iso_date(value: object, *, field_label: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise RentalValidationError(f"Укажите {field_label}.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise RentalValidationError(f"Поле «{field_label}» содержит неверную дату.") from exc


def inclusive_days(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        raise RentalValidationError("Дата окончания не может быть раньше даты начала.")
    return (end_date - start_date).days + 1


def end_date_from_days(start_date: date, rent_days: int) -> date:
    if isinstance(rent_days, bool) or not isinstance(rent_days, int):
        raise RentalValidationError("Количество дней должно быть целым числом.")
    if rent_days < 1:
        raise RentalValidationError("Количество дней должно быть не меньше 1.")
    try:
        return start_date + timedelta(days=rent_days - 1)
    except OverflowError as exc:
        raise RentalValidationError("Указан слишком большой срок аренды.") from exc


def _validated_period(
    *,
    start_date_value: object,
    end_date_value: object | None,
    rent_days_value: object | None,
) -> tuple[date, date, int]:
    start_date = parse_iso_date(start_date_value, field_label="дату начала")

    supplied_days: int | None = None
    if rent_days_value is not None:
        if isinstance(rent_days_value, bool) or not isinstance(rent_days_value, int):
            raise RentalValidationError("Количество дней должно быть целым числом.")
        if rent_days_value < 1:
            raise RentalValidationError("Количество дней должно быть не меньше 1.")
        supplied_days = rent_days_value

    if end_date_value is None and supplied_days is None:
        raise RentalValidationError("Укажите дату окончания или количество дней.")

    if end_date_value is None:
        end_date = end_date_from_days(start_date, supplied_days)
        return start_date, end_date, supplied_days

    end_date = parse_iso_date(end_date_value, field_label="дату окончания")
    calculated_days = inclusive_days(start_date, end_date)
    if supplied_days is not None and supplied_days != calculated_days:
        raise RentalValidationError(
            "Количество дней не соответствует выбранным датам. Обновите расчёт."
        )
    return start_date, end_date, calculated_days


def _money_config(connection: sqlite3.Connection) -> tuple[int, str, int]:
    rows = connection.execute(
        """
        SELECT key, value FROM config
        WHERE key IN ('deposit_amount_minor', 'currency_code', 'currency_scale')
        """
    ).fetchall()
    values = {row["key"]: row["value"] for row in rows}
    try:
        deposit = int(values["deposit_amount_minor"])
        currency_code = values["currency_code"]
        currency_scale = int(values["currency_scale"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RentalDataError("Денежные настройки заполнены некорректно.") from exc
    if deposit < 0 or currency_code != "KGS" or currency_scale != 0:
        raise RentalDataError("Денежные настройки заполнены некорректно.")
    return deposit, currency_code, currency_scale


def calculate_rental_quote_in_connection(
    connection: sqlite3.Connection,
    *,
    cell_number: object,
    start_date_value: object,
    end_date_value: object | None = None,
    rent_days_value: object | None = None,
) -> RentalQuote:
    """Calculate a quote using the caller's current SQLite transaction."""

    if not isinstance(cell_number, str) or not cell_number.strip():
        raise RentalValidationError("Не указан номер ячейки.")
    normalized_number = cell_number.strip()
    if len(normalized_number) > 50:
        raise RentalValidationError("Номер ячейки слишком длинный.")

    start_date, end_date, rent_days = _validated_period(
        start_date_value=start_date_value,
        end_date_value=end_date_value,
        rent_days_value=rent_days_value,
    )
    cell = connection.execute(
        """
        SELECT cells.number, cells.height_mm, contracts.contract_id
        FROM cells
        LEFT JOIN contracts ON contracts.cell_number = cells.number
        WHERE cells.number = ?
        """,
        (normalized_number,),
    ).fetchone()
    if cell is None:
        raise CellUnavailableError("Ячейка не найдена.")
    if cell["contract_id"] is not None:
        raise CellUnavailableError(
            "Ячейка уже занята. Обновите главный экран и выберите свободную ячейку."
        )

    tariff_rows = connection.execute(
        """
        SELECT period_from_days, period_to_days, price_per_day_minor
        FROM tariffs
        WHERE height_mm = ?
          AND period_from_days <= ?
          AND (period_to_days IS NULL OR period_to_days >= ?)
        ORDER BY period_from_days
        """,
        (cell["height_mm"], rent_days, rent_days),
    ).fetchall()
    if len(tariff_rows) != 1:
        raise RentalDataError(
            "Для выбранной высоты и срока не найден единственный тариф."
        )
    tariff = tariff_rows[0]
    deposit, currency_code, _currency_scale = _money_config(connection)

    price_per_day = int(tariff["price_per_day_minor"])
    if price_per_day < 0:
        raise RentalDataError("Тариф не может быть отрицательным.")
    rent_price = rent_days * price_per_day
    return RentalQuote(
        cell_number=str(cell["number"]),
        height_mm=int(cell["height_mm"]),
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        rent_days=rent_days,
        period_from_days=int(tariff["period_from_days"]),
        period_to_days=(
            int(tariff["period_to_days"])
            if tariff["period_to_days"] is not None
            else None
        ),
        price_per_day=price_per_day,
        rent_price=rent_price,
        deposit_amount=deposit,
        currency_code=currency_code,
    )


def calculate_rental_quote(
    settings: Settings,
    *,
    cell_number: object,
    start_date_value: object,
    end_date_value: object | None = None,
    rent_days_value: object | None = None,
) -> RentalQuote:
    """Recalculate dates, rental price and separate deposit using a short RO connection."""

    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            return calculate_rental_quote_in_connection(
                connection,
                cell_number=cell_number,
                start_date_value=start_date_value,
                end_date_value=end_date_value,
                rent_days_value=rent_days_value,
            )
    except (RentalValidationError, CellUnavailableError, RentalDataError):
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise RentalReadError(NETWORK_ERROR_MESSAGE) from exc
