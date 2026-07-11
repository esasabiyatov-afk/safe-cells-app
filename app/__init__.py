"""Flask application factory for Safe Cells."""

from __future__ import annotations

from datetime import date

from flask import Flask, request

from app.config import Settings
from app.routes import cells_blueprint, main_blueprint, system_blueprint
from app.services.employee import get_employee_username


def create_app(settings: Settings) -> Flask:
    """Create the Flask app without creating or mutating any database files."""

    app = Flask(__name__)
    app.config.update(
        DATABASE_DIRECTORY=str(settings.database_directory),
        WORKING_DATABASE_NAME=settings.working_database_name,
        ARCHIVE_DATABASE_NAME=settings.archive_database_name,
        BUSY_TIMEOUT_MS=settings.busy_timeout_ms,
        TESTING=settings.testing,
        TODAY_PROVIDER=date.today,
        EMPLOYEE_PROVIDER=get_employee_username,
    )
    app.extensions["safe_cells_settings"] = settings
    app.register_blueprint(main_blueprint)
    app.register_blueprint(cells_blueprint)
    app.register_blueprint(system_blueprint)

    @app.after_request
    def add_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path == "/" or request.path.startswith(("/api/", "/health")):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
