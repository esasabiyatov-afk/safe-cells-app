"""Main read-only screen."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template
from app.services.employee import EmployeeProfileError, get_employee_full_name


main_blueprint = Blueprint("main", __name__)


@main_blueprint.get("/")
def index():
    employee_provider = current_app.config["EMPLOYEE_PROVIDER"]
    username = employee_provider()
    try:
        full_name = get_employee_full_name(
            current_app.config["EMPLOYEE_PROFILE_PATH"], username
        )
    except EmployeeProfileError:
        full_name = None
    return render_template(
        "index.html",
        employee=full_name or username,
        employee_username=username,
        employee_profile_required=full_name is None,
        private_token=current_app.extensions["safe_cells_private_token"],
    )
