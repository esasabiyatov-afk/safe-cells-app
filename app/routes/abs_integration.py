"""Local private endpoints for importing one selected customer from ABS."""

from __future__ import annotations

from hmac import compare_digest

from flask import Blueprint, current_app, jsonify, request

from app.services.abs_integration import (
    AbsAuthenticationError,
    AbsConnectionError,
    AbsResponseError,
    AbsSessionRequiredError,
    AbsValidationError,
    get_abs_session_minutes,
    refresh_linked_contracts,
)


abs_integration_blueprint = Blueprint(
    "abs_integration", __name__, url_prefix="/api/abs"
)


def _private_access_error():
    expected = current_app.extensions["safe_cells_private_token"]
    supplied = request.headers.get("X-Safe-Cells-Token", "")
    if not supplied or not compare_digest(supplied, expected):
        return jsonify({"message": "Доступ к данным не подтверждён."}), 403
    return None


def _manager():
    return current_app.extensions["safe_cells_abs_session"]


def _employee_name() -> str:
    return current_app.config["EMPLOYEE_PROVIDER"]()


def _json_object() -> dict:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise AbsValidationError("Переданы некорректные данные.")
    return payload


def _integration_error(error: Exception):
    if isinstance(error, AbsValidationError):
        return jsonify({"message": str(error)}), 400
    if isinstance(error, (AbsAuthenticationError, AbsSessionRequiredError)):
        return jsonify({"message": str(error), "login_required": True}), 401
    if isinstance(error, (AbsConnectionError, AbsResponseError)):
        return jsonify({"message": str(error)}), 503
    raise error


@abs_integration_blueprint.get("/status")
def status():
    denied = _private_access_error()
    if denied:
        return denied
    employee_name = _employee_name()
    return jsonify(
        {"authenticated": _manager().is_authenticated(employee_name)}
    )


@abs_integration_blueprint.post("/login")
def login():
    denied = _private_access_error()
    if denied:
        return denied
    try:
        payload = _json_object()
        manager = _manager()
        login_args = (
            str(payload.get("login", "")),
            str(payload.get("password", "")),
            _employee_name(),
        )
        lifetime_minutes = get_abs_session_minutes(
            current_app.extensions["safe_cells_settings"]
        )
        try:
            manager.login(*login_args, lifetime_minutes=lifetime_minutes)
        except TypeError:
            if not current_app.testing:
                raise
            manager.login(*login_args)
    except (
        AbsValidationError,
        AbsAuthenticationError,
        AbsConnectionError,
        AbsResponseError,
    ) as exc:
        return _integration_error(exc)
    try:
        sync_result = refresh_linked_contracts(
            current_app.extensions["safe_cells_settings"],
            manager=_manager(),
            employee_name=_employee_name(),
            occurred_at=current_app.config["NOW_PROVIDER"](),
        )
    except (AbsConnectionError, AbsResponseError, AbsSessionRequiredError) as exc:
        return _integration_error(exc)
    return jsonify({"authenticated": True, "sync": sync_result.to_dict()})


@abs_integration_blueprint.post("/search")
def search():
    denied = _private_access_error()
    if denied:
        return denied
    try:
        payload = _json_object()
        results = _manager().search(
            str(payload.get("query", "")), _employee_name()
        )
    except (
        AbsValidationError,
        AbsSessionRequiredError,
        AbsConnectionError,
        AbsResponseError,
    ) as exc:
        return _integration_error(exc)
    return jsonify({"results": [item.to_dict() for item in results]})


@abs_integration_blueprint.post("/refresh-linked")
def refresh_linked():
    denied = _private_access_error()
    if denied:
        return denied
    try:
        result = refresh_linked_contracts(
            current_app.extensions["safe_cells_settings"],
            manager=_manager(),
            employee_name=_employee_name(),
            occurred_at=current_app.config["NOW_PROVIDER"](),
        )
    except (
        AbsSessionRequiredError,
        AbsConnectionError,
        AbsResponseError,
    ) as exc:
        return _integration_error(exc)
    return jsonify(result.to_dict())


@abs_integration_blueprint.post("/customer")
def customer():
    denied = _private_access_error()
    if denied:
        return denied
    try:
        payload = _json_object()
        customer_data = _manager().customer(
            str(payload.get("customer_id", "")), _employee_name()
        )
    except (
        AbsValidationError,
        AbsSessionRequiredError,
        AbsConnectionError,
        AbsResponseError,
    ) as exc:
        return _integration_error(exc)
    return jsonify(customer_data.to_dict())
