"""Explicit read-only disclosure of private active-contract details."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import sqlite3
from typing import Any

from app.config import Settings
from app.db.connections import (
    DatabaseUnavailableError,
    NETWORK_ERROR_MESSAGE,
    open_readonly,
    validate_database_pair,
)
from app.services.legacy_contracts import (
    LEGACY_MISSING_DATE,
    LEGACY_MISSING_TEXT,
    legacy_status,
)


class ContractDetailsValidationError(ValueError):
    """The requested cell number is malformed."""


class ActiveContractNotFoundError(RuntimeError):
    """The requested cell has no active contract."""


class ContractDetailsReadError(RuntimeError):
    """The shared database pair cannot be read safely."""


@dataclass(frozen=True, slots=True)
class RenewalDetails:
    renewal_date: str
    old_end_date: str
    new_start_date: str
    new_end_date: str
    renewal_days: int
    renewal_price: int
    penalty_days: int
    penalty_amount: int
    created_by: str


@dataclass(frozen=True, slots=True)
class PrivateContractDetails:
    cell_number: str
    client_full_name: str
    id_card_number: str
    id_card_issuer: str
    id_card_issue_date: str
    account_number: str
    created_at: str
    created_by: str
    deposit_amount: int | None
    legacy_imported: bool
    legacy_identity_complete: bool
    legacy_deposit_known: bool
    renewals: tuple[RenewalDetails, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["renewals"] = [asdict(item) for item in self.renewals]
        return payload


def get_contract_client_name(
    settings: Settings, *, cell_number: object, contract_ref: object
) -> str:
    """Read only the full client name for the explicitly opened occupied card."""

    normalized_number = _cell_number(cell_number)
    normalized_contract_ref = _contract_ref(contract_ref)
    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            row = connection.execute(
                """
                SELECT client_full_name
                FROM contracts
                WHERE cell_number = ? AND contract_id = ?
                """,
                (normalized_number, normalized_contract_ref),
            ).fetchone()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise ContractDetailsReadError(NETWORK_ERROR_MESSAGE) from exc
    if row is None:
        raise ActiveContractNotFoundError(
            "Ячейка свободна или договор уже закрыт. Обновите главный экран."
        )
    return str(row["client_full_name"])


def _cell_number(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractDetailsValidationError("Не указан номер ячейки.")
    normalized = value.strip()
    if len(normalized) > 50:
        raise ContractDetailsValidationError("Номер ячейки слишком длинный.")
    return normalized


def _contract_ref(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractDetailsValidationError("Карточка договора устарела. Обновите экран.")
    normalized = value.strip()
    if len(normalized) > 100:
        raise ContractDetailsValidationError("Карточка договора устарела. Обновите экран.")
    return normalized


def get_private_contract_details(
    settings: Settings, *, cell_number: object, contract_ref: object
) -> PrivateContractDetails:
    """Read PII only for an explicit request, then close both connections."""

    normalized_number = _cell_number(cell_number)
    normalized_contract_ref = _contract_ref(contract_ref)
    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            contract = connection.execute(
                """
                SELECT
                    contract_id, cell_number, client_full_name, id_card_number,
                    id_card_issuer, id_card_issue_date,
                    account_number, extra_fields_json, deposit_amount_minor,
                    created_at, created_by
                FROM contracts
                WHERE cell_number = ? AND contract_id = ?
                """,
                (normalized_number, normalized_contract_ref),
            ).fetchone()
        if contract is None:
            raise ActiveContractNotFoundError(
                "Ячейка свободна или договор уже закрыт. Обновите главный экран."
            )
        with open_readonly(
            paths.archive, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            renewal_rows = connection.execute(
                """
                SELECT
                    renewal_date, old_end_date, new_start_date, new_end_date,
                    renewal_days, renewal_price_minor, penalty_days,
                    penalty_amount_minor, created_by
                FROM renewals
                WHERE contract_id = ?
                ORDER BY created_at, renewal_id
                """,
                (contract["contract_id"],),
            ).fetchall()
    except ActiveContractNotFoundError:
        raise
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise ContractDetailsReadError(NETWORK_ERROR_MESSAGE) from exc

    renewals = tuple(
        RenewalDetails(
            renewal_date=str(row["renewal_date"]),
            old_end_date=str(row["old_end_date"]),
            new_start_date=str(row["new_start_date"]),
            new_end_date=str(row["new_end_date"]),
            renewal_days=int(row["renewal_days"]),
            renewal_price=int(row["renewal_price_minor"]),
            penalty_days=int(row["penalty_days"]),
            penalty_amount=int(row["penalty_amount_minor"]),
            created_by=str(row["created_by"]),
        )
        for row in renewal_rows
    )
    legacy = legacy_status(contract["extra_fields_json"])
    identity_complete = legacy["legacy_identity_complete"]
    deposit_known = legacy["legacy_deposit_known"]
    return PrivateContractDetails(
        cell_number=str(contract["cell_number"]),
        client_full_name=str(contract["client_full_name"]),
        id_card_number=(
            str(contract["id_card_number"])
            if contract["id_card_number"] != LEGACY_MISSING_TEXT
            else ""
        ),
        id_card_issuer=(
            str(contract["id_card_issuer"])
            if contract["id_card_issuer"] != LEGACY_MISSING_TEXT
            else ""
        ),
        id_card_issue_date=(
            str(contract["id_card_issue_date"])
            if contract["id_card_issue_date"] != LEGACY_MISSING_DATE
            else ""
        ),
        account_number=(
            str(contract["account_number"])
            if contract["account_number"] != LEGACY_MISSING_TEXT
            else ""
        ),
        created_at=str(contract["created_at"]),
        created_by=str(contract["created_by"]),
        deposit_amount=int(contract["deposit_amount_minor"]) if deposit_known else None,
        legacy_imported=legacy["legacy_imported"],
        legacy_identity_complete=identity_complete,
        legacy_deposit_known=deposit_known,
        renewals=renewals,
    )
