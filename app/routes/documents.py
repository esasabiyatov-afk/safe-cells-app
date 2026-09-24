"""Explicit private endpoint for repeat DOCX generation."""

from io import BytesIO
from pathlib import Path
import tempfile

from flask import Blueprint, current_app, jsonify, request, send_file

from app.documents import DocumentPublishError, DocumentTemplateError
from app.routes.contracts import _private_request_payload
from app.services.documents import (
    DocumentConflictError, DocumentReadError, DocumentValidationError,
    generate_active_contract_document, list_active_templates,
)
from app.services.document_downloads import publish_generated_documents

documents_blueprint = Blueprint("documents", __name__, url_prefix="/api/documents")

@documents_blueprint.post("/templates")
def templates():
    payload, error_response = _private_request_payload()
    if error_response is not None:
        return error_response
    try:
        items = list_active_templates(
            current_app.extensions["safe_cells_settings"],
            cell_number=payload.get("cell_number"), contract_ref=payload.get("contract_ref"),
        )
    except DocumentValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except DocumentConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except DocumentReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify({"templates": items})

@documents_blueprint.post("/generate")
def generate():
    payload, error_response = _private_request_payload()
    if error_response is not None:
        return error_response
    try:
        employee_full_name = current_app.config["DOCUMENT_EMPLOYEE_PROVIDER"](
            payload.pop("document_employee_id", None)
        )
        with tempfile.TemporaryDirectory(prefix="safe-cells-document-") as staging:
            output_directory = Path(staging)
            result = generate_active_contract_document(
                current_app.extensions["safe_cells_settings"],
                cell_number=payload.get("cell_number"), contract_ref=payload.get("contract_ref"),
                template_id=payload.get("template_id"),
                output_directory=output_directory,
                creation_date=current_app.config["TODAY_PROVIDER"](),
                employee=employee_full_name,
            )
            published = publish_generated_documents(
                current_app.extensions["safe_cells_document_downloads"],
                output_directory=output_directory,
                generated=[result],
            )
    except (DocumentValidationError, DocumentTemplateError) as exc:
        return jsonify({"message": str(exc)}), 400
    except DocumentConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except DocumentReadError as exc:
        return jsonify({"message": str(exc)}), 503
    except DocumentPublishError as exc:
        return jsonify({"message": str(exc)}), 500
    except OSError:
        return jsonify({"message": "Не удалось подготовить документ для скачивания."}), 500
    response = result.to_dict()
    response["documents"] = [published[0].to_dict()]
    return jsonify(response), 201


@documents_blueprint.post("/download")
def download():
    payload, error_response = _private_request_payload()
    if error_response is not None:
        return error_response
    artifact = current_app.extensions["safe_cells_document_downloads"].claim(
        payload.get("download_id")
    )
    if artifact is None:
        return jsonify(
            {
                "message": (
                    "Документ уже скачан или время его получения истекло. "
                    "Сформируйте документ повторно."
                )
            }
        ), 410
    return send_file(
        BytesIO(artifact.content),
        mimetype=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        as_attachment=True,
        download_name=artifact.file_name,
        max_age=0,
    )
