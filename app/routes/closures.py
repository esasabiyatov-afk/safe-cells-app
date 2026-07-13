"""HTTP endpoints for contract closing quotes and confirmation."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from app.config import Settings
from app.routes.document_events import document_event_payload
from app.services.closures import (
    ClosureBusyError, ClosureConflictError, ClosureNetworkError, ClosureReadError,
    ClosureValidationError, ClosureWriteError, ClosureWriteUncertainError,
    calculate_closure_quote, close_contract,
)


closures_blueprint = Blueprint("closures", __name__, url_prefix="/api/closures")


@closures_blueprint.post("/calculate")
def calculate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Переданы неверные данные расчёта."}), 400
    settings: Settings = current_app.extensions["safe_cells_settings"]
    try:
        quote = calculate_closure_quote(
            settings,
            cell_number=payload.get("cell_number"),
            contract_ref=payload.get("contract_ref"),
            close_date=current_app.config["TODAY_PROVIDER"](),
            reason_code=payload.get("reason_code"),
        )
    except ClosureValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except ClosureConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except ClosureReadError as exc:
        return jsonify({"message": str(exc)}), 503
    except ClosureWriteError as exc:
        return jsonify({"message": str(exc)}), 500
    return jsonify(quote.to_dict())


@closures_blueprint.post("")
def confirm():
    settings: Settings = current_app.extensions["safe_cells_settings"]
    payload = request.get_json(silent=True)
    timestamp_provider = current_app.config.get(
        "TIMESTAMP_PROVIDER", lambda: datetime.now().astimezone()
    )
    try:
        result = close_contract(
            settings,
            payload=payload,
            employee=current_app.config["EMPLOYEE_PROVIDER"](),
            close_date=current_app.config["TODAY_PROVIDER"](),
            occurred_at=timestamp_provider(),
        )
    except ClosureValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except ClosureConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except ClosureBusyError as exc:
        return jsonify({"message": str(exc)}), 423
    except (ClosureNetworkError, ClosureWriteUncertainError) as exc:
        return jsonify({"message": str(exc)}), 503
    except ClosureWriteError as exc:
        return jsonify({"message": str(exc)}), 500
    response = result.to_dict()
    response.update(
        document_event_payload(
            event_type="closing",
            contract_ref=result.contract_ref,
            event_ref=str(payload.get("operation_id")) if isinstance(payload, dict) else None,
        )
    )
    return jsonify(response), 200 if result.repeated else 201
