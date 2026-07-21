"""Main read-only screen."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template


main_blueprint = Blueprint("main", __name__)


@main_blueprint.get("/")
def index():
    return render_template(
        "index.html",
        private_token=current_app.extensions["safe_cells_private_token"],
        runtime_enabled="safe_cells_runtime_lifecycle" in current_app.extensions,
    )
