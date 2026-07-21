"""Health checks and protected local-process lifecycle routes."""

from __future__ import annotations

from hmac import compare_digest
from typing import Any

from flask import Blueprint, current_app, jsonify, request

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


def _runtime() -> Any:
    lifecycle = current_app.extensions.get("safe_cells_runtime_lifecycle")
    if lifecycle is None:
        raise ValueError("Управление локальным запуском недоступно.")
    return lifecycle


def _authorized() -> bool:
    supplied = request.headers.get("X-Safe-Cells-Token", "")
    expected = current_app.extensions["safe_cells_private_token"]
    return bool(supplied) and compare_digest(supplied, expected)


def _tab_id() -> object:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"tab_id"}:
        raise ValueError("Данные вкладки переданы неверно.")
    return payload["tab_id"]


@system_blueprint.post("/api/runtime/heartbeat")
def runtime_heartbeat():
    if not _authorized():
        return jsonify({"message": "Недействительный токен локального экземпляра."}), 403
    try:
        lifecycle = _runtime()
        lifecycle.heartbeat(_tab_id())
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    return jsonify({"status": "ok"})


@system_blueprint.post("/api/runtime/disconnect")
def runtime_disconnect():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not set(payload).issubset({"tab_id", "token"}):
        return jsonify({"message": "Данные вкладки переданы неверно."}), 400
    supplied_body_token = payload.get("token", "")
    expected = current_app.extensions["safe_cells_private_token"]
    body_authorized = isinstance(supplied_body_token, str) and bool(
        supplied_body_token
    ) and compare_digest(supplied_body_token, expected)
    if not _authorized() and not body_authorized:
        return jsonify({"message": "Недействительный токен локального экземпляра."}), 403
    try:
        lifecycle = _runtime()
        lifecycle.disconnect(payload.get("tab_id"))
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    return jsonify({"status": "closing-if-last-tab"})


@system_blueprint.post("/api/runtime/shutdown")
def runtime_shutdown():
    if not _authorized():
        return jsonify({"message": "Недействительный токен локального экземпляра."}), 403
    try:
        _runtime().request_shutdown()
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    return jsonify({"status": "shutting-down"})
