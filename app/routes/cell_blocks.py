"""HTTP routes for explicit non-contract cell occupation states."""

from __future__ import annotations

from hmac import compare_digest

from flask import Blueprint, current_app, jsonify, request

from app.config import Settings
from app.services.cell_blocks import (
    CellBlockBusyError,
    CellBlockConflictError,
    CellBlockNetworkError,
    CellBlockReadError,
    CellBlockValidationError,
    CellBlockWriteError,
    CellBlockWriteUncertainError,
    lost_key_client_name,
    occupy_cell_by_bank,
    release_cell_block,
)


cell_blocks_blueprint = Blueprint(
    "cell_blocks", __name__, url_prefix="/api/cell-blocks"
)


def _settings() -> Settings:
    return current_app.extensions["safe_cells_settings"]


def _write_error(error: Exception):
    if isinstance(error, CellBlockValidationError):
        return jsonify({"message": str(error)}), 400
    if isinstance(error, CellBlockConflictError):
        return jsonify({"message": str(error)}), 409
    if isinstance(error, CellBlockBusyError):
        return jsonify({"message": str(error)}), 423
    if isinstance(error, CellBlockWriteUncertainError):
        return jsonify({"message": str(error), "result_uncertain": True}), 503
    if isinstance(error, (CellBlockNetworkError, CellBlockWriteError)):
        return jsonify({"message": str(error)}), 503
    raise error


@cell_blocks_blueprint.post("/bank")
def occupy_bank():
    try:
        result = occupy_cell_by_bank(
            _settings(),
            payload=request.get_json(silent=True),
            employee=current_app.config["EMPLOYEE_PROVIDER"](),
            occurred_at=current_app.config["NOW_PROVIDER"](),
        )
    except Exception as exc:
        return _write_error(exc)
    return jsonify(result.to_dict()), 200 if result.repeated else 201


@cell_blocks_blueprint.post("/release/<block_kind>")
def release(block_kind: str):
    try:
        result = release_cell_block(
            _settings(),
            payload=request.get_json(silent=True),
            expected_kind=block_kind,
            employee=current_app.config["EMPLOYEE_PROVIDER"](),
            occurred_at=current_app.config["NOW_PROVIDER"](),
        )
    except Exception as exc:
        return _write_error(exc)
    return jsonify(result.to_dict()), 200 if result.repeated else 201


@cell_blocks_blueprint.post("/lost-key-client")
def lost_key_client():
    supplied_token = request.headers.get("X-Safe-Cells-Token", "")
    expected_token = current_app.extensions["safe_cells_private_token"]
    if not supplied_token or not compare_digest(supplied_token, expected_token):
        return jsonify({"message": "Запрос данных клиента не подтверждён."}), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"cell_number"}:
        return jsonify({"message": "Укажите номер ячейки."}), 400
    try:
        name = lost_key_client_name(_settings(), cell_number=payload["cell_number"])
    except CellBlockValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except CellBlockConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except CellBlockReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify({"client_full_name": name})
