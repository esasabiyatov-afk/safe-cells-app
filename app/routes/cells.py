"""Read-only API for the main cells screen."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.config import Settings
from app.services.cells import (
    CellsReadError,
    InvalidStoredDataError,
    list_cells,
    search_cell_numbers,
)


cells_blueprint = Blueprint("cells", __name__, url_prefix="/api/cells")


def _settings() -> Settings:
    return current_app.extensions["safe_cells_settings"]


@cells_blueprint.get("")
def cells_list():
    today_provider = current_app.config["TODAY_PROVIDER"]
    try:
        payload = list_cells(_settings(), as_of_date=today_provider())
    except CellsReadError as exc:
        return jsonify({"message": str(exc)}), 503
    except InvalidStoredDataError:
        return jsonify(
            {"message": "В базе обнаружены некорректные данные. Обратитесь к администратору"}
        ), 500
    return jsonify(payload)


@cells_blueprint.post("/search")
def cells_search():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("query"), str):
        return jsonify({"message": "Укажите строку поиска"}), 400
    query = payload["query"].strip()
    if len(query) > 100:
        return jsonify({"message": "Строка поиска слишком длинная"}), 400
    try:
        numbers = search_cell_numbers(_settings(), query=query)
    except CellsReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify({"matched_numbers": numbers})
