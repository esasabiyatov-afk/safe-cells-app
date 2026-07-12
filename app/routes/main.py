"""Main read-only screen."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template


main_blueprint = Blueprint("main", __name__)


@main_blueprint.get("/")
def index():
    employee_provider = current_app.config["EMPLOYEE_PROVIDER"]
    return render_template(
        "index.html",
        employee=employee_provider(),
        private_token=current_app.extensions["safe_cells_private_token"],
    )
