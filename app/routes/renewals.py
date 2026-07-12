"""HTTP endpoints for renewal quotes and confirmed renewals."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from app.config import Settings
from app.services.renewals import (
    RenewalBusyError,
    RenewalConflictError,
    RenewalNetworkError,
    RenewalReadError,
    RenewalValidationError,
    RenewalWriteError,
    RenewalWriteUncertainError,
    calculate_renewal_quote,
    renew_contract,
)


renewals_blueprint = Blueprint("renewals", __name__, url_prefix="/api/renewals")


@renewals_blueprint.post("/calculate")
def calculate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Переданы неверные данные расчёта."}), 400
    settings: Settings = current_app.extensions["safe_cells_settings"]
    try:
        quote = calculate_renewal_quote(
            settings,
            cell_number=payload.get("cell_number"),
            contract_ref=payload.get("contract_ref"),
            renewal_date=current_app.config["TODAY_PROVIDER"](),
            new_end_date_value=payload.get("new_end_date"),
            renewal_days_value=payload.get("renewal_days"),
        )
    except RenewalValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except RenewalConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except RenewalWriteError as exc:
        return jsonify({"message": str(exc)}), 500
    except RenewalReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(quote.to_dict())


@renewals_blueprint.post("")
def confirm():
    settings: Settings = current_app.extensions["safe_cells_settings"]
    timestamp_provider = current_app.config.get(
        "TIMESTAMP_PROVIDER", lambda: datetime.now().astimezone()
    )
    try:
        result = renew_contract(
            settings,
            payload=request.get_json(silent=True),
            employee=current_app.config["EMPLOYEE_PROVIDER"](),
            renewal_date=current_app.config["TODAY_PROVIDER"](),
            occurred_at=timestamp_provider(),
        )
    except RenewalValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except RenewalConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except RenewalBusyError as exc:
        return jsonify({"message": str(exc)}), 423
    except (RenewalNetworkError, RenewalWriteUncertainError) as exc:
        return jsonify({"message": str(exc)}), 503
    except RenewalWriteError as exc:
        return jsonify({"message": str(exc)}), 500
    return jsonify(result.to_dict()), 200 if result.repeated else 201
