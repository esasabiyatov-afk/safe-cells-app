"""Safe editing of non-financial active-contract details."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from app.config import Settings
from app.db.connections import DatabaseUnavailableError, NETWORK_ERROR_MESSAGE, open_write
from app.services.backups import create_backup_pair


BUSY_MESSAGE = "База сейчас занята другим сотрудником. Повторите позже."
UNCERTAIN_MESSAGE = "Не удалось подтвердить результат записи. Обновите экран и проверьте данные."


class EditingValidationError(ValueError): pass
class EditingConflictError(RuntimeError): pass
class EditingBusyError(RuntimeError): pass
class EditingNetworkError(RuntimeError): pass
class EditingWriteError(RuntimeError): pass
class EditingWriteUncertainError(RuntimeError): pass


@dataclass(frozen=True, slots=True)
class EditingData:
    operation_id: str
    contract_ref: str
    cell_number: str
    client_full_name: str
    id_card_number: str
    id_card_issuer: str
    id_card_expiry_date: str
    account_number: str


@dataclass(frozen=True, slots=True)
class EditingResult:
    contract_ref: str
    cell_number: str
    repeated: bool
    backup_created: bool
    warning: str | None

    def to_dict(self) -> dict[str, Any]: return asdict(self)


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EditingValidationError(f"Поле «{label}» обязательно.")
    result = " ".join(value.split())
    if len(result) > maximum:
        raise EditingValidationError(f"Поле «{label}» слишком длинное.")
    return result


def validate_editing_payload(payload: object) -> EditingData:
    if not isinstance(payload, dict):
        raise EditingValidationError("Переданы неверные данные формы.")
    allowed = {"operation_id", "contract_ref", "cell_number", "client_full_name", "id_card_number", "id_card_issuer", "id_card_expiry_date", "account_number"}
    if set(payload) - allowed:
        raise EditingValidationError("Попытка изменить запрещённое поле.")
    operation_id = _text(payload.get("operation_id"), "Операция", 100)
    try: UUID(operation_id)
    except ValueError as exc: raise EditingValidationError("Неверный идентификатор операции.") from exc
    expiry = _text(payload.get("id_card_expiry_date"), "Дата окончания ID-карты", 10)
    try: date.fromisoformat(expiry)
    except ValueError as exc: raise EditingValidationError("Укажите корректную дату окончания ID-карты.") from exc
    return EditingData(
        operation_id=operation_id,
        contract_ref=_text(payload.get("contract_ref"), "Договор", 100),
        cell_number=_text(payload.get("cell_number"), "Номер ячейки", 50),
        client_full_name=_text(payload.get("client_full_name"), "ФИО клиента", 200),
        id_card_number=_text(payload.get("id_card_number"), "Номер ID-карты", 100),
        id_card_issuer=_text(payload.get("id_card_issuer"), "Орган выдачи", 200),
        id_card_expiry_date=expiry,
        account_number=_text(payload.get("account_number"), "Номер счёта", 100),
    )


def edit_contract(settings: Settings, *, payload: object, employee: str, occurred_at: datetime) -> EditingResult:
    data = validate_editing_payload(payload)
    employee_name = _text(employee, "Сотрудник", 128)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise EditingValidationError("Время операции должно содержать часовой пояс.")
    timestamp = occurred_at.isoformat(timespec="seconds")
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"; connection.execute("BEGIN IMMEDIATE"); phase = "transaction"
            previous = connection.execute(
                "SELECT contract_id FROM archive.log WHERE operation_id = ? AND action = 'contract.edited'",
                (data.operation_id,),
            ).fetchone()
            if previous:
                if str(previous["contract_id"]) != data.contract_ref:
                    raise EditingConflictError("Идентификатор операции уже использован.")
                connection.rollback()
                return EditingResult(data.contract_ref, data.cell_number, True, False, None)
            row = connection.execute(
                "SELECT * FROM contracts WHERE contract_id = ? AND cell_number = ?",
                (data.contract_ref, data.cell_number),
            ).fetchone()
            if row is None:
                raise EditingConflictError("Договор изменён или закрыт. Обновите экран.")
            fields = ("client_full_name", "id_card_number", "id_card_issuer", "id_card_expiry_date", "account_number")
            new_values = {name: getattr(data, name) for name in fields}
            changes = {name: {"old": str(row[name]), "new": new_values[name]} for name in fields if str(row[name]) != new_values[name]}
            if not changes:
                raise EditingValidationError("Данные не изменены.")
            connection.execute(
                """UPDATE contracts SET client_full_name=?, id_card_number=?, id_card_issuer=?,
                   id_card_expiry_date=?, account_number=?, updated_at=?, updated_by=?
                   WHERE contract_id=? AND cell_number=?""",
                (*new_values.values(), timestamp, employee_name, data.contract_ref, data.cell_number),
            )
            connection.execute(
                """INSERT INTO archive.log(log_id, operation_id, occurred_at, employee, action,
                   contract_id, cell_number, changes_json) VALUES(?, ?, ?, ?, 'contract.edited', ?, ?, ?)""",
                (str(uuid4()), data.operation_id, timestamp, employee_name, data.contract_ref,
                 data.cell_number, json.dumps(changes, ensure_ascii=False, sort_keys=True)),
            )
            phase = "committing"; connection.commit(); phase = "verifying"
            saved = connection.execute("SELECT contract_id FROM contracts WHERE contract_id=?", (data.contract_ref,)).fetchone()
            if saved is None: raise EditingWriteUncertainError(UNCERTAIN_MESSAGE)
            warning = None; backup_created = True
            try: create_backup_pair(connection, settings, operation_id=data.operation_id, occurred_at=occurred_at)
            except Exception:
                backup_created = False; warning = "Данные сохранены, но резервную копию создать не удалось. Сообщите администратору."
            return EditingResult(data.contract_ref, data.cell_number, False, backup_created, warning)
    except (EditingValidationError, EditingConflictError, EditingWriteUncertainError): raise
    except DatabaseUnavailableError as exc: raise EditingNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {"opening", "begin", "transaction"}: raise EditingBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}: raise EditingWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise EditingNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}: raise EditingWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise EditingWriteError("Данные не сохранены. Изменения отменены.") from exc
