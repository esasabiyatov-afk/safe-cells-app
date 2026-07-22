"""Read-only renewal quotes and atomic confirmed renewals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import json
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from app.config import Settings
from app.db.connections import (
    DatabaseCorruptionError,
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_readonly,
    open_write,
    validate_database_pair,
)
from app.services.backups import create_backup_pair, has_valid_backup_for_operation
from app.services.legacy_contracts import require_legacy_identity
from app.services.penalty_rates import (
    PenaltyRateConfigurationError,
    resolve_penalty_rate,
)
from app.services.rental_calculator import parse_iso_date


BUSY_MESSAGE = "Другая операция записи ещё не завершена. Подождите и обновите данные."
UNCERTAIN_MESSAGE = (
    "Не удалось подтвердить результат сохранения. Не повторяйте операцию автоматически. "
    "Обновите главный экран и проверьте состояние ячейки."
)


class RenewalValidationError(ValueError):
    """The renewal request is incomplete or malformed."""


class RenewalConflictError(RuntimeError):
    """The active contract changed or is not eligible for renewal."""


class RenewalReadError(RuntimeError):
    """A quote could not be read safely."""


class RenewalBusyError(RuntimeError):
    """Another writer held the database beyond the configured timeout."""


class RenewalNetworkError(RuntimeError):
    """The database pair could not be reached safely."""


class RenewalWriteError(RuntimeError):
    """The renewal transaction failed and was rolled back."""


class RenewalWriteUncertainError(RuntimeError):
    """The connection failed while commit/result verification was in progress."""


@dataclass(frozen=True, slots=True)
class RenewalQuote:
    contract_ref: str
    cell_number: str
    height_mm: int
    old_end_date: str
    renewal_date: str
    new_start_date: str
    new_end_date: str
    renewal_days: int
    price_per_day: int
    renewal_price: int
    penalty_days: int
    penalty_rate: int
    penalty_amount: int
    total_amount: int
    currency_code: str = "KGS"
    currency_label: str = "сом"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RenewalResult:
    renewal_id: str
    contract_ref: str
    cell_number: str
    old_end_date: str
    renewal_date: str
    new_start_date: str
    new_end_date: str
    renewal_days: int
    price_per_day: int
    renewal_price: int
    penalty_days: int
    penalty_rate: int
    penalty_amount: int
    total_amount: int
    repeated: bool
    backup_created: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def renewal_penalty_days(*, renewal_date: date, old_end_date: date) -> int:
    return max(0, (renewal_date - old_end_date).days - 1)


def renewal_start_date(*, renewal_date: date, old_end_date: date) -> date:
    if renewal_date <= old_end_date:
        return old_end_date + timedelta(days=1)
    return renewal_date


def _required_text(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RenewalValidationError(f"Укажите поле «{label}».")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise RenewalValidationError(f"Поле «{label}» слишком длинное.")
    return normalized


def _operation_id(value: object) -> str:
    if not isinstance(value, str):
        raise RenewalValidationError("Не удалось подготовить операцию. Обновите форму.")
    try:
        return str(UUID(value.strip()))
    except (ValueError, AttributeError) as exc:
        raise RenewalValidationError(
            "Не удалось подготовить операцию. Обновите форму."
        ) from exc


def _date(value: object, *, label: str) -> date:
    try:
        return parse_iso_date(value, field_label=label)
    except ValueError as exc:
        raise RenewalValidationError(str(exc)) from exc


def _days(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RenewalValidationError("Количество дней должно быть целым числом.")
    if value < 1:
        raise RenewalValidationError("Количество дней должно быть не меньше 1.")
    return value


def _new_period(
    *, new_start: date, new_end_value: object | None, renewal_days_value: object | None
) -> tuple[date, int]:
    supplied_days = _days(renewal_days_value)
    if new_end_value is None and supplied_days is None:
        raise RenewalValidationError("Укажите новую дату окончания или количество дней.")
    if new_end_value is None:
        try:
            return new_start + timedelta(days=supplied_days - 1), supplied_days
        except OverflowError as exc:
            raise RenewalValidationError("Указан слишком большой срок продления.") from exc
    new_end = _date(new_end_value, label="новую дату окончания")
    if new_end < new_start:
        raise RenewalValidationError(
            "Новая дата окончания не может быть раньше начала нового периода."
        )
    calculated_days = (new_end - new_start).days + 1
    if supplied_days is not None and supplied_days != calculated_days:
        raise RenewalValidationError(
            "Количество дней не соответствует выбранной дате окончания. Обновите расчёт."
        )
    return new_end, calculated_days


def _single_tariff(
    connection: sqlite3.Connection, *, height_mm: int, days: int
) -> int:
    rows = connection.execute(
        """
        SELECT price_per_day_minor
        FROM tariffs
        WHERE height_mm = ? AND period_from_days <= ?
          AND (period_to_days IS NULL OR period_to_days >= ?)
        """,
        (height_mm, days, days),
    ).fetchall()
    if len(rows) != 1:
        raise RenewalWriteError(
            "Для выбранной высоты и срока не найден единственный тариф."
        )
    rate = int(rows[0]["price_per_day_minor"])
    if rate < 0:
        raise RenewalWriteError("Тариф не может быть отрицательным.")
    return rate


def calculate_renewal_quote_in_connection(
    connection: sqlite3.Connection,
    *,
    cell_number: object,
    contract_ref: object,
    renewal_date: date,
    new_end_date_value: object | None = None,
    renewal_days_value: object | None = None,
) -> RenewalQuote:
    normalized_cell = _required_text(cell_number, label="Номер ячейки", maximum=50)
    normalized_ref = _required_text(
        contract_ref, label="Идентификатор договора", maximum=100
    )
    row = connection.execute(
        """
        SELECT contracts.contract_id,
               contracts.cell_number, contracts.end_date,
               contracts.extra_fields_json, cells.height_mm
        FROM contracts
        JOIN cells ON cells.number = contracts.cell_number
        WHERE contracts.cell_number = ? AND contracts.contract_id = ?
        """,
        (normalized_cell, normalized_ref),
    ).fetchone()
    if row is None:
        raise RenewalConflictError(
            "Договор изменился или ячейка уже свободна. Обновите главный экран."
        )
    try:
        require_legacy_identity(row["extra_fields_json"], action="продлением")
    except ValueError as exc:
        raise RenewalConflictError(str(exc)) from exc
    old_end = _date(row["end_date"], label="текущую дату окончания")
    new_start = renewal_start_date(
        renewal_date=renewal_date, old_end_date=old_end
    )
    new_end, renewal_days = _new_period(
        new_start=new_start,
        new_end_value=new_end_date_value,
        renewal_days_value=renewal_days_value,
    )
    height_mm = int(row["height_mm"])
    price_per_day = _single_tariff(
        connection, height_mm=height_mm, days=renewal_days
    )
    penalty_days = renewal_penalty_days(
        renewal_date=renewal_date, old_end_date=old_end
    )
    try:
        penalty_rate = resolve_penalty_rate(connection, height_mm=height_mm)
    except PenaltyRateConfigurationError as exc:
        raise RenewalWriteError(str(exc)) from exc
    renewal_price = renewal_days * price_per_day
    penalty_amount = penalty_days * penalty_rate
    return RenewalQuote(
        contract_ref=str(row["contract_id"]),
        cell_number=str(row["cell_number"]),
        height_mm=height_mm,
        old_end_date=old_end.isoformat(),
        renewal_date=renewal_date.isoformat(),
        new_start_date=new_start.isoformat(),
        new_end_date=new_end.isoformat(),
        renewal_days=renewal_days,
        price_per_day=price_per_day,
        renewal_price=renewal_price,
        penalty_days=penalty_days,
        penalty_rate=penalty_rate,
        penalty_amount=penalty_amount,
        total_amount=renewal_price + penalty_amount,
    )


def calculate_renewal_quote(
    settings: Settings,
    *,
    cell_number: object,
    contract_ref: object,
    renewal_date: date,
    new_end_date_value: object | None = None,
    renewal_days_value: object | None = None,
) -> RenewalQuote:
    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            return calculate_renewal_quote_in_connection(
                connection,
                cell_number=cell_number,
                contract_ref=contract_ref,
                renewal_date=renewal_date,
                new_end_date_value=new_end_date_value,
                renewal_days_value=renewal_days_value,
            )
    except (RenewalValidationError, RenewalConflictError, RenewalWriteError):
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise RenewalReadError(NETWORK_ERROR_MESSAGE) from exc


def _result_from_row(
    row: sqlite3.Row,
    *,
    repeated: bool,
    backup_created: bool,
    warning: str | None = None,
) -> RenewalResult:
    renewal_price = int(row["renewal_price_minor"])
    penalty_amount = int(row["penalty_amount_minor"])
    return RenewalResult(
        renewal_id=str(row["renewal_id"]),
        contract_ref=str(row["contract_id"]),
        cell_number=str(row["cell_number"]),
        old_end_date=str(row["old_end_date"]),
        renewal_date=str(row["renewal_date"]),
        new_start_date=str(row["new_start_date"]),
        new_end_date=str(row["new_end_date"]),
        renewal_days=int(row["renewal_days"]),
        price_per_day=int(row["price_per_day_minor"]),
        renewal_price=renewal_price,
        penalty_days=int(row["penalty_days"]),
        penalty_rate=int(row["penalty_rate_minor"]),
        penalty_amount=penalty_amount,
        total_amount=renewal_price + penalty_amount,
        repeated=repeated,
        backup_created=backup_created,
        warning=warning,
    )


def _existing_result(
    connection: sqlite3.Connection,
    settings: Settings,
    *,
    operation_id: str,
    cell_number: str,
    contract_ref: str,
) -> RenewalResult | None:
    row = connection.execute(
        "SELECT * FROM archive.renewals WHERE operation_id = ?", (operation_id,)
    ).fetchone()
    if row is None:
        return None
    if row["cell_number"] != cell_number or row["contract_id"] != contract_ref:
        raise RenewalConflictError(
            "Этот идентификатор операции уже использован. Обновите форму."
        )
    backup_created = has_valid_backup_for_operation(settings, operation_id)
    warning = None if backup_created else (
        "Продление уже сохранено, но комплект резервной копии не найден. "
        "Сообщите администратору."
    )
    return _result_from_row(
        row, repeated=True, backup_created=backup_created, warning=warning
    )


def _audit_changes(quote: RenewalQuote) -> str:
    return json.dumps(
        {
            "cell_number": quote.cell_number,
            "old_end_date": quote.old_end_date,
            "new_start_date": quote.new_start_date,
            "new_end_date": quote.new_end_date,
            "renewal_days": quote.renewal_days,
            "price_per_day": quote.price_per_day,
            "renewal_price": quote.renewal_price,
            "penalty_days": quote.penalty_days,
            "penalty_rate": quote.penalty_rate,
            "penalty_amount": quote.penalty_amount,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _is_locked(error: BaseException) -> bool:
    return "locked" in str(error).lower() or "busy" in str(error).lower()


def renew_contract(
    settings: Settings,
    *,
    payload: object,
    employee: str,
    renewal_date: date,
    occurred_at: datetime,
    after_renewal_insert: Callable[[], None] | None = None,
) -> RenewalResult:
    if not isinstance(payload, dict):
        raise RenewalValidationError("Переданы неверные данные продления.")
    operation_id = _operation_id(payload.get("operation_id"))
    cell_number = _required_text(
        payload.get("cell_number"), label="Номер ячейки", maximum=50
    )
    contract_ref = _required_text(
        payload.get("contract_ref"), label="Идентификатор договора", maximum=100
    )
    expected_end = _date(
        payload.get("expected_end_date"), label="ожидаемую дату окончания"
    ).isoformat()
    employee_name = _required_text(employee, label="Сотрудник", maximum=128)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise RenewalValidationError("Время операции должно содержать часовой пояс.")
    timestamp = occurred_at.isoformat(timespec="seconds")
    phase = "opening"

    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            existing = _existing_result(
                connection,
                settings,
                operation_id=operation_id,
                cell_number=cell_number,
                contract_ref=contract_ref,
            )
            if existing is not None:
                connection.rollback()
                return existing
            current = connection.execute(
                """
                SELECT end_date FROM main.contracts
                WHERE contract_id = ? AND cell_number = ?
                """,
                (contract_ref, cell_number),
            ).fetchone()
            if current is None:
                raise RenewalConflictError(
                    "Договор изменился или ячейка уже свободна. Обновите главный экран."
                )
            if str(current["end_date"]) != expected_end:
                raise RenewalConflictError(
                    "Дата окончания уже изменилась. Обновите карточку и повторите расчёт."
                )
            quote = calculate_renewal_quote_in_connection(
                connection,
                cell_number=cell_number,
                contract_ref=contract_ref,
                renewal_date=renewal_date,
                new_end_date_value=payload.get("new_end_date"),
                renewal_days_value=payload.get("renewal_days"),
            )
            renewal_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO archive.renewals(
                    renewal_id, contract_id, cell_number,
                    old_end_date, renewal_date, new_start_date, new_end_date,
                    renewal_days, price_per_day_minor, renewal_price_minor,
                    penalty_days, penalty_rate_minor, penalty_amount_minor,
                    created_at, created_by, operation_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    renewal_id, quote.contract_ref, quote.cell_number,
                    quote.old_end_date, quote.renewal_date,
                    quote.new_start_date, quote.new_end_date, quote.renewal_days,
                    quote.price_per_day, quote.renewal_price, quote.penalty_days,
                    quote.penalty_rate, quote.penalty_amount, timestamp,
                    employee_name, operation_id,
                ),
            )
            if after_renewal_insert is not None:
                after_renewal_insert()
            cursor = connection.execute(
                """
                UPDATE main.contracts
                SET end_date = ?, updated_at = ?, updated_by = ?
                WHERE contract_id = ? AND cell_number = ? AND end_date = ?
                """,
                (
                    quote.new_end_date, timestamp, employee_name,
                    quote.contract_ref, quote.cell_number, quote.old_end_date,
                ),
            )
            if cursor.rowcount != 1:
                raise RenewalConflictError(
                    "Договор уже изменился. Обновите главный экран и повторите расчёт."
                )
            connection.execute(
                """
                INSERT INTO archive.log(
                    log_id, operation_id, occurred_at, employee, action,
                    contract_id, cell_number, changes_json
                ) VALUES(?, ?, ?, ?, 'contract.renewed', ?, ?, ?)
                """,
                (
                    str(uuid4()), operation_id, timestamp, employee_name,
                    quote.contract_ref, quote.cell_number, _audit_changes(quote),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT * FROM archive.renewals WHERE renewal_id = ?", (renewal_id,)
            ).fetchone()
            if saved is None:
                raise RenewalWriteUncertainError(UNCERTAIN_MESSAGE)
            phase = "backup"
            backup_created = True
            warning = None
            try:
                create_backup_pair(
                    connection,
                    settings,
                    operation_id=operation_id,
                    occurred_at=occurred_at,
                )
            except Exception:
                backup_created = False
                warning = (
                    "Продление сохранено, но резервную копию создать не удалось. "
                    "Сообщите администратору."
                )
            return _result_from_row(
                saved,
                repeated=False,
                backup_created=backup_created,
                warning=warning,
            )
    except (RenewalValidationError, RenewalConflictError, RenewalWriteUncertainError):
        raise
    except DatabaseCorruptionError as exc:
        raise RenewalNetworkError(str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise RenewalNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.IntegrityError as exc:
        if "operation_id" in str(exc):
            raise RenewalConflictError(
                "Операция уже была обработана. Обновите главный экран."
            ) from exc
        raise RenewalWriteError("Продление не сохранено. Изменения отменены.") from exc
    except (OSError, sqlite3.OperationalError) as exc:
        if phase in {"opening", "begin", "transaction"} and _is_locked(exc):
            raise RenewalBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise RenewalWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise RenewalNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except RenewalWriteError:
        raise
    except Exception as exc:
        if phase in {"committing", "verifying"}:
            raise RenewalWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise RenewalWriteError("Продление не сохранено. Изменения отменены.") from exc
