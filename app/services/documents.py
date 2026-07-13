"""Read active contract data and generate a document from an approved template."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Mapping

from app.config import Settings
from app.db.connections import DatabaseUnavailableError, NETWORK_ERROR_MESSAGE, open_readonly, validate_database_pair
from app.documents import DocumentPublishError, DocumentTemplateError, render_docx
from app.documents.values import (
    amount_in_words_ky,
    amount_in_words_ru,
    format_document_issue_date,
    format_kyrgyz_date,
    format_quoted_kyrgyz_date,
    format_quoted_kyrgyz_date_stem,
    format_quoted_russian_date,
    format_russian_date,
)


class DocumentValidationError(ValueError): pass
class DocumentConflictError(RuntimeError): pass
class DocumentReadError(RuntimeError): pass


DOCUMENT_EVENT_TYPES = frozenset({"opening", "renewal", "closing"})

# The admin upload validator accepts only fields the renderer can actually fill.
ALLOWED_DOCUMENT_PLACEHOLDERS = frozenset(
    {
        "CLIENT_FULL_NAME", "ID_CARD_NUMBER", "ID_CARD_ISSUER",
        "ID_CARD_ISSUE_DATE", "ACCOUNT_NUMBER", "SAFE_NUMBER", "SAFE_HEIGHT",
        "SAFE_WIDTH", "SAFE_DEPTH", "START_DATE", "END_DATE", "RENT_DAYS",
        "RENT_PRICE", "CREATION_DATE", "EMPLOYEE", "Дата.Сегодня",
        "Дата.СегодняК", "Счет.Номер", "Клиент.ФИО",
        "Клиент.Документ.Номер", "Клиент.Документ.Выдан",
        "Клиент.Документ.ДатаВыдачи", "Система.Пользователь",
        "Договор.Начало", "Договор.Конец", "Договор.НачалоК",
        "Договор.КонецК", "Договор.НачалоД", "Договор.НачалоДК", "Сумма",
        "Залог.Цифр", "Залог.Пропись", "Залог.ПрописьК", "Сейф.Номер",
        "Сейф.Размер", "Продление.Начало", "Продление.Конец",
        "Продление.НачалоК", "Продление.КонецК", "Продление.Сумма",
        "Продление.Срок",
    }
)


@dataclass(frozen=True, slots=True)
class GeneratedDocument:
    file_name: str
    def to_dict(self) -> dict[str, str]:
        return {"file_name": self.file_name, "message": "Документ сохранён в папку «Загрузки»."}


def _required_placeholders(value: object) -> list[str]:
    try:
        required = json.loads(value)
        if not isinstance(required, list) or not all(
            isinstance(item, str) for item in required
        ):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DocumentValidationError(
            "Настройка обязательных полей шаблона повреждена."
        ) from exc
    return required


def list_active_templates(settings: Settings, *, cell_number: object, contract_ref: object) -> list[dict[str, str]]:
    if not all(isinstance(value, str) and value.strip() for value in (cell_number, contract_ref)):
        raise DocumentValidationError("Не выбран активный договор.")
    try:
        paths = validate_database_pair(settings)
        with open_readonly(paths.working, busy_timeout_ms=settings.busy_timeout_ms) as connection:
            contract = connection.execute(
                "SELECT 1 FROM contracts WHERE cell_number = ? AND contract_id = ?",
                (cell_number.strip(), contract_ref.strip()),
            ).fetchone()
            rows = connection.execute(
                """SELECT template_id, display_name FROM document_templates
                   WHERE is_active = 1
                     AND document_type NOT IN ('renewal', 'closing')
                   ORDER BY display_name, template_id"""
            ).fetchall()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise DocumentReadError(NETWORK_ERROR_MESSAGE) from exc
    if contract is None:
        raise DocumentConflictError("Договор изменён или закрыт. Обновите главный экран.")
    return [{"template_id": str(row["template_id"]), "display_name": str(row["display_name"])} for row in rows]


def _safe_filename_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value).strip().rstrip(".")
    cleaned = re.sub(r"\s+", "-", cleaned)
    return (cleaned[:60] or fallback)


def build_document_values(
    contract: Mapping[str, object] | sqlite3.Row,
    *,
    creation_date: date,
    employee: str,
    renewal: Mapping[str, object] | sqlite3.Row | None = None,
) -> dict[str, object]:
    """Build approved placeholder values without guessing legal requisites."""

    start_date = date.fromisoformat(str(contract["start_date"]))
    end_date = date.fromisoformat(str(contract["end_date"]))
    issue_date = date.fromisoformat(str(contract["id_card_issue_date"]))
    deposit = int(contract["deposit_amount_minor"])
    safe_size = (
        f'{contract["height_mm"]}×{contract["width_mm"]}×{contract["depth_mm"]} мм'
    )
    values: dict[str, object] = {
        "CLIENT_FULL_NAME": contract["client_full_name"],
        "ID_CARD_NUMBER": contract["id_card_number"],
        "ID_CARD_ISSUER": contract["id_card_issuer"],
        "ID_CARD_ISSUE_DATE": contract["id_card_issue_date"],
        "ACCOUNT_NUMBER": contract["account_number"],
        "SAFE_NUMBER": contract["cell_number"],
        "SAFE_HEIGHT": contract["height_mm"],
        "SAFE_WIDTH": contract["width_mm"],
        "SAFE_DEPTH": contract["depth_mm"],
        "START_DATE": contract["start_date"],
        "END_DATE": contract["end_date"],
        "RENT_DAYS": contract["rent_days"],
        "RENT_PRICE": contract["rent_price_minor"],
        "CREATION_DATE": creation_date.isoformat(),
        "EMPLOYEE": employee,
        "Дата.Сегодня": format_russian_date(creation_date),
        "Дата.СегодняК": format_kyrgyz_date(creation_date),
        "Счет.Номер": contract["account_number"],
        "Клиент.ФИО": contract["client_full_name"],
        "Клиент.Документ.Номер": contract["id_card_number"],
        "Клиент.Документ.Выдан": contract["id_card_issuer"],
        "Клиент.Документ.ДатаВыдачи": format_document_issue_date(issue_date),
        "Система.Пользователь": employee,
        "Договор.Начало": format_russian_date(start_date),
        "Договор.Конец": format_russian_date(end_date),
        "Договор.НачалоК": format_kyrgyz_date(start_date),
        "Договор.КонецК": format_kyrgyz_date(end_date),
        "Договор.НачалоД": format_quoted_russian_date(start_date),
        # The supplied addendum already appends "-жылдагы" after this code.
        "Договор.НачалоДК": format_quoted_kyrgyz_date_stem(start_date),
        "Сумма": contract["rent_price_minor"],
        "Залог.Цифр": deposit,
        "Залог.Пропись": amount_in_words_ru(deposit),
        "Залог.ПрописьК": amount_in_words_ky(deposit),
        "Сейф.Номер": contract["cell_number"],
        "Сейф.Размер": safe_size,
    }
    if renewal is not None:
        renewal_start = date.fromisoformat(str(renewal["new_start_date"]))
        renewal_end = date.fromisoformat(str(renewal["new_end_date"]))
        values.update(
            {
                "Продление.Начало": format_quoted_russian_date(renewal_start),
                "Продление.Конец": format_quoted_russian_date(renewal_end),
                "Продление.НачалоК": format_quoted_kyrgyz_date(renewal_start),
                "Продление.КонецК": format_quoted_kyrgyz_date(renewal_end),
                "Продление.Сумма": int(renewal["renewal_price_minor"]),
                "Продление.Срок": int(renewal["renewal_days"]),
            }
        )
    return values


def generate_active_contract_document(
    settings: Settings, *, cell_number: object, contract_ref: object,
    template_id: object, output_directory: Path, creation_date: date,
    employee: str,
) -> GeneratedDocument:
    if not all(isinstance(value, str) and value.strip() for value in (cell_number, contract_ref, template_id)):
        raise DocumentValidationError("Не выбран договор или шаблон документа.")
    try:
        paths = validate_database_pair(settings)
        with open_readonly(paths.working, busy_timeout_ms=settings.busy_timeout_ms) as connection:
            template = connection.execute(
                "SELECT display_name, relative_file_name, required_placeholders_json FROM document_templates WHERE template_id = ? AND is_active = 1",
                (template_id.strip(),),
            ).fetchone()
            contract = connection.execute(
                """SELECT c.*, cells.height_mm,
                          COALESCE(cells.width_mm, defaults.width_mm) AS width_mm,
                          COALESCE(cells.depth_mm, defaults.depth_mm) AS depth_mm
                   FROM contracts c JOIN cells ON cells.number = c.cell_number
                   CROSS JOIN vault_defaults defaults
                   WHERE c.cell_number = ? AND c.contract_id = ?""",
                (cell_number.strip(), contract_ref.strip()),
            ).fetchone()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise DocumentReadError(NETWORK_ERROR_MESSAGE) from exc
    if template is None:
        raise DocumentValidationError("Активный шаблон документа не найден.")
    if contract is None:
        raise DocumentConflictError("Договор изменён или закрыт. Обновите главный экран.")
    required = _required_placeholders(template["required_placeholders_json"])

    values = build_document_values(
        contract, creation_date=creation_date, employee=employee
    )
    display = _safe_filename_part(str(template["display_name"]), "Документ")
    cell = _safe_filename_part(str(contract["cell_number"]), "ячейка")
    client = _safe_filename_part(str(contract["client_full_name"]), "клиент")
    output_name = f"{display}_Ячейка-{cell}_{client}_{creation_date.isoformat()}.docx"
    try:
        render_docx(
            template_directory=settings.database_directory / "templates",
            template_file_name=str(template["relative_file_name"]),
            output_directory=output_directory, output_file_name=output_name,
            values=values, required_placeholders=required,
        )
    except (DocumentTemplateError, DocumentPublishError):
        raise
    return GeneratedDocument(output_name)


def generate_event_documents(
    settings: Settings,
    *,
    event_type: str,
    contract_ref: str,
    event_ref: str | None,
    output_directory: Path,
    employee: str,
) -> list[GeneratedDocument]:
    """Generate the configured post-commit bundle for one saved business event."""

    if event_type not in DOCUMENT_EVENT_TYPES:
        raise DocumentValidationError("Неизвестный комплект документов.")
    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            templates = connection.execute(
                """SELECT display_name, relative_file_name,
                          required_placeholders_json
                   FROM document_templates
                   WHERE document_type = ? AND is_active = 1
                   ORDER BY display_name, template_id""",
                (event_type,),
            ).fetchall()
            if not templates:
                return []
            if event_type in {"opening", "renewal"}:
                contract_row = connection.execute(
                    """SELECT c.*, cells.height_mm,
                              COALESCE(cells.width_mm, defaults.width_mm) AS width_mm,
                              COALESCE(cells.depth_mm, defaults.depth_mm) AS depth_mm
                       FROM contracts c JOIN cells ON cells.number = c.cell_number
                       CROSS JOIN vault_defaults defaults
                       WHERE c.contract_id = ?""",
                    (contract_ref,),
                ).fetchone()
                contract = dict(contract_row) if contract_row is not None else None
            else:
                contract = None
        renewal = None
        if event_type == "renewal":
            if not event_ref:
                raise DocumentValidationError("Не выбрано сохранённое продление.")
            with open_readonly(
                paths.archive, busy_timeout_ms=settings.busy_timeout_ms
            ) as connection:
                renewal_row = connection.execute(
                    "SELECT * FROM renewals WHERE renewal_id = ? AND contract_id = ?",
                    (event_ref, contract_ref),
                ).fetchone()
                renewal = dict(renewal_row) if renewal_row is not None else None
        elif event_type == "closing":
            if not event_ref:
                raise DocumentValidationError("Не выбрано сохранённое закрытие.")
            with open_readonly(
                paths.archive, busy_timeout_ms=settings.busy_timeout_ms
            ) as connection:
                archived = connection.execute(
                    """SELECT * FROM contracts_archive
                       WHERE operation_id = ? AND contract_id = ?""",
                    (event_ref, contract_ref),
                ).fetchone()
                contract = dict(archived) if archived is not None else None
            if contract is not None:
                with open_readonly(
                    paths.working, busy_timeout_ms=settings.busy_timeout_ms
                ) as connection:
                    dimension_row = connection.execute(
                        """SELECT cells.height_mm,
                                  COALESCE(cells.width_mm, defaults.width_mm) AS width_mm,
                                  COALESCE(cells.depth_mm, defaults.depth_mm) AS depth_mm
                           FROM cells CROSS JOIN vault_defaults defaults
                           WHERE cells.number = ?""",
                        (contract["cell_number"],),
                    ).fetchone()
                if dimension_row is None:
                    contract = None
                else:
                    contract.update(dict(dimension_row))
    except (DocumentValidationError, DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        if isinstance(exc, DocumentValidationError):
            raise
        raise DocumentReadError(NETWORK_ERROR_MESSAGE) from exc

    if contract is None:
        raise DocumentConflictError(
            "Сохранённый договор для формирования документов не найден."
        )
    if event_type == "renewal" and renewal is None:
        raise DocumentConflictError(
            "Сохранённое продление для формирования документа не найдено."
        )
    try:
        event_date = date.fromisoformat(
            str(
                renewal["renewal_date"]
                if renewal is not None
                else contract["close_date"]
                if event_type == "closing"
                else contract["created_at"]
            )[:10]
        )
        values = build_document_values(
            contract,
            creation_date=event_date,
            employee=employee,
            renewal=renewal,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DocumentValidationError(
            "Сохранённые данные договора нельзя подставить в документ."
        ) from exc
    cell = _safe_filename_part(str(contract["cell_number"]), "ячейка")
    client = _safe_filename_part(str(contract["client_full_name"]), "клиент")
    generated: list[GeneratedDocument] = []
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".safe-cells-bundle-", dir=output_directory
        ) as temporary_directory:
            staging_directory = Path(temporary_directory)
            for template in templates:
                display = _safe_filename_part(
                    str(template["display_name"]), "Документ"
                )
                output_name = (
                    f"{display}_Ячейка-{cell}_{client}_{event_date.isoformat()}.docx"
                )
                render_docx(
                    template_directory=settings.database_directory / "templates",
                    template_file_name=str(template["relative_file_name"]),
                    output_directory=staging_directory,
                    output_file_name=output_name,
                    values=values,
                    required_placeholders=_required_placeholders(
                        template["required_placeholders_json"]
                    ),
                )
                generated.append(GeneratedDocument(output_name))
            for document in generated:
                os.replace(
                    staging_directory / document.file_name,
                    output_directory / document.file_name,
                )
    except (DocumentTemplateError, DocumentPublishError, DocumentValidationError):
        raise
    except OSError as exc:
        raise DocumentPublishError(
            "Не удалось сохранить комплект документов в папку «Загрузки»."
        ) from exc
    return generated
