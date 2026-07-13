"""Best-effort DOCX publication after a confirmed database operation."""

from pathlib import Path

from flask import current_app

from app.documents import DocumentPublishError, DocumentTemplateError
from app.services.documents import (
    DocumentConflictError,
    DocumentReadError,
    DocumentValidationError,
    generate_event_documents,
)
from app.services.employee import EmployeeProfileError, get_employee_full_name


def document_event_payload(
    *, event_type: str, contract_ref: str, event_ref: str | None
) -> dict[str, object]:
    """Return generated filenames or a warning without undoing committed data."""

    try:
        username = current_app.config["EMPLOYEE_PROVIDER"]()
        employee = get_employee_full_name(
            current_app.config["EMPLOYEE_PROFILE_PATH"], username
        )
        if employee is None:
            raise DocumentValidationError(
                "Документы не сформированы: укажите полные фамилию и имя сотрудника."
            )
        generated = generate_event_documents(
            current_app.extensions["safe_cells_settings"],
            event_type=event_type,
            contract_ref=contract_ref,
            event_ref=event_ref,
            output_directory=Path(
                current_app.config["DOWNLOADS_DIRECTORY_PROVIDER"]()
            ),
            employee=employee,
        )
        if not generated:
            return {
                "documents": [],
                "document_warning": "Активные DOCX-шаблоны этого действия не настроены.",
            }
        return {
            "documents": [document.file_name for document in generated],
            "document_warning": None,
        }
    except (
        DocumentValidationError,
        DocumentTemplateError,
        DocumentConflictError,
        DocumentReadError,
        DocumentPublishError,
        EmployeeProfileError,
    ) as exc:
        return {"documents": [], "document_warning": str(exc)}
