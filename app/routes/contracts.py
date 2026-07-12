"""HTTP endpoint for confirmed contract creation."""

from __future__ import annotations

from datetime import datetime
from hmac import compare_digest

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
from app.services.contract_details import (
    ActiveContractNotFoundError,
    ContractDetailsReadError,
    ContractDetailsValidationError,
    get_contract_client_name,
    get_private_contract_details,
)


contracts_blueprint = Blueprint("contracts", __name__, url_prefix="/api/contracts")


def _private_request_payload():
    expected_token = current_app.extensions["safe_cells_private_token"]
    supplied_token = request.headers.get("X-Safe-Cells-Token", "")
    if not supplied_token or not compare_digest(supplied_token, expected_token):
        return None, (jsonify({"message": "Доступ к данным не подтверждён."}), 403)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify({"message": "Переданы неверные данные запроса."}), 400)
    return payload, None


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
            as_of_date=current_app.config["TODAY_PROVIDER"](),
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


@contracts_blueprint.post("/private")
def private_details():
    payload, error_response = _private_request_payload()
    if error_response is not None:
        return error_response
    settings: Settings = current_app.extensions["safe_cells_settings"]
    try:
        details = get_private_contract_details(
            settings,
            cell_number=payload.get("cell_number"),
            contract_ref=payload.get("contract_ref"),
        )
    except ContractDetailsValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except ActiveContractNotFoundError as exc:
        return jsonify({"message": str(exc)}), 409
    except ContractDetailsReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(details.to_dict())


@contracts_blueprint.post("/client-name")
def client_name():
    payload, error_response = _private_request_payload()
    if error_response is not None:
        return error_response
    settings: Settings = current_app.extensions["safe_cells_settings"]
    try:
        name = get_contract_client_name(
            settings,
            cell_number=payload.get("cell_number"),
            contract_ref=payload.get("contract_ref"),
        )
    except ContractDetailsValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except ActiveContractNotFoundError as exc:
        return jsonify({"message": str(exc)}), 409
    except ContractDetailsReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify({"client_full_name": name})
