"""HTTP route blueprints."""

from app.routes.cells import cells_blueprint
from app.routes.contracts import contracts_blueprint
from app.routes.main import main_blueprint
from app.routes.rental import rental_blueprint
from app.routes.renewals import renewals_blueprint
from app.routes.system import system_blueprint

__all__ = [
    "cells_blueprint",
    "contracts_blueprint",
    "main_blueprint",
    "rental_blueprint",
    "renewals_blueprint",
    "system_blueprint",
]
