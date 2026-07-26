"""Flask application factory for Safe Cells."""

from __future__ import annotations

from datetime import date, datetime
from secrets import token_urlsafe
from typing import TYPE_CHECKING

from flask import Flask, request

from app.config import Settings
from app.routes import (
    admin_blueprint,
    cells_blueprint,
    cell_blocks_blueprint,
    closures_blueprint,
    contracts_blueprint,
    editing_blueprint,
    documents_blueprint,
    employee_blueprint,
    journal_blueprint,
    main_blueprint,
    rental_blueprint,
    renewals_blueprint,
    reminders_blueprint,
    system_blueprint,
    statement_import_blueprint,
)
from app.services.admin_auth import AdminAccessManager
from app.services.document_downloads import DocumentDownloadStore
from app.services.employee import (
    EmployeeDirectoryReadError,
    EmployeeSelectionManager,
    EmployeeSelectionRequiredError,
    get_selected_employee,
)
from app.services.instances import attach_instance_coordinator

if TYPE_CHECKING:
    from app.runtime import BrowserLifecycle


def create_app(
    settings: Settings,
    *,
    runtime_lifecycle: "BrowserLifecycle | None" = None,
) -> Flask:
    """Create the Flask app without creating or mutating any database files."""

    app = Flask(__name__)
    app.config.update(
        DATABASE_DIRECTORY=str(settings.database_directory),
        WORKING_DATABASE_NAME=settings.working_database_name,
        ARCHIVE_DATABASE_NAME=settings.archive_database_name,
        BUSY_TIMEOUT_MS=settings.busy_timeout_ms,
        TESTING=settings.testing,
        TODAY_PROVIDER=date.today,
        NOW_PROVIDER=lambda: datetime.now().astimezone(),
    )
    app.extensions["safe_cells_settings"] = settings
    app.extensions["safe_cells_private_token"] = token_urlsafe(32)
    app.extensions["safe_cells_admin_access"] = AdminAccessManager()
    app.extensions["safe_cells_document_downloads"] = DocumentDownloadStore()
    if runtime_lifecycle is not None:
        app.extensions["safe_cells_runtime_lifecycle"] = runtime_lifecycle
    instance_coordinator = attach_instance_coordinator(app, settings)
    employee_selection = EmployeeSelectionManager()
    app.extensions["safe_cells_employee_selection"] = employee_selection
    app.config["EMPLOYEE_PROVIDER"] = lambda: get_selected_employee(
        settings, employee_selection
    ).full_name
    app.register_blueprint(admin_blueprint)
    app.register_blueprint(main_blueprint)
    app.register_blueprint(cells_blueprint)
    app.register_blueprint(cell_blocks_blueprint)
    app.register_blueprint(closures_blueprint)
    app.register_blueprint(contracts_blueprint)
    app.register_blueprint(editing_blueprint)
    app.register_blueprint(employee_blueprint)
    app.register_blueprint(journal_blueprint)
    app.register_blueprint(documents_blueprint)
    app.register_blueprint(rental_blueprint)
    app.register_blueprint(renewals_blueprint)
    app.register_blueprint(reminders_blueprint)
    app.register_blueprint(system_blueprint)
    app.register_blueprint(statement_import_blueprint)

    @app.before_request
    def refresh_instance_registration():
        # A process that started during a short restore retries registration
        # before handling later requests instead of remaining invisible.
        instance_coordinator.start()

    @app.after_request
    def add_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path in {"/", "/journal"} or request.path.startswith(("/api/", "/health")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(EmployeeSelectionRequiredError)
    def employee_selection_required(error):
        return {"message": str(error), "selection_required": True}, 409

    @app.errorhandler(EmployeeDirectoryReadError)
    def employee_directory_unavailable(error):
        return {"message": str(error)}, 503

    return app
