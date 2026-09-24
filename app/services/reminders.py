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
from app.documents.values import (
    amount_in_words_ky,
    amount_in_words_ru,
    format_document_issue_date,
    format_kyrgyz_date,
    format_quoted_kyrgyz_date_stem,
    format_quoted_russian_date,
)
from app.services.backups import create_backup_pair, has_valid_backup_for_operation
from app.services.phone_numbers import (
    PhoneNumberValidationError,
    normalize_whatsapp_phone,
)
from app.services.statuses import CellStatus, calculate_status
from app.template_fields import (
    ALLOWED_REMINDER_PLACEHOLDERS,
    MESSAGE_PLACEHOLDER_RE,
    TEMPLATE_FIELD_DICTIONARY,
    client_greeting_name,
)


REMINDER_TEMPLATE_EXPIRING_KEY = "whatsapp_reminder_expiring_template"
REMINDER_TEMPLATE_OVERDUE_KEY = "whatsapp_reminder_overdue_template"
REMINDER_TEMPLATE_KEYS = {
    CellStatus.EXPIRING.value: REMINDER_TEMPLATE_EXPIRING_KEY,
    CellStatus.OVERDUE.value: REMINDER_TEMPLATE_OVERDUE_KEY,
}
# Kept as a public alias for older internal callers. The settings screen now
# receives the complete catalog rather than a WhatsApp-only subset.
REMINDER_PLACEHOLDER_DICTIONARY = TEMPLATE_FIELD_DICTIONARY
REMINDER_PLACEHOLDERS = ALLOWED_REMINDER_PLACEHOLDERS
REMINDER_PLACEHOLDER_PATTERN = MESSAGE_PLACEHOLDER_RE
MAX_REMINDER_TEMPLATE_LENGTH = 4_000
RUSSIAN_MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
DEFAULT_REMINDER_TEMPLATES = {
    CellStatus.EXPIRING.value: (
        "Здравствуйте, [Клиент.Обращение]!\n\n"
        "Напоминаем, что срок аренды вашей банковской сейфовой ячейки "
        "№[Сейф.Номер] истекает [Договор.Конец].\n\n"
        "Для продления аренды или освобождения ячейки просим обратиться "
        "в отделение банка.\n\n"
        "С уважением, Банк «Толубай»."
    ),
    CellStatus.OVERDUE.value: (
        "Здравствуйте, [Клиент.Обращение]!\n\n"
        "Срок аренды вашей банковской сейфовой ячейки №[Сейф.Номер] "
        "истёк [Договор.Конец].\n\n"
        "Просим обратиться в отделение банка для продления аренды или "
        "освобождения ячейки. За период просрочки начисляется штраф "
        "согласно условиям договора.\n\n"
        "С уважением, Банк «Толубай»."
    ),
}
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


class ReminderTemplateValidationError(ValueError):
    """A configurable WhatsApp message template is incomplete or unsafe."""


@dataclass(frozen=True, slots=True)
class ReminderRequest:
    operation_id: str
    cell_number: str
    contract_ref: str
    phone_kind: str


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
    phone_kind = payload.get("phone_kind", "mobile")
    if phone_kind not in {"mobile", "whatsapp"}:
        raise ReminderValidationError("Выберите мобильный номер или номер WhatsApp.")
    return ReminderRequest(
        operation_id=operation_id,
        cell_number=_text(
            payload.get("cell_number"), label="Номер ячейки", maximum=50
        ),
        contract_ref=_text(
            payload.get("contract_ref"), label="Договор", maximum=100
        ),
        phone_kind=phone_kind,
    )


def format_message_date(value: date) -> str:
    """Format a Russian date for a formal client message."""

    return f"{value.day} {RUSSIAN_MONTHS[value.month]} {value.year} года"


def validate_reminder_template(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReminderTemplateValidationError(f"Шаблон «{label}» не может быть пустым.")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > MAX_REMINDER_TEMPLATE_LENGTH:
        raise ReminderTemplateValidationError(
            f"Шаблон «{label}» не должен превышать "
            f"{MAX_REMINDER_TEMPLATE_LENGTH} символов."
        )
    unknown = sorted(
        {
            match.group(0)
            for match in REMINDER_PLACEHOLDER_PATTERN.finditer(normalized)
            if match.group(0) not in REMINDER_PLACEHOLDERS
        }
    )
    if unknown:
        raise ReminderTemplateValidationError(
            f"В шаблоне «{label}» есть неизвестные подстановки: "
            + ", ".join(unknown)
            + "."
        )
    return normalized


def get_reminder_templates(connection: sqlite3.Connection) -> dict[str, str]:
    templates = dict(DEFAULT_REMINDER_TEMPLATES)
    rows = connection.execute(
        """
        SELECT key, value
        FROM config
        WHERE key IN (?, ?)
        """,
        (
            REMINDER_TEMPLATE_EXPIRING_KEY,
            REMINDER_TEMPLATE_OVERDUE_KEY,
        ),
    ).fetchall()
    status_by_key = {key: status for status, key in REMINDER_TEMPLATE_KEYS.items()}
    for row in rows:
        key = str(row["key"])
        status = status_by_key.get(key)
        if status is None:
            continue
        try:
            templates[status] = validate_reminder_template(
                row["value"],
                label=(
                    "Истекающая аренда"
                    if status == CellStatus.EXPIRING.value
                    else "Просроченная аренда"
                ),
            )
        except ReminderTemplateValidationError as exc:
            raise ReminderWriteError(
                "Сохранённый шаблон WhatsApp повреждён. Проверьте настройки."
            ) from exc
    return templates


def build_reminder_message(
    *,
    status: str,
    client_full_name: str,
    cell_number: str,
    end_date: date,
    template: str | None = None,
    start_date: date | None = None,
    rent_days: int | None = None,
    client_phone: str | None = None,
    account_number: str | None = None,
    id_card_number: str | None = None,
    id_card_issuer: str | None = None,
    id_card_issue_date: date | None = None,
    rent_price_minor: int | None = None,
    deposit_amount_minor: int | None = None,
    employee: str | None = None,
    message_date: date | None = None,
    height_mm: int | None = None,
    width_mm: int | None = None,
    depth_mm: int | None = None,
) -> str:
    if status not in DEFAULT_REMINDER_TEMPLATES:
        raise ReminderConflictError(
            "Напоминание доступно только для истекающей или просроченной аренды."
        )
    label = (
        "Истекающая аренда"
        if status == CellStatus.EXPIRING.value
        else "Просроченная аренда"
    )
    selected_template = validate_reminder_template(
        DEFAULT_REMINDER_TEMPLATES[status] if template is None else template,
        label=label,
    )
    greeting = client_greeting_name(client_full_name)
    formatted_end = format_message_date(end_date)
    dimensions = ""
    if all(value is not None for value in (height_mm, width_mm, depth_mm)):
        dimensions = f"{height_mm}×{width_mm}×{depth_mm} мм"
    status_text = (
        "Истекает"
        if status == CellStatus.EXPIRING.value
        else "Просрочено"
    )
    rent_price = "" if rent_price_minor is None else str(rent_price_minor)
    deposit = "" if deposit_amount_minor is None else str(deposit_amount_minor)
    issue_date_text = (
        format_document_issue_date(id_card_issue_date)
        if id_card_issue_date
        else ""
    )
    replacements = {
        "[Клиент.Обращение]": greeting,
        "[Клиент.ФИО]": client_full_name,
        "[Клиент.Телефон]": client_phone or "",
        "[Счет.Номер]": account_number or "",
        "[Сейф.Номер]": str(cell_number),
        "[Сейф.Размер]": dimensions,
        "[Сейф.Высота]": "" if height_mm is None else str(height_mm),
        "[Сейф.Ширина]": "" if width_mm is None else str(width_mm),
        "[Сейф.Глубина]": "" if depth_mm is None else str(depth_mm),
        "[Договор.Начало]": (
            format_message_date(start_date) if start_date else ""
        ),
        "[Договор.Конец]": formatted_end,
        "[Договор.Срок]": "" if rent_days is None else str(rent_days),
        "[Договор.Сумма]": rent_price,
        "[Договор.Статус]": status_text,
        "[Дата.Сегодня]": (
            format_message_date(message_date) if message_date else ""
        ),
        "[Дата.СегодняК]": (
            format_kyrgyz_date(message_date) if message_date else ""
        ),
        "[Клиент.Документ.Номер]": id_card_number or "",
        "[Клиент.Документ.Выдан]": id_card_issuer or "",
        "[Клиент.Документ.ДатаВыдачи]": issue_date_text,
        "[Система.Пользователь]": employee or "",
        "[Договор.НачалоК]": (
            format_kyrgyz_date(start_date) if start_date else ""
        ),
        "[Договор.КонецК]": format_kyrgyz_date(end_date),
        "[Договор.НачалоД]": (
            format_quoted_russian_date(start_date) if start_date else ""
        ),
        "[Договор.НачалоДК]": (
            format_quoted_kyrgyz_date_stem(start_date) if start_date else ""
        ),
        "[Сумма]": rent_price,
        "[Залог.Сумма]": deposit,
        "[Залог.Цифр]": deposit,
        "[Залог.Пропись]": (
            amount_in_words_ru(deposit_amount_minor)
            if deposit_amount_minor is not None
            else ""
        ),
        "[Залог.ПрописьК]": (
            amount_in_words_ky(deposit_amount_minor)
            if deposit_amount_minor is not None
            else ""
        ),
        "[Обращение]": greeting,
        "[Имя]": greeting,
        "[ФИО клиента]": client_full_name,
        "[Номер ячейки]": str(cell_number),
        "[Размер ячейки]": dimensions,
        "[Дата начала]": format_message_date(start_date) if start_date else "",
        "[Дата окончания]": formatted_end,
        "[Количество дней]": "" if rent_days is None else str(rent_days),
        "[Телефон]": client_phone or "",
        "[Номер счёта]": account_number or "",
        "[Статус аренды]": status_text,
        "{{CLIENT_FULL_NAME}}": client_full_name,
        "{{ID_CARD_NUMBER}}": id_card_number or "",
        "{{ID_CARD_ISSUER}}": id_card_issuer or "",
        "{{ID_CARD_ISSUE_DATE}}": (
            id_card_issue_date.isoformat() if id_card_issue_date else ""
        ),
        "{{ACCOUNT_NUMBER}}": account_number or "",
        "{{SAFE_NUMBER}}": str(cell_number),
        "{{SAFE_HEIGHT}}": "" if height_mm is None else str(height_mm),
        "{{SAFE_WIDTH}}": "" if width_mm is None else str(width_mm),
        "{{SAFE_DEPTH}}": "" if depth_mm is None else str(depth_mm),
        "{{START_DATE}}": start_date.isoformat() if start_date else "",
        "{{END_DATE}}": end_date.isoformat(),
        "{{RENT_DAYS}}": "" if rent_days is None else str(rent_days),
        "{{RENT_PRICE}}": rent_price,
        "{{CREATION_DATE}}": message_date.isoformat() if message_date else "",
        "{{EMPLOYEE}}": employee or "",
    }
    message = selected_template
    for placeholder, replacement in replacements.items():
        message = message.replace(placeholder, replacement)
    return message


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


def _whatsapp_url_from_row(
    row: sqlite3.Row,
    *,
    status: str,
    occurred_at: datetime,
    employee: str,
    template: str,
    phone_kind: str,
) -> str:
    phone_field = (
        "client_whatsapp_phone" if phone_kind == "whatsapp" else "client_phone"
    )
    raw_phone = str(row[phone_field] or "")
    try:
        phone = normalize_whatsapp_phone(raw_phone)
        start_date = date.fromisoformat(str(row["start_date"]))
        end_date = date.fromisoformat(str(row["end_date"]))
        id_card_issue_date = date.fromisoformat(str(row["id_card_issue_date"]))
    except PhoneNumberValidationError as exc:
        raise ReminderValidationError(str(exc)) from exc
    except ValueError as exc:
        raise ReminderWriteError("В договоре сохранена некорректная дата окончания.") from exc
    message = build_reminder_message(
        status=status,
        client_full_name=str(row["client_full_name"]),
        cell_number=str(row["cell_number"]),
        end_date=end_date,
        template=template,
        start_date=start_date,
        rent_days=int(row["rent_days"]),
        client_phone=raw_phone,
        account_number=str(row["account_number"] or ""),
        id_card_number=str(row["id_card_number"] or ""),
        id_card_issuer=str(row["id_card_issuer"] or ""),
        id_card_issue_date=id_card_issue_date,
        rent_price_minor=int(row["rent_price_minor"]),
        deposit_amount_minor=int(row["deposit_amount_minor"]),
        employee=employee,
        message_date=occurred_at.date(),
        height_mm=int(row["height_mm"]),
        width_mm=int(row["width_mm"]),
        depth_mm=int(row["depth_mm"]),
    )
    return (
        "https://web.whatsapp.com/send"
        f"?phone={phone}&text={quote(message, safe='')}"
    )


def _result_from_row(
    row: sqlite3.Row,
    *,
    status: str,
    occurred_at: datetime,
    employee: str,
    template: str,
    repeated: bool,
    backup_created: bool,
    warning: str | None = None,
    phone_kind: str,
) -> ReminderResult:
    whatsapp_url = _whatsapp_url_from_row(
        row,
        status=status,
        occurred_at=occurred_at,
        employee=employee,
        template=template,
        phone_kind=phone_kind,
    )
    last_reminded_at = str(row["last_reminded_at"])
    return ReminderResult(
        contract_ref=str(row["contract_id"]),
        cell_number=str(row["cell_number"]),
        status=status,
        last_reminded_at=last_reminded_at,
        reminder_count=int(row["reminder_count"]),
        reminder_status=reminder_status_text(last_reminded_at, as_of=occurred_at),
        whatsapp_url=whatsapp_url,
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
                SELECT contracts.contract_id, contracts.cell_number,
                       contracts.client_full_name, contracts.client_phone,
                       contracts.client_whatsapp_phone,
                       contracts.account_number, contracts.id_card_number,
                       contracts.id_card_issuer, contracts.id_card_issue_date,
                       contracts.start_date, contracts.end_date,
                       contracts.rent_days, contracts.rent_price_minor,
                       contracts.deposit_amount_minor,
                       contracts.last_reminded_at, contracts.reminder_count,
                       cells.height_mm,
                       COALESCE(cells.width_mm, defaults.width_mm) AS width_mm,
                       COALESCE(cells.depth_mm, defaults.depth_mm) AS depth_mm
                FROM main.contracts AS contracts
                JOIN main.cells AS cells ON cells.number=contracts.cell_number
                CROSS JOIN main.vault_defaults AS defaults
                WHERE defaults.id=1
                  AND contracts.contract_id=? AND contracts.cell_number=?
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
            reminder_template = get_reminder_templates(connection)[status]
            phone_field = (
                "client_whatsapp_phone"
                if data.phone_kind == "whatsapp"
                else "client_phone"
            )
            try:
                normalize_whatsapp_phone(row[phone_field])
            except PhoneNumberValidationError as exc:
                raise ReminderValidationError(str(exc)) from exc
            # Prepare the complete link before changing reminder state. A damaged
            # stored field or an unfillable code must never mark the client as
            # notified.
            _whatsapp_url_from_row(
                row,
                status=status,
                occurred_at=occurred_at,
                employee=employee_name,
                template=reminder_template,
                phone_kind=data.phone_kind,
            )

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
                    employee=employee_name,
                    template=reminder_template,
                    repeated=True,
                    backup_created=backup_created,
                    warning=warning,
                    phone_kind=data.phone_kind,
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
                SELECT contracts.contract_id, contracts.cell_number,
                       contracts.client_full_name, contracts.client_phone,
                       contracts.client_whatsapp_phone,
                       contracts.account_number, contracts.id_card_number,
                       contracts.id_card_issuer, contracts.id_card_issue_date,
                       contracts.start_date, contracts.end_date,
                       contracts.rent_days, contracts.rent_price_minor,
                       contracts.deposit_amount_minor,
                       contracts.last_reminded_at, contracts.reminder_count,
                       cells.height_mm,
                       COALESCE(cells.width_mm, defaults.width_mm) AS width_mm,
                       COALESCE(cells.depth_mm, defaults.depth_mm) AS depth_mm
                FROM main.contracts AS contracts
                JOIN main.cells AS cells ON cells.number=contracts.cell_number
                CROSS JOIN main.vault_defaults AS defaults
                WHERE defaults.id=1
                  AND contracts.contract_id=? AND contracts.cell_number=?
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
                SELECT contracts.contract_id, contracts.cell_number,
                       contracts.client_full_name, contracts.client_phone,
                       contracts.client_whatsapp_phone,
                       contracts.account_number, contracts.id_card_number,
                       contracts.id_card_issuer, contracts.id_card_issue_date,
                       contracts.start_date, contracts.end_date,
                       contracts.rent_days, contracts.rent_price_minor,
                       contracts.deposit_amount_minor,
                       contracts.last_reminded_at, contracts.reminder_count,
                       cells.height_mm,
                       COALESCE(cells.width_mm, defaults.width_mm) AS width_mm,
                       COALESCE(cells.depth_mm, defaults.depth_mm) AS depth_mm
                FROM main.contracts AS contracts
                JOIN main.cells AS cells ON cells.number=contracts.cell_number
                CROSS JOIN main.vault_defaults AS defaults
                WHERE defaults.id=1
                  AND contracts.contract_id=? AND contracts.cell_number=?
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
                employee=employee_name,
                template=reminder_template,
                repeated=False,
                backup_created=backup_created,
                warning=warning,
                phone_kind=data.phone_kind,
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
