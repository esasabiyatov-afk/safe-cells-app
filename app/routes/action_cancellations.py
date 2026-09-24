"""HTTP endpoint for cancelling the latest opening or renewal."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from app.config import Settings
from app.services.action_cancellations import (
    ActionCancellationBusyError,
    ActionCancellationConflictError,
    ActionCancellationNetworkError,
    ActionCancellationValidationError,
    ActionCancellationWriteError,
    ActionCancellationWriteUncertainError,
    cancel_contract_action,
)


action_cancellations_blueprint = Blueprint(
    "action_cancellations",
    __name__,
    url_prefix="/api/action-cancellations",
)


@action_cancellations_blueprint.post("")
def cancel():
    settings: Settings = current_app.extensions["safe_cells_settings"]
    timestamp_provider = current_app.config.get(
        "TIMESTAMP_PROVIDER", lambda: datetime.now().astimezone()
    )
    try:
        result = cancel_contract_action(
            settings,
            payload=request.get_json(silent=True),
            employee=current_app.config["EMPLOYEE_PROVIDER"](),
            occurred_at=timestamp_provider(),
        )
    except ActionCancellationValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except ActionCancellationConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except ActionCancellationBusyError as exc:
        return jsonify({"message": str(exc)}), 423
    except (
        ActionCancellationNetworkError,
        ActionCancellationWriteUncertainError,
    ) as exc:
        return jsonify({"message": str(exc)}), 503
    except ActionCancellationWriteError as exc:
        return jsonify({"message": str(exc)}), 500
    return jsonify(result.to_dict()), 200 if result.repeated else 201
