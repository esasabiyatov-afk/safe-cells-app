"""HTTP endpoint for confirmed WhatsApp reminders."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from app.services.reminders import (
    ReminderBusyError,
    ReminderConflictError,
    ReminderNetworkError,
    ReminderValidationError,
    ReminderWriteError,
    ReminderWriteUncertainError,
    send_reminder,
)


reminders_blueprint = Blueprint(
    "reminders", __name__, url_prefix="/api/reminders"
)


@reminders_blueprint.post("")
def send():
    settings = current_app.extensions["safe_cells_settings"]
    timestamp_provider = current_app.config.get(
        "TIMESTAMP_PROVIDER", lambda: datetime.now().astimezone()
    )
    try:
        result = send_reminder(
            settings,
            payload=request.get_json(silent=True),
            employee=current_app.config["EMPLOYEE_PROVIDER"](),
            occurred_at=timestamp_provider(),
            as_of_date=current_app.config["TODAY_PROVIDER"](),
        )
    except ReminderValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except ReminderConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except ReminderBusyError as exc:
        return jsonify({"message": str(exc)}), 423
    except (ReminderNetworkError, ReminderWriteUncertainError) as exc:
        return jsonify({"message": str(exc)}), 503
    except ReminderWriteError as exc:
        return jsonify({"message": str(exc)}), 500
    return jsonify(result.to_dict()), 200
