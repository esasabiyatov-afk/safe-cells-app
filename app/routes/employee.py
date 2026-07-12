"""Local employee display-name setup for the current Windows account."""

from hmac import compare_digest
from flask import Blueprint, current_app, jsonify, request

from app.services.employee import (
    EmployeeProfileError,
    get_employee_full_name,
    save_employee_full_name,
)


employee_blueprint = Blueprint("employee", __name__, url_prefix="/api/employee")


@employee_blueprint.get("/profile")
def profile():
    username = current_app.config["EMPLOYEE_PROVIDER"]()
    try:
        full_name = get_employee_full_name(
            current_app.config["EMPLOYEE_PROFILE_PATH"], username
        )
    except EmployeeProfileError as exc:
        return jsonify({"message": str(exc)}), 500
    return jsonify(
        {"username": username, "full_name": full_name, "profile_required": full_name is None}
    )


@employee_blueprint.post("/profile")
def save_profile():
    supplied_token = request.headers.get("X-Safe-Cells-Token", "")
    expected_token = current_app.extensions["safe_cells_private_token"]
    if not supplied_token or not compare_digest(supplied_token, expected_token):
        return jsonify({"message": "Доступ к настройке сотрудника не подтверждён."}), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"full_name"}:
        return jsonify({"message": "Переданы неверные данные сотрудника."}), 400
    username = current_app.config["EMPLOYEE_PROVIDER"]()
    try:
        full_name = save_employee_full_name(
            current_app.config["EMPLOYEE_PROFILE_PATH"], username, payload.get("full_name")
        )
    except EmployeeProfileError as exc:
        return jsonify({"message": str(exc)}), 400
    return jsonify({"username": username, "full_name": full_name})
