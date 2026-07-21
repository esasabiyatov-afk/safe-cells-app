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

_FILTER_KEYS = frozenset(
    {
        "cell_number",
        "action",
        "date_from",
        "date_to",
        "client_name",
        "employee",
    }
)


def _request_filters(*, include_page: bool) -> dict[str, object | None]:
    payload = request.get_json(silent=True)
    allowed = _FILTER_KEYS | ({"page", "page_size"} if include_page else set())
    if not isinstance(payload, dict) or not set(payload).issubset(allowed):
        raise JournalValidationError("Условия журнала переданы неверно.")
    return {key: payload.get(key) for key in allowed}


def _settings() -> Settings:
    return current_app.extensions["safe_cells_settings"]


@journal_blueprint.get("/journal")
def journal_page():
    """Show the journal in its own browser tab without reading databases."""

    return render_template(
        "journal.html",
        private_token=current_app.extensions["safe_cells_private_token"],
        runtime_enabled="safe_cells_runtime_lifecycle" in current_app.extensions,
    )


@journal_blueprint.post("/api/journal")
def journal_list():
    # The ordinary journal is available after the mandatory employee selection.
    current_app.config["EMPLOYEE_PROVIDER"]()
    try:
        payload = list_journal_entries(
            _settings(), **_request_filters(include_page=True)
        )
    except JournalValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except JournalReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(payload)


@journal_blueprint.post("/api/journal/report")
def journal_report():
    """Download the current journal selection as a real XLSX workbook."""

    current_app.config["EMPLOYEE_PROVIDER"]()
    try:
        filters = _request_filters(include_page=False)
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
