"""Explicit private endpoint for repeat DOCX generation."""

from pathlib import Path
from flask import Blueprint, current_app, jsonify, request

from app.documents import DocumentPublishError, DocumentTemplateError
from app.routes.contracts import _private_request_payload
from app.services.documents import (
    DocumentConflictError, DocumentReadError, DocumentValidationError,
    generate_active_contract_document, list_active_templates,
)

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
        result = generate_active_contract_document(
            current_app.extensions["safe_cells_settings"],
            cell_number=payload.get("cell_number"), contract_ref=payload.get("contract_ref"),
            template_id=payload.get("template_id"),
            output_directory=Path(current_app.config["DOWNLOADS_DIRECTORY_PROVIDER"]()),
            creation_date=current_app.config["TODAY_PROVIDER"](),
            employee=current_app.config["EMPLOYEE_PROVIDER"](),
        )
    except (DocumentValidationError, DocumentTemplateError) as exc:
        return jsonify({"message": str(exc)}), 400
    except DocumentConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except DocumentReadError as exc:
        return jsonify({"message": str(exc)}), 503
    except DocumentPublishError as exc:
        return jsonify({"message": str(exc)}), 500
    return jsonify(result.to_dict()), 201
