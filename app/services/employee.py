"""Windows employee name detection."""

from __future__ import annotations

import getpass


def get_employee_username() -> str:
    """Return the current Windows account name without logging it."""

    try:
        username = getpass.getuser().strip()
    except (ImportError, KeyError, OSError):
        username = ""
    return username or "Не определён"
