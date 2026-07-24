"""Atomic non-contract cell occupation and release operations."""

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
    open_readonly,
    open_write,
    validate_database_pair,
)
from app.services.backups import create_backup_pair, has_valid_backup_for_operation


BUSY_MESSAGE = "Другая операция записи ещё не завершена. Подождите и обновите данные."
UNCERTAIN_MESSAGE = (
    "Не удалось подтвердить результат операции. Не повторяйте её автоматически. "
    "Обновите главный экран и проверьте состояние ячейки."
)
BLOCK_ACTIONS = {
    "manual": ("cell.manual_occupied", "cell.manual_released"),
    "lost_key": (None, "cell.key_restored"),
}


class CellBlockValidationError(ValueError):
    pass


class CellBlockConflictError(RuntimeError):
    pass


class CellBlockReadError(RuntimeError):
    pass


class CellBlockBusyError(RuntimeError):
    pass


class CellBlockNetworkError(RuntimeError):
    pass


class CellBlockWriteError(RuntimeError):
    pass


class CellBlockWriteUncertainError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CellBlockResult:
    cell_number: str
    block_kind: str
    occupation_label: str | None
    repeated: bool
    backup_created: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _required_text(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CellBlockValidationError(f"Укажите поле «{label}».")
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise CellBlockValidationError(f"Поле «{label}» слишком длинное.")
    return normalized


def _operation_id(value: object) -> str:
    if not isinstance(value, str):
        raise CellBlockValidationError("Не удалось подготовить операцию. Обновите форму.")
    try:
        return str(UUID(value.strip()))
    except (ValueError, AttributeError) as exc:
        raise CellBlockValidationError(
            "Не удалось подготовить операцию. Обновите форму."
        ) from exc


def _payload(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict) or set(payload) != {"operation_id", "cell_number"}:
        raise CellBlockValidationError("Переданы неверные данные операции.")
    return (
        _operation_id(payload.get("operation_id")),
        _required_text(payload.get("cell_number"), label="Номер ячейки", maximum=50),
    )


def _manual_payload(payload: object) -> tuple[str, str, str]:
    if not isinstance(payload, dict) or set(payload) != {
        "operation_id", "cell_number", "occupation_label"
    }:
        raise CellBlockValidationError("Переданы неверные данные операции.")
    return (
        _operation_id(payload.get("operation_id")),
        _required_text(payload.get("cell_number"), label="Номер ячейки", maximum=50),
        _required_text(payload.get("occupation_label"), label="Пометка", maximum=80),
    )


def _timestamp(occurred_at: datetime) -> str:
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise CellBlockValidationError("Время операции должно содержать часовой пояс.")
    return occurred_at.isoformat(timespec="seconds")


def _warning(settings: Settings, operation_id: str, *, repeated: bool) -> tuple[bool, str | None]:
    backed_up = has_valid_backup_for_operation(settings, operation_id)
    if backed_up:
        return True, None
    prefix = "Операция уже сохранена" if repeated else "Операция сохранена"
    return False, f"{prefix}, но резервную копию создать не удалось. Сообщите администратору."


def _existing_operation(
    connection: sqlite3.Connection,
    settings: Settings,
    *,
    operation_id: str,
    cell_number: str,
    action: str,
    block_kind: str,
    release: bool,
    occupation_label: str | None = None,
) -> CellBlockResult | None:
    row = connection.execute(
        "SELECT action, cell_number FROM archive.log WHERE operation_id=?",
        (operation_id,),
    ).fetchone()
    if row is None:
        return None
    if row["action"] != action or row["cell_number"] != cell_number:
        raise CellBlockConflictError("Этот идентификатор операции уже использован.")
    if not release:
        block = connection.execute(
            "SELECT block_kind, occupation_label FROM main.cell_blocks WHERE cell_number=?",
            (cell_number,),
        ).fetchone()
        if block is None or block["block_kind"] != block_kind:
            raise CellBlockWriteUncertainError(UNCERTAIN_MESSAGE)
        if block_kind == "manual" and block["occupation_label"] != occupation_label:
            raise CellBlockConflictError("Этот идентификатор операции уже использован.")
    backed_up, warning = _warning(settings, operation_id, repeated=True)
    return CellBlockResult(
        cell_number, block_kind, occupation_label, True, backed_up, warning
    )


def _audit_changes(
    block_kind: str, *, occupation_label: str | None = None
) -> str:
    changes = {"block_kind": block_kind}
    if block_kind == "manual" and occupation_label is not None:
        changes["occupation_label"] = occupation_label
    return json.dumps(
        changes,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _is_locked(error: BaseException) -> bool:
    return "locked" in str(error).lower() or "busy" in str(error).lower()


def _write_error(error: BaseException, *, phase: str) -> BaseException:
    if isinstance(error, DatabaseCorruptionError):
        return CellBlockNetworkError(str(error))
    if isinstance(error, DatabaseUnavailableError):
        return CellBlockNetworkError(NETWORK_ERROR_MESSAGE)
    if isinstance(error, (OSError, sqlite3.OperationalError)):
        if phase in {"opening", "begin", "transaction"} and _is_locked(error):
            return CellBlockBusyError(BUSY_MESSAGE)
        if phase in {"committing", "verifying"}:
            return CellBlockWriteUncertainError(UNCERTAIN_MESSAGE)
        return CellBlockNetworkError(NETWORK_ERROR_MESSAGE)
    if phase in {"committing", "verifying"}:
        return CellBlockWriteUncertainError(UNCERTAIN_MESSAGE)
    return CellBlockWriteError("Операция не сохранена. Изменения отменены.")


def occupy_cell_manually(
    settings: Settings,
    *,
    payload: object,
    employee: str,
    occurred_at: datetime,
) -> CellBlockResult:
    operation_id, cell_number, occupation_label = _manual_payload(payload)
    employee_name = _required_text(employee, label="Сотрудник", maximum=128)
    timestamp = _timestamp(occurred_at)
    action = "cell.manual_occupied"
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            existing = _existing_operation(
                connection,
                settings,
                operation_id=operation_id,
                cell_number=cell_number,
                action=action,
                block_kind="manual",
                release=False,
                occupation_label=occupation_label,
            )
            if existing is not None:
                connection.rollback()
                return existing
            cell = connection.execute(
                """
                SELECT cells.number, contracts.contract_id, cell_blocks.block_kind
                FROM main.cells
                LEFT JOIN main.contracts ON contracts.cell_number=cells.number
                LEFT JOIN main.cell_blocks ON cell_blocks.cell_number=cells.number
                WHERE cells.number=?
                """,
                (cell_number,),
            ).fetchone()
            if cell is None:
                raise CellBlockConflictError("Ячейка не найдена.")
            if cell["contract_id"] is not None or cell["block_kind"] is not None:
                raise CellBlockConflictError(
                    "Ячейка уже занята. Обновите главный экран."
                )
            connection.execute(
                """
                INSERT INTO main.cell_blocks(
                    cell_number, block_kind, source_contract_id,
                    occupation_label, created_at, created_by
                ) VALUES(?, 'manual', NULL, ?, ?, ?)
                """,
                (cell_number, occupation_label, timestamp, employee_name),
            )
            connection.execute(
                """
                INSERT INTO archive.log(
                    log_id, operation_id, occurred_at, employee, action,
                    contract_id, cell_number, changes_json
                ) VALUES(?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    str(uuid4()), operation_id, timestamp, employee_name, action,
                    cell_number,
                    _audit_changes("manual", occupation_label=occupation_label),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            saved = connection.execute(
                "SELECT block_kind, occupation_label FROM main.cell_blocks WHERE cell_number=?",
                (cell_number,),
            ).fetchone()
            if (
                saved is None
                or saved["block_kind"] != "manual"
                or saved["occupation_label"] != occupation_label
            ):
                raise CellBlockWriteUncertainError(UNCERTAIN_MESSAGE)
            phase = "backup"
            backed_up = True
            warning = None
            try:
                create_backup_pair(
                    connection, settings, operation_id=operation_id, occurred_at=occurred_at
                )
            except Exception:
                backed_up, warning = _warning(settings, operation_id, repeated=False)
            return CellBlockResult(
                cell_number, "manual", occupation_label, False, backed_up, warning
            )
    except (CellBlockValidationError, CellBlockConflictError, CellBlockWriteUncertainError):
        raise
    except sqlite3.IntegrityError as exc:
        raise CellBlockConflictError("Ячейка уже занята. Обновите главный экран.") from exc
    except Exception as exc:
        raise _write_error(exc, phase=phase) from exc


def release_cell_block(
    settings: Settings,
    *,
    payload: object,
    expected_kind: str,
    employee: str,
    occurred_at: datetime,
) -> CellBlockResult:
    if expected_kind not in BLOCK_ACTIONS:
        raise CellBlockValidationError("Указан неверный вид блокировки ячейки.")
    operation_id, cell_number = _payload(payload)
    employee_name = _required_text(employee, label="Сотрудник", maximum=128)
    timestamp = _timestamp(occurred_at)
    action = BLOCK_ACTIONS[expected_kind][1]
    phase = "opening"
    try:
        with open_write(settings, attach_archive=True) as connection:
            phase = "begin"
            connection.execute("BEGIN IMMEDIATE")
            phase = "transaction"
            existing = _existing_operation(
                connection,
                settings,
                operation_id=operation_id,
                cell_number=cell_number,
                action=action,
                block_kind=expected_kind,
                release=True,
            )
            if existing is not None:
                connection.rollback()
                return existing
            block = connection.execute(
                """
                SELECT block_kind, source_contract_id, occupation_label
                FROM main.cell_blocks WHERE cell_number=?
                """,
                (cell_number,),
            ).fetchone()
            if block is None:
                raise CellBlockConflictError(
                    "Ячейка уже свободна. Обновите главный экран."
                )
            if block["block_kind"] != expected_kind:
                raise CellBlockConflictError(
                    "Состояние ячейки изменилось. Обновите главный экран."
                )
            deleted = connection.execute(
                "DELETE FROM main.cell_blocks WHERE cell_number=? AND block_kind=?",
                (cell_number, expected_kind),
            )
            if deleted.rowcount != 1:
                raise CellBlockConflictError(
                    "Состояние ячейки изменилось. Обновите главный экран."
                )
            connection.execute(
                """
                INSERT INTO archive.log(
                    log_id, operation_id, occurred_at, employee, action,
                    contract_id, cell_number, changes_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), operation_id, timestamp, employee_name, action,
                    block["source_contract_id"], cell_number,
                    _audit_changes(
                        expected_kind,
                        occupation_label=block["occupation_label"],
                    ),
                ),
            )
            phase = "committing"
            connection.commit()
            phase = "verifying"
            remaining = connection.execute(
                "SELECT 1 FROM main.cell_blocks WHERE cell_number=?",
                (cell_number,),
            ).fetchone()
            if remaining is not None:
                raise CellBlockWriteUncertainError(UNCERTAIN_MESSAGE)
            phase = "backup"
            backed_up = True
            warning = None
            try:
                create_backup_pair(
                    connection, settings, operation_id=operation_id, occurred_at=occurred_at
                )
            except Exception:
                backed_up, warning = _warning(settings, operation_id, repeated=False)
            return CellBlockResult(
                cell_number,
                expected_kind,
                block["occupation_label"],
                False,
                backed_up,
                warning,
            )
    except (CellBlockValidationError, CellBlockConflictError, CellBlockWriteUncertainError):
        raise
    except sqlite3.IntegrityError as exc:
        raise CellBlockConflictError("Операция уже была выполнена.") from exc
    except Exception as exc:
        raise _write_error(exc, phase=phase) from exc


def lost_key_client_name(settings: Settings, *, cell_number: object) -> str:
    cell = _required_text(cell_number, label="Номер ячейки", maximum=50)
    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            block = connection.execute(
                """
                SELECT source_contract_id FROM cell_blocks
                WHERE cell_number=? AND block_kind='lost_key'
                """,
                (cell,),
            ).fetchone()
        if block is None:
            raise CellBlockConflictError(
                "Состояние ячейки изменилось. Обновите главный экран."
            )
        with open_readonly(
            paths.archive, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            archived = connection.execute(
                """
                SELECT client_full_name FROM contracts_archive
                WHERE contract_id=? AND cell_number=?
                """,
                (block["source_contract_id"], cell),
            ).fetchone()
        if archived is None:
            raise CellBlockReadError("Не удалось найти закрытый договор по ячейке.")
        return str(archived["client_full_name"])
    except (CellBlockValidationError, CellBlockConflictError, CellBlockReadError):
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise CellBlockReadError(NETWORK_ERROR_MESSAGE) from exc
