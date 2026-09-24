"""Safe editing of non-financial active-contract details."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
import re
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from app.config import Settings
from app.db.connections import (
    DatabaseCorruptionError,
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_write,
)
from app.services.backups import create_backup_pair
from app.services.legacy_contracts import complete_legacy_details, legacy_status
from app.services.phone_numbers import (
    PhoneNumberValidationError,
    normalize_whatsapp_phone,
)


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
    client_phone: str | None
    client_whatsapp_phone: str | None
    id_card_number: str
    id_card_issuer: str
    id_card_issue_date: str
    account_number: str
    abs_customer_id: str | None
    deposit_amount: int | None


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
    allowed = {"operation_id", "contract_ref", "cell_number", "client_full_name", "client_phone", "client_whatsapp_phone", "id_card_number", "id_card_issuer", "id_card_issue_date", "account_number", "abs_customer_id", "deposit_amount"}
    if set(payload) - allowed:
        raise EditingValidationError("Попытка изменить запрещённое поле.")
    operation_id = _text(payload.get("operation_id"), "Операция", 100)
    try: UUID(operation_id)
    except ValueError as exc: raise EditingValidationError("Неверный идентификатор операции.") from exc
    issue_date = _text(payload.get("id_card_issue_date"), "Дата выдачи ID-карты", 10)
    try: date.fromisoformat(issue_date)
    except ValueError as exc: raise EditingValidationError("Укажите корректную дату выдачи ID-карты.") from exc
    deposit_value = payload.get("deposit_amount")
    if deposit_value is None:
        deposit_amount = None
    elif isinstance(deposit_value, bool) or not isinstance(deposit_value, int) or not 0 <= deposit_value <= 10_000_000:
        raise EditingValidationError("Укажите корректный фактический залог.")
    else:
        deposit_amount = deposit_value
    client_phone = None
    if "client_phone" in payload:
        client_phone = _text(payload.get("client_phone"), "Номер телефона", 50)
        try:
            normalize_whatsapp_phone(client_phone)
        except PhoneNumberValidationError as exc:
            raise EditingValidationError(str(exc)) from exc
    client_whatsapp_phone = None
    if "client_whatsapp_phone" in payload and payload.get("client_whatsapp_phone") not in (None, ""):
        client_whatsapp_phone = _text(
            payload.get("client_whatsapp_phone"), "Номер WhatsApp", 50
        )
        try:
            normalize_whatsapp_phone(client_whatsapp_phone)
        except PhoneNumberValidationError as exc:
            raise EditingValidationError(str(exc)) from exc
    raw_abs_customer_id = payload.get("abs_customer_id")
    abs_customer_id = None
    if raw_abs_customer_id not in (None, ""):
        if not isinstance(raw_abs_customer_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,50}", raw_abs_customer_id.strip()
        ):
            raise EditingValidationError("Некорректный ID клиента АБС.")
        abs_customer_id = raw_abs_customer_id.strip()
    return EditingData(
        operation_id=operation_id,
        contract_ref=_text(payload.get("contract_ref"), "Договор", 100),
        cell_number=_text(payload.get("cell_number"), "Номер ячейки", 50),
        client_full_name=_text(payload.get("client_full_name"), "ФИО клиента", 200),
        client_phone=client_phone,
        client_whatsapp_phone=client_whatsapp_phone,
        id_card_number=_text(payload.get("id_card_number"), "Номер ID-карты", 100),
        id_card_issuer=_text(payload.get("id_card_issuer"), "Орган выдачи", 200),
        id_card_issue_date=issue_date,
        account_number=_text(payload.get("account_number"), "Номер счёта", 100),
        abs_customer_id=abs_customer_id,
        deposit_amount=deposit_amount,
    )


def edit_contract(settings: Settings, *, payload: object, employee: str, occurred_at: datetime) -> EditingResult:
    data = validate_editing_payload(payload)
    employee_name = _text(employee, "Сотрудник", 128)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise EditingValidationError("Время операции должно содержать часовой пояс.")
    if date.fromisoformat(data.id_card_issue_date) > occurred_at.date():
        raise EditingValidationError("Дата выдачи ID-карты не может быть в будущем.")
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
            legacy = legacy_status(row["extra_fields_json"])
            if not legacy["legacy_imported"] and data.deposit_amount is not None:
                raise EditingValidationError("Залог обычного договора здесь не изменяется.")
            if legacy["legacy_imported"] and not legacy["legacy_deposit_known"] and data.deposit_amount is None:
                raise EditingValidationError("Для старого договора укажите фактический залог.")
            fields = ("client_full_name", "client_phone", "client_whatsapp_phone", "id_card_number", "id_card_issuer", "id_card_issue_date", "account_number")
            stored_abs_customer_id = (
                str(row["abs_customer_id"])
                if row["abs_customer_id"] is not None
                else None
            )
            if (
                stored_abs_customer_id is not None
                and data.abs_customer_id is not None
                and data.abs_customer_id != stored_abs_customer_id
            ):
                raise EditingConflictError(
                    "Договор уже привязан к другому ID клиента АБС."
                )
            effective_abs_customer_id = (
                stored_abs_customer_id or data.abs_customer_id
            )
            new_values = {
                name: (
                    row[name]
                    if name in {"client_phone", "client_whatsapp_phone"}
                    and getattr(data, name) is None
                    else getattr(data, name)
                )
                for name in fields
            }
            if legacy["legacy_imported"]:
                changes = {}
                if not legacy["legacy_identity_complete"] or any(
                    row[name] != new_values[name] for name in fields
                ):
                    changes["legacy_identity_details"] = {"completed": True}
                if data.deposit_amount is not None and (
                    not legacy["legacy_deposit_known"] or int(row["deposit_amount_minor"]) != data.deposit_amount
                ):
                    changes["legacy_deposit"] = {"completed": True}
            else:
                changes = {
                    name: {"old": row[name], "new": new_values[name]}
                    for name in fields
                    if row[name] != new_values[name]
                }
            if effective_abs_customer_id != stored_abs_customer_id:
                changes["abs_customer_link"] = {
                    "old": stored_abs_customer_id is not None,
                    "new": effective_abs_customer_id is not None,
                }
            if not changes:
                raise EditingValidationError("Данные не изменены.")
            effective_deposit = int(row["deposit_amount_minor"]) if data.deposit_amount is None else data.deposit_amount
            extra_fields_json = complete_legacy_details(
                row["extra_fields_json"],
                identity_complete=True,
                deposit_known=legacy["legacy_deposit_known"] or data.deposit_amount is not None,
            )
            connection.execute(
                """UPDATE contracts SET client_full_name=?, client_phone=?, client_whatsapp_phone=?, id_card_number=?, id_card_issuer=?,
                   id_card_issue_date=?, account_number=?, abs_customer_id=?,
                   deposit_amount_minor=?,
                   extra_fields_json=?, updated_at=?, updated_by=?
                   WHERE contract_id=? AND cell_number=?""",
                (*new_values.values(), effective_abs_customer_id, effective_deposit,
                 extra_fields_json, timestamp, employee_name,
                 data.contract_ref, data.cell_number),
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
    except DatabaseCorruptionError as exc: raise EditingNetworkError(str(exc)) from exc
    except DatabaseUnavailableError as exc: raise EditingNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() and phase in {"opening", "begin", "transaction"}: raise EditingBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}: raise EditingWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise EditingNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except (OSError, sqlite3.Error) as exc:
        if phase in {"committing", "verifying"}: raise EditingWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise EditingWriteError("Данные не сохранены. Изменения отменены.") from exc
