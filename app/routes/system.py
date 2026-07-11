"""Read-only system routes used before the main screen is implemented."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from app.config import Settings
from app.db.connections import DatabaseUnavailableError, check_database_pair


system_blueprint = Blueprint("system", __name__)


@system_blueprint.get("/health")
def health():
    settings: Settings = current_app.extensions["safe_cells_settings"]
    try:
        versions = check_database_pair(settings)
    except DatabaseUnavailableError as exc:
        return jsonify({"status": "unavailable", "message": str(exc)}), 503
    return jsonify({"status": "ok", "schema_versions": versions})
