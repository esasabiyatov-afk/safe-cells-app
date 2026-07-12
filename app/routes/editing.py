"""Active-contract editing endpoint."""

from datetime import datetime
from flask import Blueprint, current_app, jsonify, request

from app.services.editing import (
    EditingBusyError, EditingConflictError, EditingNetworkError,
    EditingValidationError, EditingWriteError, EditingWriteUncertainError,
    edit_contract,
)

editing_blueprint = Blueprint("editing", __name__, url_prefix="/api/contracts")

@editing_blueprint.post("/edit")
def edit():
    settings = current_app.extensions["safe_cells_settings"]
    try:
        result = edit_contract(settings, payload=request.get_json(silent=True),
            employee=current_app.config["EMPLOYEE_PROVIDER"](),
            occurred_at=current_app.config.get("TIMESTAMP_PROVIDER", lambda: datetime.now().astimezone())())
    except EditingValidationError as exc: return jsonify({"message": str(exc)}), 400
    except EditingConflictError as exc: return jsonify({"message": str(exc)}), 409
    except EditingBusyError as exc: return jsonify({"message": str(exc)}), 423
    except (EditingNetworkError, EditingWriteUncertainError) as exc: return jsonify({"message": str(exc)}), 503
    except EditingWriteError as exc: return jsonify({"message": str(exc)}), 500
    return jsonify(result.to_dict())
