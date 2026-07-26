"""Atomic WhatsApp reminder registration and message preparation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
import sqlite3
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from app.config import Settings
from app.db.connections import (
    DatabaseCorruptionError,
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_write,
)
from app.services.backups import create_backup_pair, has_valid_backup_for_operation
from app.services.phone_numbers import (
    PhoneNumberValidationError,
    normalize_whatsapp_phone,
)
from app.services.statuses import CellStatus, calculate_status


BANK_NAME = "ЗАО АКБ «Толубай»"
BUSY_MESSAGE = "База сейчас занята другим сотрудником. Повторите позже."
UNCERTAIN_MESSAGE = (
    "Не удалось подтвердить сохранение оповещения. Не нажимайте повторно автоматически. "
    "Обновите экран и проверьте статус оповещения."
)


class ReminderValidationError(ValueError):
    """The reminder request or stored client data is malformed."""


class ReminderConflictError(RuntimeError):
    """The active contract is no longer eligible for a reminder."""


class ReminderBusyError(RuntimeError):
    """Another writer held the database beyond the configured timeout."""


class ReminderNetworkError(RuntimeError):
    """The shared database pair could not be reached."""


class ReminderWriteError(RuntimeError):
    """The reminder transaction failed and was rolled back."""


class ReminderWriteUncertainError(RuntimeError):
    """The commit result could not be confirmed."""


@dataclass(frozen=True, slots=True)
class ReminderRequest:
    operation_id: str
    cell_number: str
    contract_ref: str


@dataclass(frozen=True, slots=True)
class ReminderResult:
    contract_ref: str
    cell_number: str
    status: str
    last_reminded_at: str
    reminder_count: int
    reminder_status: str
    whatsapp_url: str
    repeated: bool
    backup_created: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReminderValidationError(f"Не указано поле «{label}».")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ReminderValidationError(f"Поле «{label}» слишком длинное.")
    return normalized


def validate_reminder_payload(payload: object) -> ReminderRequest:
    if not isinstance(payload, dict):
        raise ReminderValidationError("Переданы неверные данные напоминания.")
    operation_id = _text(payload.get("operation_id"), label="Операция", maximum=100)
    try:
        operation_id = str(UUID(operation_id))
    except ValueError as exc:
        raise ReminderValidationError("Неверный идентификатор операции.") from exc
    return ReminderRequest(
        operation_id=operation_id,
        cell_number=_text(
            payload.get("cell_number"), label="Номер ячейки", maximum=50
        ),
        contract_ref=_text(
            payload.get("contract_ref"), label="Договор", maximum=100
        ),
    )


def client_greeting_name(full_name: str) -> str:
    """Use first name and patronymic for the approved greeting."""

    parts = full_name.split()
    if len(parts) >= 3:
        return " ".join(parts[1:3])
    return " ".join(parts)


def build_reminder_message(
    *,
    status: str,
    client_full_name: str,
    cell_number: str,
    end_date: date,
    bank_name: str = BANK_NAME,
) -> str:
    greeting = client_greeting_name(client_full_name)
    formatted_end = end_date.strftime("%d.%m.%Y")
    if status == CellStatus.EXPIRING.value:
        body = (
            f"Напоминаем, что срок аренды вашей банковской сейфовой ячейки "
            f"№{cell_number} истекает {formatted_end}.\n\n"
            "Для продления аренды или освобождения ячейки просим обратиться "
            "в отделение банка."
        )
    elif status == CellStatus.OVERDUE.value:
        body = (
            f"Срок аренды вашей банковской сейфовой ячейки №{cell_number} "
            f"истёк {formatted_end}.\n\n"
            "Просим обратиться в отделение банка для продления аренды или "
            "освобождения ячейки. За период просрочки начисляется штраф "
            "согласно условиям договора."
        )
    else:
        raise ReminderConflictError(
            "Напоминание доступно только для истекающей или просроченной аренды."
        )
    return f"Здравствуйте, {greeting}!\n\n{body}\n\nС уважением, {bank_name}."


def reminder_status_text(
    last_reminded_at: str | None,
    *,
    as_of: datetime,
) -> str:
    if not last_reminded_at:
        return "Не оповещён"
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ReminderValidationError("Текущее время должно содержать часовой пояс.")
    try:
        reminded_at = datetime.fromisoformat(last_reminded_at)
    except (TypeError, ValueError) as exc:
        raise ReminderValidationError(
            "В базе сохранено некорректное время оповещения."
        ) from exc
    if reminded_at.tzinfo is None or reminded_at.utcoffset() is None:
        raise ReminderValidationError(
            "В базе сохранено некорректное время оповещения."
        )
    local_reminded_at = reminded_at.astimezone(as_of.tzinfo)
    days_ago = (as_of.date() - local_reminded_at.date()).days
    time_text = local_reminded_at.strftime("%H:%M")
    if days_ago <= 0:
        return f"Оповещён сегодня в {time_text}"
    if days_ago == 1:
        return f"Оповещён вчера в {time_text}"
    return f"Оповещён {days_ago} дней назад"


def _threshold(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM main.config WHERE key='expiring_soon_days'"
    ).fetchone()
    try:
        value = int(row["value"])
    except (TypeError, ValueError) as exc:
        raise ReminderWriteError(
            "Не удалось определить статус аренды. Проверьте настройки."
        ) from exc
    if value < 0:
        raise ReminderWriteError(
            "Не удалось определить статус аренды. Проверьте настройки."
        )
    return value


def _result_from_row(
    row: sqlite3.Row,
    *,
    status: str,
    occurred_at: datetime,
    repeated: bool,
    backup_created: bool,
    warning: str | None = None,
) -> ReminderResult:
    try:
        phone = normalize_whatsapp_phone(row["client_phone"])
        end_date = date.fromisoformat(str(row["end_date"]))
    except PhoneNumberValidationError as exc:
        raise ReminderValidationError(str(exc)) from exc
    except ValueError as exc:
        raise ReminderWriteError("В договоре сохранена некорректная дата окончания.") from exc
    message = build_reminder_message(
        status=status,
        client_full_name=str(row["client_full_name"]),
        cell_number=str(row["cell_number"]),
        end_date=end_date,
    )
    last_reminded_at = str(row["last_reminded_at"])
    return ReminderResult(
        contract_ref=str(row["contract_id"]),
        cell_number=str(row["cell_number"]),
        status=status,
        last_reminded_at=last_reminded_at,
        reminder_count=int(row["reminder_count"]),
        reminder_status=reminder_status_text(last_reminded_at, as_of=occurred_at),
        whatsapp_url=f"https://wa.me/{phone}?text={quote(message, safe='')}",
        repeated=repeated,
        backup_created=backup_created,
        warning=warning,
    )


def _is_locked(error: BaseException) -> bool:
    return "locked" in str(error).lower() or "busy" in str(error).lower()


def send_reminder(
    settings: Settings,
    *,
    payload: object,
    employee: str,
    occurred_at: datetime,
    as_of_date: date | None = None,
) -> ReminderResult:
    """Register a reminder, then return the WhatsApp link for this exact contract."""

    data = validate_reminder_payload(payload)
    employee_name = _text(employee, label="Сотрудник", maximum=128)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ReminderValidationError("Время операции должно содержать часовой пояс.")
    current_date = as_of_date or occurred_at.date()
    timestamp = occurred_at.isoformat(timespec="seconds")
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            prior = connection.execute(
                """
                SELECT action, contract_id, cell_number, changes_json
                FROM archive.log
                WHERE operation_id=?
                """,
                (data.operation_id,),
            ).fetchone()
            row = connection.execute(
                """
                SELECT contract_id, cell_number, client_full_name, client_phone,
                       end_date, last_reminded_at, reminder_count
                FROM main.contracts
                WHERE contract_id=? AND cell_number=?
                """,
                (data.contract_ref, data.cell_number),
            ).fetchone()
            if row is None:
                raise ReminderConflictError(
                    "Договор изменён или закрыт. Обновите главный экран."
                )
            try:
                end_date = date.fromisoformat(str(row["end_date"]))
            except ValueError as exc:
                raise ReminderWriteError(
                    "В договоре сохранена некорректная дата окончания."
                ) from exc
            status = calculate_status(
                end_date=end_date,
                as_of_date=current_date,
                expiring_soon_days=_threshold(connection),
            ).status.value
            if status not in {
                CellStatus.EXPIRING.value,
                CellStatus.OVERDUE.value,
            }:
                raise ReminderConflictError(
                    "Напоминание доступно только для истекающей или просроченной аренды."
                )
            try:
                normalize_whatsapp_phone(row["client_phone"])
            except PhoneNumberValidationError as exc:
                raise ReminderValidationError(str(exc)) from exc

            if prior is not None:
                if (
                    prior["action"] != "contract.reminded"
                    or prior["contract_id"] != data.contract_ref
                    or prior["cell_number"] != data.cell_number
                ):
                    raise ReminderConflictError(
                        "Этот идентификатор операции уже использован. Обновите экран."
                    )
                connection.rollback()
                backup_created = has_valid_backup_for_operation(
                    settings, data.operation_id
                )
                warning = None if backup_created else (
                    "Оповещение уже было сохранено, но резервная копия не найдена. "
                    "Сообщите администратору."
                )
                return _result_from_row(
                    row,
                    status=status,
                    occurred_at=occurred_at,
                    repeated=True,
                    backup_created=backup_created,
                    warning=warning,
                )

            updated = connection.execute(
                """
                UPDATE main.contracts
                SET last_reminded_at=?,
                    reminder_count=reminder_count + 1,
                    updated_at=?,
                    updated_by=?
                WHERE contract_id=? AND cell_number=?
                """,
                (
                    timestamp,
                    timestamp,
                    employee_name,
                    data.contract_ref,
                    data.cell_number,
                ),
            )
            if updated.rowcount != 1:
                raise ReminderConflictError(
                    "Договор изменён или закрыт. Обновите главный экран."
                )
            saved = connection.execute(
                """
                SELECT contract_id, cell_number, client_full_name, client_phone,
                       end_date, last_reminded_at, reminder_count
                FROM main.contracts
                WHERE contract_id=? AND cell_number=?
                """,
                (data.contract_ref, data.cell_number),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO archive.log(
                    log_id, operation_id, occurred_at, employee, action,
                    contract_id, cell_number, changes_json
                ) VALUES(?, ?, ?, ?, 'contract.reminded', ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    data.operation_id,
                    timestamp,
                    employee_name,
                    data.contract_ref,
                    data.cell_number,
                    json.dumps(
                        {
                            "status": status,
                            "last_reminded_at": timestamp,
                            "reminder_count": int(saved["reminder_count"]),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            verified = connection.execute(
                """
                SELECT contract_id, cell_number, client_full_name, client_phone,
                       end_date, last_reminded_at, reminder_count
                FROM main.contracts
                WHERE contract_id=? AND cell_number=?
                """,
                (data.contract_ref, data.cell_number),
            ).fetchone()
            if verified is None or str(verified["last_reminded_at"]) != timestamp:
                raise ReminderWriteUncertainError(UNCERTAIN_MESSAGE)
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
                    "Оповещение сохранено, но резервную копию создать не удалось. "
                    "Сообщите администратору."
                )
            return _result_from_row(
                verified,
                status=status,
                occurred_at=occurred_at,
                repeated=False,
                backup_created=backup_created,
                warning=warning,
            )
    except (ReminderValidationError, ReminderConflictError, ReminderWriteUncertainError):
        raise
    except DatabaseCorruptionError as exc:
        raise ReminderNetworkError(str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise ReminderNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.OperationalError) as exc:
        if phase in {"opening", "begin", "transaction"} and _is_locked(exc):
            raise ReminderBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise ReminderWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise ReminderNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.Error as exc:
        if phase in {"committing", "verifying"}:
            raise ReminderWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise ReminderWriteError(
            "Оповещение не сохранено. Изменения отменены."
        ) from exc
    except ReminderWriteError:
        raise
    except Exception as exc:
        if phase in {"committing", "verifying"}:
            raise ReminderWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise ReminderWriteError(
            "Оповещение не сохранено. Изменения отменены."
        ) from exc
