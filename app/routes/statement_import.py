"""Private endpoint for reading an ABS opening statement."""

from __future__ import annotations

from hmac import compare_digest

from flask import Blueprint, current_app, jsonify, request

from app.services.statement_import import (
    StatementImportValidationError,
    extract_statement_data,
)


statement_import_blueprint = Blueprint(
    "statement_import", __name__, url_prefix="/api/contract-statements"
)


@statement_import_blueprint.post("/extract")
def extract():
    expected_token = current_app.extensions["safe_cells_private_token"]
    supplied_token = request.headers.get("X-Safe-Cells-Token", "")
    if not supplied_token or not compare_digest(supplied_token, expected_token):
        return jsonify({"message": "Доступ к данным не подтверждён."}), 403

    # The import fills a contract form and is unavailable before an employee
    # is selected. The document itself is never written to the DB.
    current_app.config["EMPLOYEE_PROVIDER"]()
    upload = request.files.get("file")
    if upload is None or upload.stream is None:
        return jsonify({"message": "Выберите заявление в формате DOCX."}), 400
    try:
        result = extract_statement_data(
            upload.stream,
            file_name=upload.filename,
            as_of_date=current_app.config["TODAY_PROVIDER"](),
        )
    except StatementImportValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    return jsonify(result.to_dict())
