"""HTTP route blueprints."""

from app.routes.admin import admin_blueprint
from app.routes.cells import cells_blueprint
from app.routes.closures import closures_blueprint
from app.routes.contracts import contracts_blueprint
from app.routes.editing import editing_blueprint
from app.routes.documents import documents_blueprint
from app.routes.employee import employee_blueprint
from app.routes.journal import journal_blueprint
from app.routes.main import main_blueprint
from app.routes.rental import rental_blueprint
from app.routes.renewals import renewals_blueprint
from app.routes.system import system_blueprint

__all__ = [
    "admin_blueprint",
    "cells_blueprint",
    "closures_blueprint",
    "contracts_blueprint",
    "editing_blueprint",
    "documents_blueprint",
    "employee_blueprint",
    "journal_blueprint",
    "main_blueprint",
    "rental_blueprint",
    "renewals_blueprint",
    "system_blueprint",
]
