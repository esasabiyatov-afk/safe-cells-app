from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from docx import Document
import pytest

from app import create_app
from app.db.connections import open_write
from app.documents import DocumentPublishError, DocumentTemplateError, render_docx
from app.services.documents import build_document_values, generate_active_contract_document
from app.services.employee import save_employee_full_name
from app.documents.values import (
    amount_in_words_ky, amount_in_words_ru,
    format_document_issue_date, format_kyrgyz_date,
    format_quoted_kyrgyz_date, format_quoted_kyrgyz_date_stem,
    format_quoted_russian_date, format_russian_date,
)


def _template(path: Path, *, unknown: bool = False) -> None:
    document = Document()
    paragraph = document.add_paragraph("ТЕСТОВЫЙ ШАБЛОН — не банковский документ\nКлиент: ")
    paragraph.add_run("{{CLIENT_")
    paragraph.add_run("FULL_NAME}}")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Ячейка"
    table.cell(0, 1).text = "{{SAFE_NUMBER}}"
    section = document.sections[0]
    section.header.paragraphs[0].text = "Дата: {{CREATION_DATE}}"
    section.footer.paragraphs[0].text = "{{UNKNOWN_FIELD}}" if unknown else "ТЕСТ"
    document.save(path)


def test_renderer_replaces_split_runs_tables_and_header(tmp_path: Path):
    templates = tmp_path / "templates"
    downloads = tmp_path / "downloads"
    templates.mkdir()
    _template(templates / "test.docx")

    result = render_docx(
        template_directory=templates, template_file_name="test.docx",
        output_directory=downloads, output_file_name="result.docx",
        values={"CLIENT_FULL_NAME": "Вымышленный Клиент", "SAFE_NUMBER": "41", "CREATION_DATE": "2026-07-13"},
        required_placeholders=["CLIENT_FULL_NAME", "SAFE_NUMBER", "CREATION_DATE"],
    )

    rendered = Document(result)
    assert "Вымышленный Клиент" in rendered.paragraphs[0].text
    assert rendered.tables[0].cell(0, 1).text == "41"
    assert "2026-07-13" in rendered.sections[0].header.paragraphs[0].text
    assert not list(downloads.glob(".safe-cells-*.docx"))


def test_renderer_rejects_missing_required_placeholder(tmp_path: Path):
    templates = tmp_path / "templates"
    templates.mkdir()
    _template(templates / "test.docx")
    with pytest.raises(DocumentTemplateError, match="ACCOUNT_NUMBER"):
        render_docx(
            template_directory=templates, template_file_name="test.docx",
            output_directory=tmp_path / "downloads", output_file_name="result.docx",
            values={"CLIENT_FULL_NAME": "Тест", "SAFE_NUMBER": "1", "CREATION_DATE": "2026-07-13"},
            required_placeholders=["ACCOUNT_NUMBER"],
        )


def test_renderer_rejects_unknown_placeholder_and_path_escape(tmp_path: Path):
    templates = tmp_path / "templates"
    templates.mkdir()
    _template(templates / "unknown.docx", unknown=True)
    with pytest.raises(DocumentTemplateError, match="UNKNOWN_FIELD"):
        render_docx(
            template_directory=templates, template_file_name="unknown.docx",
            output_directory=tmp_path / "downloads", output_file_name="result.docx",
            values={"CLIENT_FULL_NAME": "Тест", "SAFE_NUMBER": "1", "CREATION_DATE": "2026-07-13"},
            required_placeholders=[],
        )


def test_renderer_removes_temporary_file_after_publish_failure(tmp_path: Path, monkeypatch):
    templates = tmp_path / "templates"
    downloads = tmp_path / "downloads"
    templates.mkdir()
    _template(templates / "test.docx")
    monkeypatch.setattr("app.documents.renderer.os.replace", lambda *args: (_ for _ in ()).throw(OSError("test failure")))
    with pytest.raises(DocumentPublishError, match="Загрузки"):
        render_docx(
            template_directory=templates, template_file_name="test.docx",
            output_directory=downloads, output_file_name="result.docx",
            values={"CLIENT_FULL_NAME": "Тест", "SAFE_NUMBER": "1", "CREATION_DATE": "2026-07-13"},
            required_placeholders=["CLIENT_FULL_NAME"],
        )
    assert not list(downloads.glob(".safe-cells-*.docx"))
    assert not (downloads / "result.docx").exists()
    with pytest.raises(DocumentTemplateError, match="внутри общей папки"):
        render_docx(
            template_directory=templates, template_file_name="..\\outside.docx",
            output_directory=tmp_path, output_file_name="result.docx", values={}, required_placeholders=[],
        )


def test_active_contract_document_and_private_endpoint(
    settings, initialized_databases, insert_test_contract, tmp_path: Path
):
    insert_test_contract(cell_number="41", start_date="2026-07-01", end_date="2026-07-30", client_name="Вымышленный Клиент")
    templates = settings.database_directory / "templates"
    templates.mkdir()
    _template(templates / "TEST_ONLY.docx")
    with open_write(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO document_templates VALUES(?, ?, ?, ?, ?, 1, ?, ?)",
            ("test-template", "TEST_ONLY", "ТЕСТОВЫЙ-ДОКУМЕНТ", "TEST_ONLY.docx",
             json.dumps(["CLIENT_FULL_NAME", "SAFE_NUMBER", "CREATION_DATE"]),
             "2026-07-13T10:00:00+06:00", "test-user"),
        )
        connection.commit()
    downloads = tmp_path / "downloads"

    result = generate_active_contract_document(
        settings, cell_number="41", contract_ref="contract-test-41",
        template_id="test-template", output_directory=downloads,
        creation_date=date(2026, 7, 13), employee="test-user",
    )
    assert result.file_name.startswith("ТЕСТОВЫЙ-ДОКУМЕНТ_Ячейка-41_Вымышленный-Клиент_")
    assert (downloads / result.file_name).is_file()

    app = create_app(settings)
    app.config.update(TODAY_PROVIDER=lambda: date(2026, 7, 13), DOWNLOADS_DIRECTORY_PROVIDER=lambda: downloads)
    save_employee_full_name(
        app.config["EMPLOYEE_PROFILE_PATH"], app.config["EMPLOYEE_PROVIDER"](),
        "Тестовый Сотрудник",
    )
    token = app.extensions["safe_cells_private_token"]
    templates_response = app.test_client().post(
        "/api/documents/templates", headers={"X-Safe-Cells-Token": token},
        json={"cell_number": "41", "contract_ref": "contract-test-41"},
    )
    assert templates_response.status_code == 200
    assert templates_response.get_json()["templates"] == [
        {"template_id": "test-template", "display_name": "ТЕСТОВЫЙ-ДОКУМЕНТ"}
    ]
    response = app.test_client().post(
        "/api/documents/generate", headers={"X-Safe-Cells-Token": token},
        json={"cell_number": "41", "contract_ref": "contract-test-41", "template_id": "test-template"},
    )
    assert response.status_code == 201
    assert response.get_json()["message"] == "Документ сохранён в папку «Загрузки»."
    assert not list(settings.database_directory.glob("*.docx"))


def test_document_endpoint_does_not_disclose_without_token(settings, initialized_databases):
    app = create_app(settings)
    response = app.test_client().post("/api/documents/generate", json={})
    assert response.status_code == 403


def test_approved_date_and_deposit_formats():
    value = date(2026, 5, 22)
    assert format_russian_date(value) == "22 мая 2026 г."
    assert format_kyrgyz_date(value) == "22-май 2026-ж."
    assert format_document_issue_date(date(2017, 9, 12)) == "12.09.2017-ж/г."
    assert format_quoted_russian_date(value) == "«22» мая 2026 г."
    assert format_quoted_kyrgyz_date(value) == "«22» май 2026-ж."
    assert format_quoted_kyrgyz_date_stem(value) == "«22» май 2026"
    assert amount_in_words_ru(1500) == "Одна тысяча пятьсот"
    assert amount_in_words_ky(1500) == "Бир миң беш жүз"


def test_renderer_supports_split_bank_square_codes(tmp_path: Path):
    templates = tmp_path / "templates"
    templates.mkdir()
    document = Document()
    paragraph = document.add_paragraph("Клиент: ")
    split_start = paragraph.add_run("[Клиент.")
    split_start.bold = True
    paragraph.add_run("ФИО]")
    suffix = paragraph.add_run("; сумма [Сумма]")
    suffix.italic = True
    document.save(templates / "bank.docx")
    result = render_docx(
        template_directory=templates, template_file_name="bank.docx",
        output_directory=tmp_path / "downloads", output_file_name="result.docx",
        values={"Клиент.ФИО": "Вымышленный Клиент", "Сумма": 450},
        required_placeholders=["Клиент.ФИО", "Сумма"],
    )
    rendered = Document(result).paragraphs[0]
    assert rendered.text == "Клиент: Вымышленный Клиент; сумма 450"
    assert rendered.runs[1].bold is True
    assert rendered.runs[3].italic is True


def test_renewal_codes_keep_original_contract_start_and_specific_period(
    tmp_path: Path,
):
    contract = {
        "client_full_name": "Вымышленный Клиент",
        "id_card_number": "TEST-000000",
        "id_card_issuer": "Тестовый орган",
        "id_card_issue_date": "2017-09-12",
        "account_number": "TEST-ACCOUNT-001",
        "cell_number": "41",
        "height_mm": 50,
        "width_mm": 220,
        "depth_mm": 330,
        "start_date": "2026-07-12",
        "end_date": "2026-09-18",
        "rent_days": 30,
        "rent_price_minor": 450,
        "deposit_amount_minor": 1500,
    }
    renewal = {
        "new_start_date": "2026-08-12",
        "new_end_date": "2026-09-18",
        "renewal_days": 38,
        "renewal_price_minor": 380,
    }
    values = build_document_values(
        contract,
        creation_date=date(2026, 8, 12),
        employee="Тестовый Сотрудник",
        renewal=renewal,
    )
    assert values["Договор.НачалоД"] == "«12» июля 2026 г."
    assert values["Договор.НачалоДК"] == "«12» июль 2026"
    assert values["Продление.Начало"] == "«12» августа 2026 г."
    assert values["Продление.Конец"] == "«18» сентября 2026 г."
    assert values["Продление.НачалоК"] == "«12» август 2026-ж."
    assert values["Продление.КонецК"] == "«18» сентябрь 2026-ж."
    assert values["Продление.Сумма"] == 380
    assert values["Продление.Срок"] == 38

    templates = tmp_path / "templates"
    templates.mkdir()
    document = Document()
    document.add_paragraph(
        "[Договор.НачалоДК]-жылдагы | [Договор.НачалоД] | "
        "[Продление.Начало] | [Продление.Конец] | "
        "[Продление.НачалоК] | [Продление.КонецК] | "
        "[Продление.Сумма] | [Продление.Срок]"
    )
    document.save(templates / "renewal.docx")
    required = [
        "Договор.НачалоДК",
        "Договор.НачалоД",
        "Продление.Начало",
        "Продление.Конец",
        "Продление.НачалоК",
        "Продление.КонецК",
        "Продление.Сумма",
        "Продление.Срок",
    ]
    result = render_docx(
        template_directory=templates,
        template_file_name="renewal.docx",
        output_directory=tmp_path / "downloads",
        output_file_name="result.docx",
        values=values,
        required_placeholders=required,
    )
    text = Document(result).paragraphs[0].text
    assert "«12» июль 2026-жылдагы" in text
    assert "2026--жылдагы" not in text
    assert "[Продление." not in text
