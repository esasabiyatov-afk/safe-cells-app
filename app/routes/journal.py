"""Read-only HTTP API for the shared cell operation journal."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.config import Settings
from app.services.journal import (
    JournalReadError,
    JournalValidationError,
    list_journal_entries,
)


journal_blueprint = Blueprint("journal", __name__, url_prefix="/api/journal")


def _settings() -> Settings:
    return current_app.extensions["safe_cells_settings"]


@journal_blueprint.get("")
def journal_list():
    # The ordinary journal is available after the mandatory employee selection.
    current_app.config["EMPLOYEE_PROVIDER"]()
    try:
        payload = list_journal_entries(
            _settings(),
            cell_number=request.args.get("cell_number"),
            action=request.args.get("action"),
            date_from=request.args.get("date_from"),
            date_to=request.args.get("date_to"),
            page=request.args.get("page"),
            page_size=request.args.get("page_size"),
        )
    except JournalValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except JournalReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(payload)
