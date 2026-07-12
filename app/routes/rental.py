"""Read-only rental calculator API."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.config import Settings
from app.services.rental_calculator import (
    CellUnavailableError,
    RentalDataError,
    RentalReadError,
    RentalValidationError,
    calculate_rental_quote,
)


rental_blueprint = Blueprint("rental", __name__, url_prefix="/api/rental")


@rental_blueprint.post("/calculate")
def calculate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Переданы неверные данные расчёта."}), 400
    settings: Settings = current_app.extensions["safe_cells_settings"]
    try:
        quote = calculate_rental_quote(
            settings,
            cell_number=payload.get("cell_number"),
            start_date_value=payload.get("start_date"),
            end_date_value=payload.get("end_date"),
            rent_days_value=payload.get("rent_days"),
            as_of_date=current_app.config["TODAY_PROVIDER"](),
        )
    except RentalValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except CellUnavailableError as exc:
        return jsonify({"message": str(exc)}), 409
    except RentalReadError as exc:
        return jsonify({"message": str(exc)}), 503
    except RentalDataError:
        return jsonify(
            {"message": "Не удалось рассчитать стоимость. Обратитесь к администратору"}
        ), 500
    return jsonify(quote.to_dict())
