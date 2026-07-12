from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from docx import Document
import pytest

from app import create_app
from app.db.connections import open_write
from app.documents import DocumentPublishError, DocumentTemplateError, render_docx
from app.services.documents import generate_active_contract_document


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
