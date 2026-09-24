"""Safe same-day cancellation of the latest contract opening or renewal."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
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
from app.services.backups import create_backup_pair, has_valid_backup_for_operation


BUSY_MESSAGE = (
    "Другая операция записи ещё не завершена. Подождите и обновите данные."
)
UNCERTAIN_MESSAGE = (
    "Не удалось подтвердить результат отмены. Не повторяйте её автоматически. "
    "Обновите главный экран и проверьте состояние ячейки."
)
REASON_LABELS = {
    "client_changed": "Клиент изменил решение",
    "change_term": "Нужно изменить срок",
    "input_error": "Ошибка при вводе",
}
ACTION_KINDS = {
    "contract.created": "opening",
    "contract.renewed": "renewal",
    "contract.closed": "closure",
}


class ActionCancellationValidationError(ValueError):
    """Cancellation payload is absent or malformed."""


class ActionCancellationConflictError(RuntimeError):
    """The original action can no longer be safely cancelled."""


class ActionCancellationBusyError(RuntimeError):
    """Another writer held the database beyond the configured timeout."""


class ActionCancellationNetworkError(RuntimeError):
    """The database pair could not be reached."""


class ActionCancellationWriteError(RuntimeError):
    """The cancellation transaction failed and was rolled back."""


class ActionCancellationWriteUncertainError(RuntimeError):
    """The connection failed while commit/result verification was in progress."""


@dataclass(frozen=True, slots=True)
class ActionCancellationData:
    cancellation_operation_id: str
    original_operation_id: str
    contract_ref: str
    cell_number: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ActionCancellationResult:
    cancellation_id: str
    original_operation_id: str
    action_kind: str
    contract_ref: str
    cell_number: str
    reason: str
    restored_end_date: str | None
    repeated: bool
    backup_created: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.action_kind == "renewal":
            payload["message"] = (
                f"Продление ячейки № {self.cell_number} отменено. "
                f"Дата окончания снова {self.restored_end_date}."
            )
        elif self.action_kind == "closure":
            payload["message"] = (
                f"Закрытие договора по ячейке № {self.cell_number} отменено. "
                f"Договор снова активен до {self.restored_end_date}."
            )
        else:
            payload["message"] = (
                f"Открытие ячейки № {self.cell_number} отменено. "
                "Ячейка снова свободна."
            )
        return payload


def _required_text(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionCancellationValidationError(f"Укажите поле «{label}».")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ActionCancellationValidationError(f"Поле «{label}» слишком длинное.")
    return normalized


def _operation_id(value: object, *, label: str) -> str:
    normalized = _required_text(value, label=label, maximum=100)
    try:
        return str(UUID(normalized))
    except ValueError as exc:
        raise ActionCancellationValidationError(
            "Не удалось подготовить отмену. Обновите окно операции."
        ) from exc


def validate_cancellation_payload(payload: object) -> ActionCancellationData:
    expected = {
        "cancellation_operation_id",
        "original_operation_id",
        "contract_ref",
        "cell_number",
        "reason_code",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ActionCancellationValidationError("Переданы неверные данные отмены.")
    reason_code = _required_text(
        payload["reason_code"], label="Причина отмены", maximum=40
    )
    if reason_code not in REASON_LABELS:
        raise ActionCancellationValidationError("Выберите допустимую причину отмены.")
    return ActionCancellationData(
        cancellation_operation_id=_operation_id(
            payload["cancellation_operation_id"], label="Операция отмены"
        ),
        original_operation_id=_operation_id(
            payload["original_operation_id"], label="Исходная операция"
        ),
        contract_ref=_required_text(
            payload["contract_ref"], label="Договор", maximum=100
        ),
        cell_number=_required_text(
            payload["cell_number"], label="Номер ячейки", maximum=50
        ),
        reason_code=reason_code,
    )


def _is_locked(error: BaseException) -> bool:
    text = str(error).lower()
    return "locked" in text or "busy" in text


def _result_from_row(
    row: sqlite3.Row,
    *,
    repeated: bool,
    backup_created: bool,
    restored_end_date: str | None,
    warning: str | None = None,
) -> ActionCancellationResult:
    action = str(row["original_action"])
    return ActionCancellationResult(
        cancellation_id=str(row["cancellation_id"]),
        original_operation_id=str(row["original_operation_id"]),
        action_kind=ACTION_KINDS[action],
        contract_ref=str(row["contract_id"]),
        cell_number=str(row["cell_number"]),
        reason=REASON_LABELS[str(row["reason_code"])],
        restored_end_date=restored_end_date,
        repeated=repeated,
        backup_created=backup_created,
        warning=warning,
    )


def _existing_result(
    connection: sqlite3.Connection,
    settings: Settings,
    data: ActionCancellationData,
) -> ActionCancellationResult | None:
    row = connection.execute(
        """
        SELECT * FROM archive.operation_cancellations
        WHERE cancellation_operation_id=?
        """,
        (data.cancellation_operation_id,),
    ).fetchone()
    if row is None:
        return None
    if (
        str(row["original_operation_id"]) != data.original_operation_id
        or str(row["contract_id"]) != data.contract_ref
        or str(row["cell_number"]) != data.cell_number
    ):
        raise ActionCancellationConflictError(
            "Этот идентификатор отмены уже использован. Обновите данные."
        )
    restored_end = None
    if row["original_action"] == "contract.renewed":
        renewal = connection.execute(
            """
            SELECT old_end_date FROM archive.renewals
            WHERE operation_id=? AND contract_id=? AND cell_number=?
            """,
            (
                data.original_operation_id,
                data.contract_ref,
                data.cell_number,
            ),
        ).fetchone()
        restored_end = str(renewal["old_end_date"]) if renewal is not None else None
    elif row["original_action"] == "contract.closed":
        contract = connection.execute(
            """
            SELECT end_date FROM main.contracts
            WHERE contract_id=? AND cell_number=?
            """,
            (data.contract_ref, data.cell_number),
        ).fetchone()
        restored_end = str(contract["end_date"]) if contract is not None else None
    backed_up = has_valid_backup_for_operation(
        settings, data.cancellation_operation_id
    )
    warning = None if backed_up else (
        "Действие уже отменено, но комплект резервной копии не найден. "
        "Сообщите администратору."
    )
    return _result_from_row(
        row,
        repeated=True,
        backup_created=backed_up,
        restored_end_date=restored_end,
        warning=warning,
    )


def _require_latest_action(
    connection: sqlite3.Connection,
    *,
    contract_ref: str,
    cell_number: str,
    original_action: str,
    original_rowid: int,
) -> None:
    if original_action == "contract.closed":
        later = connection.execute(
            """
            SELECT action FROM archive.log
            WHERE cell_number=? AND rowid>?
              AND (
                action LIKE 'contract.%'
                OR action LIKE 'cell.%'
                OR action LIKE 'admin.cell.%'
              )
            ORDER BY rowid
            LIMIT 1
            """,
            (cell_number, original_rowid),
        ).fetchone()
    else:
        later = connection.execute(
            """
            SELECT action FROM archive.log
            WHERE contract_id=? AND rowid>? AND action LIKE 'contract.%'
            ORDER BY rowid
            LIMIT 1
            """,
            (contract_ref, original_rowid),
        ).fetchone()
    if later is not None:
        raise ActionCancellationConflictError(
            "После этой операции договор уже изменялся. "
            "Отменить её автоматически нельзя."
        )


def _cancel_opening(
    connection: sqlite3.Connection,
    *,
    data: ActionCancellationData,
    timestamp: str,
    employee: str,
    reason_label: str,
) -> None:
    contract = connection.execute(
        """
        SELECT * FROM main.contracts
        WHERE contract_id=? AND cell_number=?
        """,
        (data.contract_ref, data.cell_number),
    ).fetchone()
    if contract is None:
        raise ActionCancellationConflictError(
            "Договор уже изменён или ячейка свободна. Обновите главный экран."
        )
    if connection.execute(
        "SELECT 1 FROM archive.renewals WHERE contract_id=? LIMIT 1",
        (data.contract_ref,),
    ).fetchone() is not None:
        raise ActionCancellationConflictError(
            "По договору уже есть продление. Сначала проверьте его историю."
        )
    if connection.execute(
        "SELECT 1 FROM main.cell_blocks WHERE cell_number=?",
        (data.cell_number,),
    ).fetchone() is not None:
        raise ActionCancellationConflictError(
            "Состояние ячейки уже изменилось. Обновите главный экран."
        )
    close_reason = f"Отмена открытия — {reason_label}"
    connection.execute(
        """
        INSERT INTO archive.contracts_archive(
            contract_id, cell_number, client_full_name, client_phone, client_whatsapp_phone,
            id_card_number, id_card_issuer, id_card_issue_date,
            account_number, abs_customer_id, extra_fields_json, start_date, end_date,
            rent_days, price_per_day_minor, rent_price_minor,
            deposit_amount_minor, created_at, created_by, updated_at,
            updated_by, last_reminded_at, reminder_count, closed_at,
            close_date, close_reason, close_kind, unused_days,
            penalty_days, penalty_rate_minor, penalty_amount_minor,
            deposit_refund_minor, closed_by, operation_id
        )
        SELECT
            contract_id, cell_number, client_full_name, client_phone, client_whatsapp_phone,
            id_card_number, id_card_issuer, id_card_issue_date,
            account_number, abs_customer_id, extra_fields_json, start_date, end_date,
            rent_days, price_per_day_minor, rent_price_minor,
            deposit_amount_minor, created_at, created_by, updated_at,
            updated_by, last_reminded_at, reminder_count, ?, substr(?, 1, 10),
            ?, 'early', 0, 0, 0, 0, 0, ?, ?
        FROM main.contracts
        WHERE contract_id=? AND cell_number=?
        """,
        (
            timestamp,
            timestamp,
            close_reason,
            employee,
            data.cancellation_operation_id,
            data.contract_ref,
            data.cell_number,
        ),
    )
    deleted = connection.execute(
        """
        DELETE FROM main.contracts
        WHERE contract_id=? AND cell_number=?
        """,
        (data.contract_ref, data.cell_number),
    )
    if deleted.rowcount != 1:
        raise ActionCancellationConflictError(
            "Договор уже изменился. Обновите главный экран."
        )


def _cancel_renewal(
    connection: sqlite3.Connection,
    *,
    data: ActionCancellationData,
    timestamp: str,
    employee: str,
) -> str:
    renewal = connection.execute(
        """
        SELECT * FROM archive.renewals
        WHERE operation_id=? AND contract_id=? AND cell_number=?
        """,
        (
            data.original_operation_id,
            data.contract_ref,
            data.cell_number,
        ),
    ).fetchone()
    if renewal is None:
        raise ActionCancellationConflictError(
            "Продление не найдено. Обновите главный экран."
        )
    old_end_date = str(renewal["old_end_date"])
    new_end_date = str(renewal["new_end_date"])
    updated = connection.execute(
        """
        UPDATE main.contracts
        SET end_date=?, updated_at=?, updated_by=?
        WHERE contract_id=? AND cell_number=? AND end_date=?
        """,
        (
            old_end_date,
            timestamp,
            employee,
            data.contract_ref,
            data.cell_number,
            new_end_date,
        ),
    )
    if updated.rowcount != 1:
        raise ActionCancellationConflictError(
            "Срок договора уже изменился. Обновите карточку."
        )
    return old_end_date


def _cancel_closure(
    connection: sqlite3.Connection,
    *,
    data: ActionCancellationData,
) -> str:
    archived = connection.execute(
        """
        SELECT * FROM archive.contracts_archive
        WHERE operation_id=? AND contract_id=? AND cell_number=?
        """,
        (
            data.original_operation_id,
            data.contract_ref,
            data.cell_number,
        ),
    ).fetchone()
    if archived is None:
        raise ActionCancellationConflictError(
            "Закрытый договор уже изменён. Обновите главный экран."
        )
    cell = connection.execute(
        """
        SELECT is_active FROM main.cells WHERE number=?
        """,
        (data.cell_number,),
    ).fetchone()
    if cell is None or not bool(cell["is_active"]):
        raise ActionCancellationConflictError(
            "Ячейка больше не используется. Восстановить договор нельзя."
        )
    active = connection.execute(
        """
        SELECT 1 FROM main.contracts
        WHERE contract_id=? OR cell_number=?
        """,
        (data.contract_ref, data.cell_number),
    ).fetchone()
    if active is not None:
        raise ActionCancellationConflictError(
            "Ячейка или договор уже заняты. Восстановить закрытие нельзя."
        )
    block = connection.execute(
        "SELECT * FROM main.cell_blocks WHERE cell_number=?",
        (data.cell_number,),
    ).fetchone()
    lost_key_closure = str(archived["close_reason"]) == "Потеря ключа"
    if lost_key_closure:
        if (
            block is None
            or str(block["block_kind"]) != "lost_key"
            or str(block["source_contract_id"]) != data.contract_ref
        ):
            raise ActionCancellationConflictError(
                "Состояние ключа уже изменилось. Восстановить договор нельзя."
            )
        deleted_block = connection.execute(
            """
            DELETE FROM main.cell_blocks
            WHERE cell_number=? AND block_kind='lost_key'
              AND source_contract_id=?
            """,
            (data.cell_number, data.contract_ref),
        )
        if deleted_block.rowcount != 1:
            raise ActionCancellationConflictError(
                "Состояние ключа уже изменилось. Обновите главный экран."
            )
    elif block is not None:
        raise ActionCancellationConflictError(
            "Ячейка уже занята или заблокирована. Восстановить договор нельзя."
        )

    connection.execute(
        """
        INSERT INTO main.contracts(
            contract_id, cell_number, client_full_name, client_phone, client_whatsapp_phone,
            id_card_number, id_card_issuer, id_card_issue_date,
            account_number, abs_customer_id, extra_fields_json, start_date, end_date,
            rent_days, price_per_day_minor, rent_price_minor,
            deposit_amount_minor, created_at, created_by, updated_at,
            updated_by, last_reminded_at, reminder_count
        )
        SELECT
            contract_id, cell_number, client_full_name, client_phone, client_whatsapp_phone,
            id_card_number, id_card_issuer, id_card_issue_date,
            account_number, abs_customer_id, extra_fields_json, start_date, end_date,
            rent_days, price_per_day_minor, rent_price_minor,
            deposit_amount_minor, created_at, created_by, updated_at,
            updated_by, last_reminded_at, reminder_count
        FROM archive.contracts_archive
        WHERE operation_id=? AND contract_id=? AND cell_number=?
        """,
        (
            data.original_operation_id,
            data.contract_ref,
            data.cell_number,
        ),
    )
    restored = connection.execute(
        """
        SELECT end_date FROM main.contracts
        WHERE contract_id=? AND cell_number=?
        """,
        (data.contract_ref, data.cell_number),
    ).fetchone()
    if restored is None:
        raise ActionCancellationConflictError(
            "Закрытый договор не удалось восстановить."
        )
    deleted_archive = connection.execute(
        """
        DELETE FROM archive.contracts_archive
        WHERE operation_id=? AND contract_id=? AND cell_number=?
        """,
        (
            data.original_operation_id,
            data.contract_ref,
            data.cell_number,
        ),
    )
    if deleted_archive.rowcount != 1:
        raise ActionCancellationConflictError(
            "Закрытый договор уже изменён. Обновите главный экран."
        )
    return str(restored["end_date"])


def cancel_contract_action(
    settings: Settings,
    *,
    payload: object,
    employee: str,
    occurred_at: datetime,
    after_state_change: Any = None,
) -> ActionCancellationResult:
    """Cancel the latest same-day opening, renewal, or closure."""

    data = validate_cancellation_payload(payload)
    employee_name = _required_text(employee, label="Сотрудник", maximum=128)
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ActionCancellationValidationError(
            "Время отмены должно содержать часовой пояс."
        )
    timestamp = occurred_at.isoformat(timespec="seconds")
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            existing = _existing_result(connection, settings, data)
            if existing is not None:
                connection.rollback()
                return existing
            prior_cancellation = connection.execute(
                """
                SELECT 1 FROM archive.operation_cancellations
                WHERE original_operation_id=?
                """,
                (data.original_operation_id,),
            ).fetchone()
            if prior_cancellation is not None:
                raise ActionCancellationConflictError(
                    "Это действие уже отменено. Обновите главный экран."
                )
            original = connection.execute(
                """
                SELECT rowid, occurred_at, action, contract_id, cell_number
                FROM archive.log
                WHERE operation_id=?
                """,
                (data.original_operation_id,),
            ).fetchone()
            if original is None or str(original["action"]) not in ACTION_KINDS:
                raise ActionCancellationConflictError(
                    "Эту операцию нельзя отменить автоматически."
                )
            if (
                str(original["contract_id"]) != data.contract_ref
                or str(original["cell_number"]) != data.cell_number
            ):
                raise ActionCancellationConflictError(
                    "Договор или ячейка уже изменились. Обновите главный экран."
                )
            original_action = str(original["action"])
            try:
                original_time = datetime.fromisoformat(str(original["occurred_at"]))
            except ValueError as exc:
                raise ActionCancellationWriteError(
                    "В журнале сохранено некорректное время исходной операции."
                ) from exc
            if original_time.date() != occurred_at.date():
                raise ActionCancellationConflictError(
                    "Отмена доступна только в день выполнения операции."
                )
            _require_latest_action(
                connection,
                contract_ref=data.contract_ref,
                cell_number=data.cell_number,
                original_action=original_action,
                original_rowid=int(original["rowid"]),
            )
            reason_label = REASON_LABELS[data.reason_code]
            restored_end_date = None
            if original_action == "contract.created":
                _cancel_opening(
                    connection,
                    data=data,
                    timestamp=timestamp,
                    employee=employee_name,
                    reason_label=reason_label,
                )
            elif original_action == "contract.renewed":
                restored_end_date = _cancel_renewal(
                    connection,
                    data=data,
                    timestamp=timestamp,
                    employee=employee_name,
                )
            else:
                restored_end_date = _cancel_closure(
                    connection,
                    data=data,
                )
            if after_state_change is not None:
                after_state_change()
            cancellation_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO archive.operation_cancellations(
                    cancellation_id, cancellation_operation_id,
                    original_operation_id, original_action, contract_id,
                    cell_number, reason_code, cancelled_at, cancelled_by
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cancellation_id,
                    data.cancellation_operation_id,
                    data.original_operation_id,
                    original_action,
                    data.contract_ref,
                    data.cell_number,
                    data.reason_code,
                    timestamp,
                    employee_name,
                ),
            )
            changes = json.dumps(
                {
                    "original_action": original_action,
                    "original_operation_id": data.original_operation_id,
                    "reason": reason_label,
                    "restored_end_date": restored_end_date,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            connection.execute(
                """
                INSERT INTO archive.log(
                    log_id, operation_id, occurred_at, employee, action,
                    contract_id, cell_number, changes_json
                ) VALUES(?, ?, ?, ?, 'contract.action_cancelled', ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    data.cancellation_operation_id,
                    timestamp,
                    employee_name,
                    data.contract_ref,
                    data.cell_number,
                    changes,
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                """
                SELECT * FROM archive.operation_cancellations
                WHERE cancellation_id=?
                """,
                (cancellation_id,),
            ).fetchone()
            if saved is None:
                raise ActionCancellationWriteUncertainError(UNCERTAIN_MESSAGE)
            phase = "backup"
            backed_up = True
            warning = None
            try:
                create_backup_pair(
                    connection,
                    settings,
                    operation_id=data.cancellation_operation_id,
                    occurred_at=occurred_at,
                )
            except Exception:
                backed_up = False
                warning = (
                    "Действие отменено, но резервную копию создать не удалось. "
                    "Сообщите администратору."
                )
            return _result_from_row(
                saved,
                repeated=False,
                backup_created=backed_up,
                restored_end_date=restored_end_date,
                warning=warning,
            )
    except (
        ActionCancellationValidationError,
        ActionCancellationConflictError,
        ActionCancellationWriteError,
        ActionCancellationWriteUncertainError,
    ):
        raise
    except DatabaseCorruptionError as exc:
        raise ActionCancellationNetworkError(str(exc)) from exc
    except DatabaseUnavailableError as exc:
        raise ActionCancellationNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except sqlite3.IntegrityError as exc:
        if "operation_cancellations" in str(exc) or "operation_id" in str(exc):
            raise ActionCancellationConflictError(
                "Действие уже отменено. Обновите главный экран."
            ) from exc
        raise ActionCancellationWriteError(
            "Действие не отменено. Изменения полностью откатились."
        ) from exc
    except (OSError, sqlite3.OperationalError) as exc:
        if phase in {"opening", "begin", "transaction"} and _is_locked(exc):
            raise ActionCancellationBusyError(BUSY_MESSAGE) from exc
        if phase in {"committing", "verifying"}:
            raise ActionCancellationWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise ActionCancellationNetworkError(NETWORK_ERROR_MESSAGE) from exc
    except Exception as exc:
        if phase in {"committing", "verifying"}:
            raise ActionCancellationWriteUncertainError(UNCERTAIN_MESSAGE) from exc
        raise ActionCancellationWriteError(
            "Действие не отменено. Изменения полностью откатились."
        ) from exc
