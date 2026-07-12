"""Read-only closing quotes and atomic active-to-archive transfers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from app.config import Settings
from app.db.connections import (
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_readonly,
    open_write,
    validate_database_pair,
)
from app.services.backups import create_backup_pair
from app.services.rental_calculator import parse_iso_date


BUSY_MESSAGE = "Другая операция записи ещё не завершена. Подождите и обновите данные."
UNCERTAIN_MESSAGE = (
    "Не удалось подтвердить результат закрытия. Не повторяйте операцию автоматически. "
    "Обновите главный экран и проверьте состояние ячейки."
)
REASON_LABELS = {
    "standard": None,
    "lost_key": "Потеря ключа",
}


class ClosureValidationError(ValueError):
    pass


class ClosureConflictError(RuntimeError):
    pass


class ClosureReadError(RuntimeError):
    pass


class ClosureBusyError(RuntimeError):
    pass


class ClosureNetworkError(RuntimeError):
    pass


class ClosureWriteError(RuntimeError):
    pass


class ClosureWriteUncertainError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ClosureQuote:
    contract_ref: str
    cell_number: str
    height_mm: int
    end_date: str
    close_date: str
    close_kind: str
    close_reason: str
    unused_days: int
    penalty_days: int
    penalty_rate: int
    penalty_amount: int
    deposit_amount: int
    deposit_refund: int
    rent_refund: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ClosureResult:
    contract_ref: str
    cell_number: str
    close_date: str
    close_kind: str
    close_reason: str
    unused_days: int
    penalty_days: int
    penalty_rate: int
    penalty_amount: int
    deposit_refund: int
    repeated: bool
    backup_created: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def closing_penalty_days(*, close_date: date, end_date: date) -> int:
    return max(0, (close_date - end_date).days)


def closing_kind(*, close_date: date, end_date: date) -> str:
    if close_date < end_date:
        return "early"
    if close_date == end_date:
        return "on_time"
    return "overdue"


def _required_text(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClosureValidationError(f"Укажите поле «{label}».")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ClosureValidationError(f"Поле «{label}» слишком длинное.")
    return normalized


def _operation_id(value: object) -> str:
    if not isinstance(value, str):
        raise ClosureValidationError("Не удалось подготовить операцию. Обновите форму.")
    try:
        return str(UUID(value.strip()))
    except (ValueError, AttributeError) as exc:
        raise ClosureValidationError(
            "Не удалось подготовить операцию. Обновите форму."
        ) from exc


def _reason_code(value: object) -> str:
    if not isinstance(value, str) or value not in REASON_LABELS:
        raise ClosureValidationError("Выберите причину закрытия договора.")
    return value


def _stored_date(value: object) -> date:
    try:
        return parse_iso_date(value, field_label="дату окончания")
    except ValueError as exc:
        raise ClosureWriteError("В договоре указана некорректная дата окончания.") from exc


def _penalty_rate(connection: sqlite3.Connection, *, height_mm: int) -> int:
    rows = connection.execute(
        """
        SELECT price_per_day_minor FROM tariffs
        WHERE height_mm = ? AND period_from_days = 1 AND period_to_days = 30
        """,
        (height_mm,),
    ).fetchall()
    if len(rows) != 1:
        raise ClosureWriteError("Не найден штрафной тариф до 30 дней.")
    rate = int(rows[0]["price_per_day_minor"])
    if rate < 0:
        raise ClosureWriteError("Штрафной тариф не может быть отрицательным.")
    return rate


def calculate_closure_quote_in_connection(
    connection: sqlite3.Connection,
    *,
    cell_number: object,
    contract_ref: object,
    close_date: date,
    reason_code: object,
) -> tuple[ClosureQuote, sqlite3.Row]:
    cell = _required_text(cell_number, label="Номер ячейки", maximum=50)
    ref = _required_text(contract_ref, label="Идентификатор договора", maximum=100)
    reason = _reason_code(reason_code)
    row = connection.execute(
        """
        SELECT contracts.*, cells.height_mm
        FROM contracts JOIN cells ON cells.number = contracts.cell_number
        WHERE contracts.cell_number = ? AND contracts.contract_id = ?
        """,
        (cell, ref),
    ).fetchone()
    if row is None:
        raise ClosureConflictError(
            "Ячейка уже свободна или договор изменился. Обновите главный экран."
        )
    end = _stored_date(row["end_date"])
    kind = closing_kind(close_date=close_date, end_date=end)
    unused_days = max(0, (end - close_date).days)
    penalty_days = closing_penalty_days(close_date=close_date, end_date=end)
    penalty_rate = _penalty_rate(connection, height_mm=int(row["height_mm"]))
    deposit = int(row["deposit_amount_minor"])
    if deposit < 0:
        raise ClosureWriteError("В договоре указан некорректный залог.")
    if reason == "lost_key":
        close_reason = "Потеря ключа"
        deposit_refund = 0
    else:
        close_reason = {
            "early": "Досрочное расторжение",
            "on_time": "Окончание срока",
            "overdue": "Закрытие после окончания срока",
        }[kind]
        deposit_refund = deposit
    quote = ClosureQuote(
        contract_ref=str(row["contract_id"]),
        cell_number=str(row["cell_number"]),
        height_mm=int(row["height_mm"]),
        end_date=end.isoformat(),
        close_date=close_date.isoformat(),
        close_kind=kind,
        close_reason=close_reason,
        unused_days=unused_days,
        penalty_days=penalty_days,
        penalty_rate=penalty_rate,
        penalty_amount=penalty_days * penalty_rate,
        deposit_amount=deposit,
        deposit_refund=deposit_refund,
    )
    return quote, row


def calculate_closure_quote(
    settings: Settings,
    *,
    cell_number: object,
    contract_ref: object,
    close_date: date,
    reason_code: object,
) -> ClosureQuote:
    try:
        paths = validate_database_pair(settings)
        with open_readonly(paths.working, busy_timeout_ms=settings.busy_timeout_ms) as con:
            quote, _row = calculate_closure_quote_in_connection(
                con,
                cell_number=cell_number,
                contract_ref=contract_ref,
                close_date=close_date,
                reason_code=reason_code,
            )
            return quote
    except (ClosureValidationError, ClosureConflictError, ClosureWriteError):
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise ClosureReadError(NETWORK_ERROR_MESSAGE) from exc


def _result_from_row(
    row: sqlite3.Row,
    *,
    repeated: bool,
    backup_created: bool,
    warning: str | None = None,
) -> ClosureResult:
    return ClosureResult(
        contract_ref=str(row["contract_id"]),
        cell_number=str(row["cell_number"]),
        close_date=str(row["close_date"]),
        close_kind=str(row["close_kind"]),
        close_reason=str(row["close_reason"]),
        unused_days=int(row["unused_days"]),
        penalty_days=int(row["penalty_days"]),
        penalty_rate=int(row["penalty_rate_minor"]),
        penalty_amount=int(row["penalty_amount_minor"]),
        deposit_refund=int(row["deposit_refund_minor"]),
        repeated=repeated,
        backup_created=backup_created,
        warning=warning,
    )


def _existing_result(
    connection: sqlite3.Connection,
    settings: Settings,
    *, operation_id: str, cell_number: str, contract_ref: str,
) -> ClosureResult | None:
    row = connection.execute(
        "SELECT * FROM archive.contracts_archive WHERE operation_id = ?",
        (operation_id,),
    ).fetchone()
    if row is None:
        return None
    if row["cell_number"] != cell_number or row["contract_id"] != contract_ref:
        raise ClosureConflictError("Этот идентификатор операции уже использован.")
    directory = settings.database_directory / "backups"
    backed_up = (
        any(directory.glob(f"*_{operation_id}.working.sqlite3"))
        and any(directory.glob(f"*_{operation_id}.archive.sqlite3"))
    )
    warning = None if backed_up else (
        "Закрытие уже сохранено, но комплект резервной копии не найден. "
        "Сообщите администратору."
    )
    return _result_from_row(
        row, repeated=True, backup_created=backed_up, warning=warning
    )


def _audit(quote: ClosureQuote) -> str:
    return json.dumps(
        {
            "cell_number": quote.cell_number,
            "close_date": quote.close_date,
            "close_kind": quote.close_kind,
            "close_reason": quote.close_reason,
            "unused_days": quote.unused_days,
            "penalty_days": quote.penalty_days,
            "penalty_rate": quote.penalty_rate,
            "penalty_amount": quote.penalty_amount,
            "deposit_refund": quote.deposit_refund,
            "rent_refund": 0,
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _is_locked(error: BaseException) -> bool:
    return "locked" in str(error).lower() or "busy" in str(error).lower()


def close_contract(
    settings: Settings,
    *,
    payload: object,
    employee: str,
    close_date: date,
    occurred_at: datetime,
    after_archive_insert: Callable[[], None] | None = None,
    before_active_delete: Callable[[], None] | None = None,
) -> ClosureResult:
    if not isinstance(payload, dict):
        raise ClosureValidationError("Переданы неверные данные закрытия.")
    operation_id = _operation_id(payload.get("operation_id"))
    cell = _required_text(payload.get("cell_number"), label="Номер ячейки", maximum=50)
    ref = _required_text(
        payload.get("contract_ref"), label="Идентификатор договора", maximum=100
    )
    reason = _reason_code(payload.get("reason_code"))
    try:
        expected_end = parse_iso_date(
            payload.get("expected_end_date"), field_label="ожидаемую дату окончания"
        ).isoformat()
    except ValueError as exc:
        raise ClosureValidationError(str(exc)) from exc
    employee_name = _required_text(employee, label="Сотрудник", maximum=128)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ClosureValidationError("Время операции должно содержать часовой пояс.")
    timestamp = occurred_at.isoformat(timespec="seconds")
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            existing = _existing_result(
                connection, settings, operation_id=operation_id,
                cell_number=cell, contract_ref=ref,
            )
            if existing is not None:
                connection.rollback()
                return existing
            current = connection.execute(
                "SELECT end_date FROM main.contracts WHERE contract_id=? AND cell_number=?",
                (ref, cell),
            ).fetchone()
            if current is None:
                raise ClosureConflictError(
                    "Ячейка уже свободна или договор изменился. Обновите главный экран."
                )
            if str(current["end_date"]) != expected_end:
                raise ClosureConflictError(
                    "Дата окончания уже изменилась. Обновите карточку и повторите расчёт."
                )
            quote, contract = calculate_closure_quote_in_connection(
                connection, cell_number=cell, contract_ref=ref,
                close_date=close_date, reason_code=reason,
            )
            connection.execute(
                """
                INSERT INTO archive.contracts_archive(
                    contract_id, cell_number, client_full_name,
                    id_card_number, id_card_issuer,
                    id_card_issue_date, account_number, extra_fields_json,
                    start_date, end_date, rent_days, price_per_day_minor,
                    rent_price_minor, deposit_amount_minor, created_at, created_by,
                    updated_at, updated_by, closed_at, close_date, close_reason,
                    close_kind, unused_days, penalty_days, penalty_rate_minor,
                    penalty_amount_minor, deposit_refund_minor, closed_by, operation_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                         ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(contract[key] for key in (
                    "contract_id", "cell_number", "client_full_name",
                    "id_card_number", "id_card_issuer",
                    "id_card_issue_date", "account_number", "extra_fields_json",
                    "start_date", "end_date", "rent_days", "price_per_day_minor",
                    "rent_price_minor", "deposit_amount_minor", "created_at", "created_by",
                    "updated_at", "updated_by",
                )) + (
                    timestamp, quote.close_date, quote.close_reason, quote.close_kind,
                    quote.unused_days, quote.penalty_days, quote.penalty_rate,
                    quote.penalty_amount, quote.deposit_refund, employee_name, operation_id,
                ),
            )
            if after_archive_insert is not None:
                after_archive_insert()
            connection.execute(
                """
                INSERT INTO archive.log(
                    log_id, operation_id, occurred_at, employee, action,
                    contract_id, cell_number, changes_json
                ) VALUES(?, ?, ?, ?, 'contract.closed', ?, ?, ?)
                """,
                (str(uuid4()), operation_id, timestamp, employee_name, ref, cell, _audit(quote)),
            )
            if before_active_delete is not None:
                before_active_delete()
            deleted = connection.execute(
                "DELETE FROM main.contracts WHERE contract_id=? AND cell_number=? AND end_date=?",
                (ref, cell, expected_end),
            )
            if deleted.rowcount != 1:
                raise ClosureConflictError("Договор уже изменился. Обновите главный экран.")
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT * FROM archive.contracts_archive WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            active = connection.execute(
                "SELECT 1 FROM main.contracts WHERE contract_id=?", (ref,)
            ).fetchone()
            if saved is None or active is not None:
                raise ClosureWriteUncertainError(UNCERTAIN_MESSAGE)
            phase = "backup"
            backed_up = True
            warning = None
            try:
                create_backup_pair(
                    connection, settings, operation_id=operation_id, occurred_at=occurred_at
                )
            except Exception:
                backed_up = False
                warning = (
                    "Договор закрыт, но резервную копию создать не удалось. "
                    "Сообщите администратору."
                )
            return _result_from_row(
                saved, repeated=False, backup_created=backed_up, warning=warning
            )
    except (ClosureValidationError, ClosureConflictError, ClosureWriteUncertainError):
        raise
    except DatabaseUnavailableError as exc:
        raise ClosureNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.IntegrityError as exc:
        if "operation_id" in str(exc) or "contracts_archive.contract_id" in str(exc):
            raise ClosureConflictError("Операция закрытия уже была выполнена.") from exc
        raise ClosureWriteError("Договор не закрыт. Изменения отменены.") from exc
    except (OSError, sqlite3.OperationalError) as exc:
        if phase in {"opening", "begin", "transaction"} and _is_locked(exc):
            raise ClosureBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise ClosureWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise ClosureNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except ClosureWriteError:
        raise
    except Exception as exc:
        if phase in {"committing", "verifying"}:
            raise ClosureWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise ClosureWriteError("Договор не закрыт. Изменения отменены.") from exc
