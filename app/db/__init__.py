"""SQLite access layer for the working and archive databases."""

from app.db.connections import (
    DatabasePaths,
    DatabaseUnavailableError,
    open_readonly,
    open_write,
    validate_database_pair,
)
from app.db.schema import InitializationResult, initialize_databases

__all__ = [
    "DatabasePaths",
    "DatabaseUnavailableError",
    "InitializationResult",
    "initialize_databases",
    "open_readonly",
    "open_write",
    "validate_database_pair",
]
