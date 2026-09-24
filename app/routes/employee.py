"""Shared employee directory and local-process employee selection."""

from datetime import datetime
from hmac import compare_digest

from flask import Blueprint, current_app, jsonify, request

from app.services.admin_auth import (
    AdminAuthenticationError,
    AdminPasswordError,
)
from app.services.admin_settings import (
    AdminBusyError,
    AdminConflictError,
    AdminNetworkError,
    AdminValidationError,
    AdminWriteError,
    AdminWriteUncertainError,
    get_admin_identity,
    get_admin_password_hash,
    setup_admin_identity,
)
from app.services.employee import (
    EmployeeDirectoryReadError,
    EmployeeProfileError,
    EmployeeSelectionRequiredError,
    get_admin_full_name,
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
        admin = get_admin_identity(_settings())
        if _manager().is_admin():
            selected = None
            selected_kind = "admin"
            selected_name = get_admin_full_name(_settings())
        else:
            try:
                selected = get_selected_employee(_settings(), _manager())
            except EmployeeSelectionRequiredError:
                selected = None
            selected_kind = "employee" if selected is not None else None
            selected_name = None if selected is None else selected.full_name
    except (EmployeeDirectoryReadError, AdminNetworkError, AdminWriteError) as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(
        {
            "employees": [employee.to_dict() for employee in employees],
            "admin": admin,
            "selected_kind": selected_kind,
            "selected_employee_id": None if selected is None else selected.employee_id,
            "selected_employee_name": selected_name,
            "selection_required": selected_kind is None,
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
    current_app.extensions["safe_cells_admin_access"].revoke_all()
    return jsonify(employee.to_dict())


@employee_blueprint.post("/admin-select")
def select_admin():
    supplied_token = request.headers.get("X-Safe-Cells-Token", "")
    expected_token = current_app.extensions["safe_cells_private_token"]
    if not supplied_token or not compare_digest(supplied_token, expected_token):
        return jsonify({"message": "Вход администратора не подтверждён."}), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Введите данные администратора."}), 400
    try:
        identity = get_admin_identity(_settings())
        if identity["configured"]:
            if set(payload) != {"password"}:
                raise AdminValidationError("Введите административный пароль.")
        else:
            if set(payload) != {
                "operation_id",
                "full_name",
                "password",
                "password_confirmation",
            }:
                raise AdminValidationError(
                    "Введите ФИО администратора и создайте пароль."
                )
            if payload["password"] != payload["password_confirmation"]:
                raise AdminValidationError("Пароли не совпадают.")
            setup_admin_identity(
                _settings(),
                operation_id=payload["operation_id"],
                full_name=payload["full_name"],
                password=payload["password"],
                occurred_at=current_app.config.get(
                    "TIMESTAMP_PROVIDER", lambda: datetime.now().astimezone()
                )(),
            )
            identity = get_admin_identity(_settings())
        stored_hash = get_admin_password_hash(_settings())
        if stored_hash is None or identity["full_name"] is None:
            raise AdminWriteError("Настройка администратора не завершена.")
        session = current_app.extensions["safe_cells_admin_access"].authenticate(
            payload.get("password"), stored_hash
        )
        _manager().set_admin()
    except (AdminValidationError, AdminPasswordError, EmployeeProfileError) as exc:
        return jsonify({"message": str(exc)}), 400
    except AdminAuthenticationError as exc:
        return jsonify({"message": str(exc)}), 401
    except AdminConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except AdminBusyError as exc:
        return jsonify({"message": str(exc)}), 423
    except (AdminNetworkError, AdminWriteUncertainError) as exc:
        return jsonify({"message": str(exc)}), 503
    except AdminWriteError as exc:
        return jsonify({"message": str(exc)}), 500
    return jsonify(
        {
            "kind": "admin",
            "full_name": identity["full_name"],
            "admin_token": session.token,
        }
    )
