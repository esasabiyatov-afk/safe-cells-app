"""Flask application factory for Safe Cells."""

from __future__ import annotations

from flask import Flask

from app.config import Settings
from app.routes import system_blueprint


def create_app(settings: Settings) -> Flask:
    """Create the Flask app without creating or mutating any database files."""

    app = Flask(__name__)
    app.config.update(
        DATABASE_DIRECTORY=str(settings.database_directory),
        WORKING_DATABASE_NAME=settings.working_database_name,
        ARCHIVE_DATABASE_NAME=settings.archive_database_name,
        BUSY_TIMEOUT_MS=settings.busy_timeout_ms,
        TESTING=settings.testing,
    )
    app.extensions["safe_cells_settings"] = settings
    app.register_blueprint(system_blueprint)
    return app
