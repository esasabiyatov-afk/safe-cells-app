"""Administrative authentication and settings endpoints."""

from __future__ import annotations

from datetime import datetime
import sqlite3

from flask import Blueprint, current_app, jsonify, request, send_file

from app.services.admin_auth import (
    AdminAccessManager,
    AdminAuthenticationError,
    AdminPasswordError,
)
from app.services.admin_settings import (
    ACCESS_MODE_ACKNOWLEDGEMENT,
    ACCESS_MODE_PASSWORD,
    AdminBusyError,
    AdminConflictError,
    AdminNetworkError,
    AdminValidationError,
    AdminWriteError,
    AdminWriteUncertainError,
    change_admin_password,
    create_admin_password,
    get_admin_access_mode,
    get_admin_password_hash,
    get_admin_settings,
    is_admin_configured,
    update_admin_settings,
    update_admin_access_mode,
    update_admin_employee,
)
from app.services.admin_templates import (
    get_document_template_path,
    save_document_template,
    update_document_template,
)
from app.services.backups import (
    BackupError,
    BackupValidationError,
    RESTORE_CONFIRMATION,
    RestoreError,
    RestoreInstancesActiveError,
    RestoreValidationError,
    check_active_integrity,
    list_backup_sets,
    read_recovery_auth,
    restore_backup_set,
)
from app.services.employee import (
    EmployeeDirectoryReadError,
    EmployeeSelectionRequiredError,
    list_employees,
)


admin_blueprint = Blueprint("admin", __name__, url_prefix="/api/admin")


def _manager() -> AdminAccessManager:
    return current_app.extensions["safe_cells_admin_access"]


def _settings():
    return current_app.extensions["safe_cells_settings"]


def _employee() -> str:
    try:
        return current_app.config["EMPLOYEE_PROVIDER"]()
    except EmployeeSelectionRequiredError:
        try:
            if not list_employees(_settings()):
                return "Первичная настройка"
        except EmployeeDirectoryReadError as exc:
            raise AdminNetworkError(str(exc)) from exc
        raise


def _occurred_at() -> datetime:
    provider = current_app.config.get(
        "TIMESTAMP_PROVIDER", lambda: datetime.now().astimezone()
    )
    return provider()


def _token() -> str | None:
    return request.headers.get("X-Safe-Cells-Admin-Token")


def _require_admin():
    try:
        _manager().require(_token())
    except AdminAuthenticationError as exc:
        return jsonify({"message": str(exc)}), 401
    return None


def _write_error(exc: Exception):
    if isinstance(exc, (AdminValidationError, AdminPasswordError)):
        return jsonify({"message": str(exc)}), 400
    if isinstance(exc, AdminConflictError):
        return jsonify({"message": str(exc)}), 409
    if isinstance(exc, AdminBusyError):
        return jsonify({"message": str(exc)}), 423
    if isinstance(exc, (AdminNetworkError, AdminWriteUncertainError)):
        return jsonify({"message": str(exc)}), 503
    return jsonify({"message": str(exc)}), 500


def _session_payload(session) -> dict[str, str]:
    return {"token": session.token}


@admin_blueprint.get("/status")
def status():
    try:
        configured = is_admin_configured(_settings())
        access_mode = get_admin_access_mode(_settings())
    except (AdminNetworkError, AdminWriteError) as exc:
        try:
            recovery = read_recovery_auth(_settings())
        except BackupError:
            return jsonify({"message": str(exc)}), 503
        return jsonify({
            "configured": recovery["password_hash"] is not None,
            "access_mode": recovery["access_mode"],
            "recovery_mode": True,
        })
    return jsonify({
        "configured": configured,
        "access_mode": access_mode,
        "recovery_mode": False,
    })


@admin_blueprint.post("/setup")
def setup():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Переданы неверные данные пароля."}), 400
    if payload.get("password") != payload.get("password_confirmation"):
        return jsonify({"message": "Пароли не совпадают."}), 400
    try:
        result = create_admin_password(
            _settings(),
            operation_id=payload.get("operation_id"),
            password=payload.get("password"),
            employee=_employee(),
            occurred_at=_occurred_at(),
        )
        stored_hash = get_admin_password_hash(_settings())
        if stored_hash is None:
            raise AdminWriteError("Пароль не найден после сохранения.")
        session = _manager().authenticate(payload.get("password"), stored_hash)
    except (
        AdminValidationError,
        AdminPasswordError,
        AdminConflictError,
        AdminBusyError,
        AdminNetworkError,
        AdminWriteError,
        AdminWriteUncertainError,
    ) as exc:
        return _write_error(exc)
    response = result.to_dict()
    response.update(_session_payload(session))
    return jsonify(response), 200 if result.repeated else 201


@admin_blueprint.post("/login")
def login():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"password"}:
        return jsonify({"message": "Введите административный пароль."}), 400
    try:
        try:
            access_mode = get_admin_access_mode(_settings())
            stored_hash = get_admin_password_hash(_settings())
        except (AdminNetworkError, AdminWriteError):
            recovery = read_recovery_auth(_settings())
            access_mode = recovery["access_mode"]
            stored_hash = recovery["password_hash"]
        if access_mode != ACCESS_MODE_PASSWORD:
            raise AdminConflictError("Для настроек выбран вход без пароля.")
        if stored_hash is None:
            raise AdminConflictError("Административный пароль ещё не создан.")
        session = _manager().authenticate(payload["password"], stored_hash)
    except AdminAuthenticationError as exc:
        return jsonify({"message": str(exc)}), 401
    except AdminConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except (AdminNetworkError, BackupError) as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(_session_payload(session))


@admin_blueprint.post("/acknowledge")
def acknowledge():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"accepted"} or payload["accepted"] is not True:
        return jsonify({"message": "Подтвердите, что настройки меняет руководитель отдела."}), 400
    try:
        try:
            access_mode = get_admin_access_mode(_settings())
        except (AdminNetworkError, AdminWriteError):
            access_mode = read_recovery_auth(_settings())["access_mode"]
        if access_mode != ACCESS_MODE_ACKNOWLEDGEMENT:
            raise AdminConflictError("Для настроек выбран вход по общему паролю.")
    except AdminConflictError as exc:
        return jsonify({"message": str(exc)}), 409
    except (AdminNetworkError, AdminWriteError, BackupError) as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(_session_payload(_manager().issue_session()))


@admin_blueprint.post("/logout")
def logout():
    _manager().revoke(_token())
    return jsonify({"message": "Вы вышли из административных настроек."})


@admin_blueprint.get("/settings")
def settings_view():
    denied = _require_admin()
    if denied:
        return denied
    try:
        return jsonify(get_admin_settings(_settings()))
    except AdminNetworkError as exc:
        return jsonify({"message": str(exc)}), 503
    except AdminWriteError as exc:
        return jsonify({"message": str(exc)}), 500


@admin_blueprint.put("/settings")
def settings_update():
    denied = _require_admin()
    if denied:
        return denied
    try:
        result = update_admin_settings(
            _settings(),
            payload=request.get_json(silent=True),
            employee=_employee(),
            occurred_at=_occurred_at(),
        )
    except (
        AdminValidationError,
        AdminConflictError,
        AdminBusyError,
        AdminNetworkError,
        AdminWriteError,
        AdminWriteUncertainError,
    ) as exc:
        return _write_error(exc)
    return jsonify(result.to_dict())


@admin_blueprint.put("/access")
def access_update():
    denied = _require_admin()
    if denied:
        return denied
    try:
        result = update_admin_access_mode(
            _settings(),
            payload=request.get_json(silent=True),
            employee=_employee(),
            occurred_at=_occurred_at(),
        )
    except (
        AdminValidationError,
        AdminConflictError,
        AdminBusyError,
        AdminNetworkError,
        AdminWriteError,
        AdminWriteUncertainError,
    ) as exc:
        return _write_error(exc)
    return jsonify(result.to_dict())


@admin_blueprint.put("/employees")
def employee_update():
    denied = _require_admin()
    if denied:
        return denied
    payload = request.get_json(silent=True)
    try:
        existing_employees = list_employees(_settings())
        actor = (
            _employee()
            if existing_employees
            else payload.get("full_name") if isinstance(payload, dict) else None
        )
        result, employee = update_admin_employee(
            _settings(),
            payload=payload,
            employee=actor,
            occurred_at=_occurred_at(),
        )
    except (
        AdminValidationError,
        AdminConflictError,
        AdminBusyError,
        AdminNetworkError,
        AdminWriteError,
        AdminWriteUncertainError,
        EmployeeDirectoryReadError,
    ) as exc:
        if isinstance(exc, EmployeeDirectoryReadError):
            return jsonify({"message": str(exc)}), 503
        return _write_error(exc)
    manager = current_app.extensions["safe_cells_employee_selection"]
    if manager.get() == employee.employee_id and not employee.is_active:
        manager.clear()
    response = result.to_dict()
    response["employee"] = employee.to_dict()
    return jsonify(response), 200 if result.repeated or not payload.get("create") else 201


@admin_blueprint.put("/password")
def password_change():
    denied = _require_admin()
    if denied:
        return denied
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Переданы неверные данные пароля."}), 400
    if payload.get("new_password") != payload.get("password_confirmation"):
        return jsonify({"message": "Новые пароли не совпадают."}), 400
    try:
        result = change_admin_password(
            _settings(),
            operation_id=payload.get("operation_id"),
            current_password=payload.get("current_password"),
            new_password=payload.get("new_password"),
            employee=_employee(),
            occurred_at=_occurred_at(),
        )
        stored_hash = get_admin_password_hash(_settings())
        if stored_hash is None:
            raise AdminWriteError("Пароль не найден после сохранения.")
        _manager().revoke_all()
        session = _manager().authenticate(payload.get("new_password"), stored_hash)
    except (
        AdminValidationError,
        AdminPasswordError,
        AdminConflictError,
        AdminBusyError,
        AdminNetworkError,
        AdminWriteError,
        AdminWriteUncertainError,
    ) as exc:
        return _write_error(exc)
    response = result.to_dict()
    response.update(_session_payload(session))
    return jsonify(response)


@admin_blueprint.post("/templates")
def template_upload():
    denied = _require_admin()
    if denied:
        return denied
    upload = request.files.get("file")
    if upload is None or upload.stream is None:
        return jsonify({"message": "Выберите DOCX-файл шаблона."}), 400
    try:
        result, template_id = save_document_template(
            _settings(),
            operation_id=request.form.get("operation_id"),
            template_id=request.form.get("template_id"),
            document_type=request.form.get("document_type"),
            display_name=request.form.get("display_name"),
            file_name=upload.filename,
            stream=upload.stream,
            employee=_employee(),
            occurred_at=_occurred_at(),
        )
    except (
        AdminValidationError,
        AdminConflictError,
        AdminBusyError,
        AdminNetworkError,
        AdminWriteError,
        AdminWriteUncertainError,
    ) as exc:
        return _write_error(exc)
    response = result.to_dict()
    response["template_id"] = template_id
    return jsonify(response), 200 if result.repeated else 201


@admin_blueprint.put("/templates")
def template_update():
    denied = _require_admin()
    if denied:
        return denied
    try:
        result = update_document_template(
            _settings(),
            payload=request.get_json(silent=True),
            employee=_employee(),
            occurred_at=_occurred_at(),
        )
    except (
        AdminValidationError,
        AdminConflictError,
        AdminBusyError,
        AdminNetworkError,
        AdminWriteError,
        AdminWriteUncertainError,
    ) as exc:
        return _write_error(exc)
    return jsonify(result.to_dict())


@admin_blueprint.get("/templates/<template_id>/file")
def template_file(template_id: str):
    denied = _require_admin()
    if denied:
        return denied
    try:
        path = get_document_template_path(_settings(), template_id)
    except (AdminValidationError, AdminConflictError, AdminNetworkError, AdminWriteError) as exc:
        return _write_error(exc)
    return send_file(path, as_attachment=True, download_name=path.name)


@admin_blueprint.get("/backups")
def backups_view():
    denied = _require_admin()
    if denied:
        return denied
    try:
        integrity = check_active_integrity(_settings(), detected_at=_occurred_at())
        backup_sets = list_backup_sets(_settings())
        coordinator = current_app.extensions["safe_cells_instance_coordinator"]
        instances = coordinator.state()
    except Exception as exc:
        if isinstance(exc, (BackupError, OSError)):
            return jsonify({"message": str(exc)}), 503
        return jsonify({"message": str(exc)}), 500
    valid_count = sum(item.valid for item in backup_sets)
    return jsonify({
        "integrity": integrity.to_dict(),
        "sets": [item.to_dict() for item in backup_sets],
        "instances": instances.to_dict(),
        "valid_count": valid_count,
        "restore_confirmation": RESTORE_CONFIRMATION,
        "restore_allowed": (
            integrity.write_blocked
            and valid_count > 0
            and instances.registered
            and instances.other_active == 0
        ),
    })


@admin_blueprint.post("/backups/check")
def backups_check():
    denied = _require_admin()
    if denied:
        return denied
    try:
        integrity = check_active_integrity(_settings(), detected_at=_occurred_at())
    except Exception as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify({"integrity": integrity.to_dict()})


@admin_blueprint.post("/backups/restore")
def backups_restore():
    denied = _require_admin()
    if denied:
        return denied
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {
        "operation_id", "set_id", "confirmation"
    }:
        return jsonify({"message": "Переданы неверные данные восстановления."}), 400
    coordinator = current_app.extensions["safe_cells_instance_coordinator"]
    try:
        result = restore_backup_set(
            _settings(),
            set_id=payload["set_id"],
            operation_id=payload["operation_id"],
            confirmation=payload["confirmation"],
            occurred_at=_occurred_at(),
            ensure_no_other_instances=coordinator.other_active_count,
        )
    except RestoreValidationError as exc:
        return jsonify({"message": str(exc)}), 400
    except RestoreInstancesActiveError as exc:
        return jsonify({"message": str(exc)}), 409
    except (RestoreError, BackupValidationError, BackupError, OSError, sqlite3.Error) as exc:
        return jsonify({"message": str(exc)}), 503
    return jsonify(result.to_dict())
