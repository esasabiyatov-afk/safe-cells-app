"""Read-only HTTP API for the shared cell operation journal."""

from __future__ import annotations

from io import BytesIO

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from app.config import Settings
from app.services.journal import (
    JournalReadError,
    JournalValidationError,
    FILTER_LABELS,
    list_journal_entries,
    list_journal_report_entries,
)
from app.services.journal_reports import REPORT_MIMETYPE, build_journal_report


journal_blueprint = Blueprint("journal", __name__)


def _settings() -> Settings:
    return current_app.extensions["safe_cells_settings"]


@journal_blueprint.get("/journal")
def journal_page():
    """Show the journal in its own browser tab without reading databases."""

    return render_template("journal.html")


@journal_blueprint.get("/api/journal")
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


@journal_blueprint.get("/api/journal/report")
def journal_report():
    """Download the current journal selection as a real XLSX workbook."""

    current_app.config["EMPLOYEE_PROVIDER"]()
    filters = {
        "cell_number": request.args.get("cell_number"),
        "action": request.args.get("action"),
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
    }
    try:
        entries = list_journal_report_entries(_settings(), **filters)
        action = filters["action"]
        report_filters = {
            **filters,
            "action_label": FILTER_LABELS.get(action, "") if action else "",
        }
        generated_on = current_app.config["TODAY_PROVIDER"]()
        report = build_journal_report(
            entries,
            generated_on=generated_on,
            filters=report_filters,
        )
    except JournalValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except JournalReadError as exc:
        return jsonify({"message": str(exc)}), 503

    return send_file(
        BytesIO(report),
        mimetype=REPORT_MIMETYPE,
        as_attachment=True,
        download_name=f"Выписка_по_ячейкам_{generated_on.isoformat()}.xlsx",
        max_age=0,
    )
