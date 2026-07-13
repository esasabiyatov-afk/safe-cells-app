"""Shared employee directory and local-process employee selection."""

from hmac import compare_digest

from flask import Blueprint, current_app, jsonify, request

from app.services.employee import (
    EmployeeDirectoryReadError,
    EmployeeSelectionRequiredError,
    get_selected_employee,
    list_employees,
    select_employee,
)


employee_blueprint = Blueprint("employee", __name__, url_prefix="/api/employee")


def _manager():
    return current_app.extensions["safe_cells_employee_selection"]


def _settings():
    return current_app.extensions["safe_cells_settings"]


@employee_blueprint.get("")
def directory():
    try:
        employees = list_employees(_settings(), active_only=True)
        try:
            selected = get_selected_employee(_settings(), _manager())
        except EmployeeSelectionRequiredError:
            selected = None
    except EmployeeDirectoryReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(
        {
            "employees": [employee.to_dict() for employee in employees],
            "selected_employee_id": None if selected is None else selected.employee_id,
            "selected_employee_name": None if selected is None else selected.full_name,
            "selection_required": selected is None,
        }
    )


@employee_blueprint.post("/select")
def select():
    supplied_token = request.headers.get("X-Safe-Cells-Token", "")
    expected_token = current_app.extensions["safe_cells_private_token"]
    if not supplied_token or not compare_digest(supplied_token, expected_token):
        return jsonify({"message": "Выбор сотрудника не подтверждён."}), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"employee_id"}:
        return jsonify({"message": "Выберите сотрудника."}), 400
    try:
        employee = select_employee(_settings(), _manager(), payload["employee_id"])
    except EmployeeSelectionRequiredError as exc:
        return jsonify({"message": str(exc), "selection_required": True}), 409
    except EmployeeDirectoryReadError as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(employee.to_dict())
