"""Read active contract data and generate a document from an approved template."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
import sqlite3
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


@dataclass(frozen=True, slots=True)
class GeneratedDocument:
    file_name: str
    def to_dict(self) -> dict[str, str]:
        return {"file_name": self.file_name, "message": "Документ сохранён в папку «Загрузки»."}


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
                "SELECT template_id, display_name FROM document_templates WHERE is_active = 1 ORDER BY display_name, template_id"
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
    try:
        required = json.loads(template["required_placeholders_json"])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DocumentValidationError("Настройка обязательных полей шаблона повреждена.") from exc

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
