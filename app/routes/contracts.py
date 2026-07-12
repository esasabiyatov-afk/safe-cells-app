"""HTTP endpoint for confirmed contract creation."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from app.config import Settings
from app.services.contracts import (
    ContractBusyError,
    ContractConflictError,
    ContractNetworkError,
    ContractValidationError,
    ContractWriteError,
    ContractWriteUncertainError,
    create_contract,
)


contracts_blueprint = Blueprint("contracts", __name__, url_prefix="/api/contracts")


@contracts_blueprint.post("")
def create():
    settings: Settings = current_app.extensions["safe_cells_settings"]
    employee = current_app.config["EMPLOYEE_PROVIDER"]()
    timestamp_provider = current_app.config.get(
        "TIMESTAMP_PROVIDER", lambda: datetime.now().astimezone()
    )
    try:
        result = create_contract(
            settings,
            payload=request.get_json(silent=True),
            employee=employee,
            occurred_at=timestamp_provider(),
        )
    except ContractValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except ContractConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except ContractBusyError as exc:
        return jsonify({"message": str(exc)}), 423
    except (ContractNetworkError, ContractWriteUncertainError) as exc:
        return jsonify({"message": str(exc)}), 503
    except ContractWriteError as exc:
        return jsonify({"message": str(exc)}), 500
    status = 200 if result.repeated else 201
    return jsonify(result.to_dict()), status
