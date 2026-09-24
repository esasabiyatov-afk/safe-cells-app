"""Best-effort DOCX preparation after a confirmed database operation."""

from pathlib import Path
import tempfile

from flask import current_app

from app.documents import DocumentPublishError, DocumentTemplateError
from app.services.documents import (
    DocumentConflictError,
    DocumentReadError,
    DocumentValidationError,
    generate_event_documents,
)
from app.services.document_downloads import publish_generated_documents
from app.services.employee import (
    EmployeeDirectoryReadError,
    EmployeeSelectionRequiredError,
)


def document_event_payload(
    *,
    event_type: str,
    contract_ref: str,
    event_ref: str | None,
    employee: str | None = None,
) -> dict[str, object]:
    """Return browser download handles or a warning without undoing committed data."""

    try:
        effective_employee = (
            employee
            if employee is not None
            else current_app.config["EMPLOYEE_PROVIDER"]()
        )
        with tempfile.TemporaryDirectory(prefix="safe-cells-documents-") as staging:
            output_directory = Path(staging)
            generated = generate_event_documents(
                current_app.extensions["safe_cells_settings"],
                event_type=event_type,
                contract_ref=contract_ref,
                event_ref=event_ref,
                output_directory=output_directory,
                employee=effective_employee,
            )
            if not generated:
                return {
                    "documents": [],
                    "document_warning": "Активные DOCX-шаблоны этого действия не настроены.",
                }
            published = publish_generated_documents(
                current_app.extensions["safe_cells_document_downloads"],
                output_directory=output_directory,
                generated=generated,
            )
            return {
                "documents": [document.to_dict() for document in published],
                "document_warning": None,
            }
    except (
        DocumentValidationError,
        DocumentTemplateError,
        DocumentConflictError,
        DocumentReadError,
        DocumentPublishError,
        EmployeeDirectoryReadError,
        EmployeeSelectionRequiredError,
    ) as exc:
        return {"documents": [], "document_warning": str(exc)}
    except OSError:
        return {
            "documents": [],
            "document_warning": "Не удалось подготовить документы для скачивания.",
        }
