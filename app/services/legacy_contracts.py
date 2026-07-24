"""Metadata and guards for contracts imported from the legacy Excel register."""

from __future__ import annotations

import json
from typing import Any


LEGACY_MISSING_TEXT = "__LEGACY_DATA_NOT_AVAILABLE__"
LEGACY_MISSING_DATE = "1900-01-01"


def legacy_extra_fields(*, identity_complete: bool = False) -> str:
    """Build explicit unknown-value markers without pretending that zero is known."""

    return json.dumps(
        {
            "legacy_import": {
                "version": 1,
                "identity_complete": bool(identity_complete),
                "deposit_known": False,
                "rent_terms_known": False,
            }
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decoded(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def legacy_status(value: object) -> dict[str, bool]:
    decoded = _decoded(value)
    marker = decoded.get("legacy_import")
    if not isinstance(marker, dict) or marker.get("version") != 1:
        return {
            "legacy_imported": False,
            "legacy_identity_complete": True,
            "legacy_deposit_known": True,
            "legacy_rent_terms_known": True,
        }
    return {
        "legacy_imported": True,
        "legacy_identity_complete": marker.get("identity_complete") is True,
        "legacy_deposit_known": marker.get("deposit_known") is True,
        "legacy_rent_terms_known": marker.get("rent_terms_known") is True,
    }


def complete_legacy_details(
    value: object, *, identity_complete: bool, deposit_known: bool
) -> str:
    decoded = _decoded(value)
    marker = decoded.get("legacy_import")
    if not isinstance(marker, dict) or marker.get("version") != 1:
        return value if isinstance(value, str) else "{}"
    marker["identity_complete"] = bool(identity_complete)
    marker["deposit_known"] = bool(deposit_known)
    decoded["legacy_import"] = marker
    return json.dumps(
        decoded,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def require_legacy_identity(value: object, *, action: str) -> None:
    status = legacy_status(value)
    if status["legacy_imported"] and not status["legacy_identity_complete"]:
        raise ValueError(
            f"Перед {action} откройте «Редактировать данные» и заполните паспортные данные и номер счёта старого договора."
        )


def require_legacy_deposit(value: object, *, action: str) -> None:
    status = legacy_status(value)
    if status["legacy_imported"] and not status["legacy_deposit_known"]:
        raise ValueError(
            f"Перед {action} откройте «Редактировать данные» и укажите фактический залог старого договора."
        )
