"""HTTP route blueprints."""

from app.routes.admin import admin_blueprint
from app.routes.abs_integration import abs_integration_blueprint
from app.routes.action_cancellations import action_cancellations_blueprint
from app.routes.cells import cells_blueprint
from app.routes.cell_blocks import cell_blocks_blueprint
from app.routes.closures import closures_blueprint
from app.routes.contracts import contracts_blueprint
from app.routes.editing import editing_blueprint
from app.routes.documents import documents_blueprint
from app.routes.employee import employee_blueprint
from app.routes.journal import journal_blueprint
from app.routes.main import main_blueprint
from app.routes.rental import rental_blueprint
from app.routes.renewals import renewals_blueprint
from app.routes.reminders import reminders_blueprint
from app.routes.system import system_blueprint
from app.routes.statement_import import statement_import_blueprint

__all__ = [
    "abs_integration_blueprint",
    "admin_blueprint",
    "action_cancellations_blueprint",
    "cells_blueprint",
    "cell_blocks_blueprint",
    "closures_blueprint",
    "contracts_blueprint",
    "editing_blueprint",
    "documents_blueprint",
    "employee_blueprint",
    "journal_blueprint",
    "main_blueprint",
    "rental_blueprint",
    "renewals_blueprint",
    "reminders_blueprint",
    "system_blueprint",
    "statement_import_blueprint",
]
