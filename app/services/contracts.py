"""Atomic creation of active rental contracts and their audit record."""

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
    open_write,
)
from app.services.backups import create_backup_pair
from app.services.rental_calculator import (
    CellUnavailableError,
    RentalDataError,
    RentalQuote,
    RentalValidationError,
    calculate_rental_quote_in_connection,
    parse_iso_date,
)


BUSY_MESSAGE = (
    "Другая операция записи ещё не завершена. Подождите и обновите данные."
)
UNCERTAIN_MESSAGE = (
    "Не удалось подтвердить результат сохранения. Не повторяйте операцию автоматически. "
    "Обновите главный экран и проверьте состояние ячейки."
)


class ContractValidationError(ValueError):
    """Required contract fields are absent or malformed."""


class ContractConflictError(RuntimeError):
    """The cell or operation can no longer be used for this contract."""


class ContractBusyError(RuntimeError):
    """Another writer held the database beyond the configured timeout."""


class ContractNetworkError(RuntimeError):
    """The database pair could not be reached before a write began."""


class ContractWriteError(RuntimeError):
    """The transaction failed and was rolled back."""


class ContractWriteUncertainError(RuntimeError):
    """The connection failed while commit/result verification was in progress."""


@dataclass(frozen=True, slots=True)
class ContractData:
    operation_id: str
    cell_number: str
    client_full_name: str
    id_card_number: str
    id_card_issuer: str
    id_card_issue_date: str
    account_number: str
    start_date: str
    end_date: str
    rent_days: int


@dataclass(frozen=True, slots=True)
class ContractCreationResult:
    contract_id: str
    cell_number: str
    start_date: str
    end_date: str
    rent_days: int
    price_per_day: int
    rent_price: int
    deposit_amount: int
    repeated: bool
    backup_created: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _required_text(
    value: object,
    *,
    label: str,
    maximum: int,
    collapse_spaces: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"Укажите поле «{label}».")
    normalized = " ".join(value.split()) if collapse_spaces else value.strip()
    if not normalized:
        raise ContractValidationError(f"Укажите поле «{label}».")
    if len(normalized) > maximum:
        raise ContractValidationError(f"Поле «{label}» слишком длинное.")
    return normalized


def _optional_date(value: object, *, label: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        return parse_iso_date(value, field_label=label).isoformat()
    except RentalValidationError as exc:
        raise ContractValidationError(str(exc)) from exc


def _operation_id(value: object) -> str:
    if not isinstance(value, str):
        raise ContractValidationError("Не удалось подготовить операцию. Обновите форму.")
    try:
        return str(UUID(value.strip()))
    except (ValueError, AttributeError) as exc:
        raise ContractValidationError(
            "Не удалось подготовить операцию. Обновите форму."
        ) from exc


def validate_contract_payload(payload: object) -> ContractData:
    if not isinstance(payload, dict):
        raise ContractValidationError("Переданы неверные данные договора.")
    try:
        rent_days = payload.get("rent_days")
        if isinstance(rent_days, bool) or not isinstance(rent_days, int):
            raise ContractValidationError("Количество дней должно быть целым числом.")
        if rent_days < 1:
            raise ContractValidationError("Количество дней должно быть не меньше 1.")
        start_date = parse_iso_date(
            payload.get("start_date"), field_label="дату начала"
        ).isoformat()
        end_date = parse_iso_date(
            payload.get("end_date"), field_label="дату окончания"
        ).isoformat()
        issue_date = parse_iso_date(
            payload.get("id_card_issue_date"),
            field_label="дату выдачи ID-карты",
        ).isoformat()
    except RentalValidationError as exc:
        raise ContractValidationError(str(exc)) from exc

    return ContractData(
        operation_id=_operation_id(payload.get("operation_id")),
        cell_number=_required_text(
            payload.get("cell_number"), label="Номер ячейки", maximum=50
        ),
        client_full_name=_required_text(
            payload.get("client_full_name"),
            label="ФИО клиента",
            maximum=200,
            collapse_spaces=True,
        ),
        id_card_number=_required_text(
            payload.get("id_card_number"), label="Серия и номер ID-карты", maximum=100
        ),
        id_card_issuer=_required_text(
            payload.get("id_card_issuer"), label="Орган выдачи", maximum=200
        ),
        id_card_issue_date=issue_date,
        account_number=_required_text(
            payload.get("account_number"), label="Номер счёта", maximum=100
        ),
        start_date=start_date,
        end_date=end_date,
        rent_days=rent_days,
    )


def _result_from_row(
    row: sqlite3.Row,
    *,
    repeated: bool,
    backup_created: bool,
    warning: str | None = None,
) -> ContractCreationResult:
    return ContractCreationResult(
        contract_id=str(row["contract_id"]),
        cell_number=str(row["cell_number"]),
        start_date=str(row["start_date"]),
        end_date=str(row["end_date"]),
        rent_days=int(row["rent_days"]),
        price_per_day=int(row["price_per_day_minor"]),
        rent_price=int(row["rent_price_minor"]),
        deposit_amount=int(row["deposit_amount_minor"]),
        repeated=repeated,
        backup_created=backup_created,
        warning=warning,
    )


def _existing_operation_result(
    connection: sqlite3.Connection, settings: Settings, data: ContractData
) -> ContractCreationResult | None:
    operation = connection.execute(
        """
        SELECT action, contract_id, cell_number
        FROM archive.log
        WHERE operation_id = ?
        """,
        (data.operation_id,),
    ).fetchone()
    if operation is None:
        return None
    if (
        operation["action"] != "contract.created"
        or operation["cell_number"] != data.cell_number
    ):
        raise ContractConflictError(
            "Этот идентификатор операции уже использован. Обновите форму."
        )
    row = connection.execute(
        "SELECT * FROM contracts WHERE contract_id = ? AND cell_number = ?",
        (operation["contract_id"], data.cell_number),
    ).fetchone()
    if row is None:
        raise ContractWriteUncertainError(UNCERTAIN_MESSAGE)
    backup_directory = settings.database_directory / "backups"
    working_backup = any(
        backup_directory.glob(f"*_{data.operation_id}.working.sqlite3")
    )
    archive_backup = any(
        backup_directory.glob(f"*_{data.operation_id}.archive.sqlite3")
    )
    backup_created = working_backup and archive_backup
    warning = None
    if not backup_created:
        warning = (
            "Договор уже был сохранён, но комплект резервной копии не найден. "
            "Сообщите администратору."
        )
    return _result_from_row(
        row,
        repeated=True,
        backup_created=backup_created,
        warning=warning,
    )


def _audit_changes(contract_id: str, quote: RentalQuote) -> str:
    return json.dumps(
        {
            "contract_id": contract_id,
            "cell_number": quote.cell_number,
            "start_date": quote.start_date,
            "end_date": quote.end_date,
            "rent_days": quote.rent_days,
            "price_per_day": quote.price_per_day,
            "rent_price": quote.rent_price,
            "deposit_amount": quote.deposit_amount,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _is_locked(error: BaseException) -> bool:
    return "locked" in str(error).lower() or "busy" in str(error).lower()


def create_contract(
    settings: Settings,
    *,
    payload: object,
    employee: str,
    occurred_at: datetime,
    as_of_date: date | None = None,
    after_contract_insert: Callable[[], None] | None = None,
) -> ContractCreationResult:
    """Create an active contract and audit row in one short transaction."""

    data = validate_contract_payload(payload)
    employee_name = _required_text(
        employee, label="Сотрудник", maximum=128, collapse_spaces=True
    )
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ContractValidationError("Время операции должно содержать часовой пояс.")
    timestamp = occurred_at.isoformat(timespec="seconds")
    current_date = as_of_date or occurred_at.date()
    if date.fromisoformat(data.id_card_issue_date) > current_date:
        raise ContractValidationError("Дата выдачи ID-карты не может быть в будущем.")
    phase = "opening"

    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            existing = _existing_operation_result(connection, settings, data)
            if existing is not None:
                connection.rollback()
                return existing

            try:
                quote = calculate_rental_quote_in_connection(
                    connection,
                    cell_number=data.cell_number,
                    start_date_value=data.start_date,
                    end_date_value=data.end_date,
                    rent_days_value=data.rent_days,
                    as_of_date=current_date,
                )
            except CellUnavailableError as exc:
                raise ContractConflictError(str(exc)) from exc
            except RentalValidationError as exc:
                raise ContractValidationError(str(exc)) from exc

            contract_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO contracts(
                    contract_id, cell_number, client_full_name,
                    id_card_number, id_card_issuer,
                    id_card_issue_date, account_number, extra_fields_json,
                    start_date, end_date, rent_days, price_per_day_minor,
                    rent_price_minor, deposit_amount_minor, created_at, created_by,
                    updated_at, updated_by
                ) VALUES(?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract_id,
                    quote.cell_number,
                    data.client_full_name,
                    data.id_card_number,
                    data.id_card_issuer,
                    data.id_card_issue_date,
                    data.account_number,
                    quote.start_date,
                    quote.end_date,
                    quote.rent_days,
                    quote.price_per_day,
                    quote.rent_price,
                    quote.deposit_amount,
                    timestamp,
                    employee_name,
                    timestamp,
                    employee_name,
                ),
            )
            if after_contract_insert is not None:
                after_contract_insert()
            connection.execute(
                """
                INSERT INTO archive.log(
                    log_id, operation_id, occurred_at, employee, action,
                    contract_id, cell_number, changes_json
                ) VALUES(?, ?, ?, ?, 'contract.created', ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    data.operation_id,
                    timestamp,
                    employee_name,
                    contract_id,
                    quote.cell_number,
                    _audit_changes(contract_id, quote),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT * FROM contracts WHERE contract_id = ?", (contract_id,)
            ).fetchone()
            if saved is None:
                raise ContractWriteUncertainError(UNCERTAIN_MESSAGE)

            phase = "backup"
            warning = None
            backup_created = True
            try:
                create_backup_pair(
                    connection,
                    settings,
                    operation_id=data.operation_id,
                    occurred_at=occurred_at,
                )
            except Exception:
                backup_created = False
                warning = (
                    "Договор сохранён, но резервную копию создать не удалось. "
                    "Сообщите администратору."
                )
            return _result_from_row(
                saved,
                repeated=False,
                backup_created=backup_created,
                warning=warning,
            )
    except ContractValidationError:
        raise
    except ContractConflictError:
        raise
    except ContractWriteUncertainError:
        raise
    except DatabaseUnavailableError as exc:
        raise ContractNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.IntegrityError as exc:
        if (
            "contracts.cell_number" in str(exc)
            or "UNIQUE constraint failed" in str(exc)
        ):
            raise ContractConflictError(
                "Ячейка уже занята. Обновите главный экран и выберите свободную ячейку."
            ) from exc
        raise ContractWriteError("Договор не сохранён. Изменения отменены.") from exc
    except (OSError, sqlite3.OperationalError) as exc:
        if phase in {"opening", "begin", "transaction"} and _is_locked(exc):
            raise ContractBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise ContractWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise ContractNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except RentalDataError as exc:
        raise ContractWriteError(
            "Договор не сохранён: тарифы или денежные настройки некорректны."
        ) from exc
    except Exception as exc:
        if phase in {"committing", "verifying"}:
            raise ContractWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise ContractWriteError("Договор не сохранён. Изменения отменены.") from exc
