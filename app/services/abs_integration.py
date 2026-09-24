"""Read customer data from the browser-based ABS through its existing HTML forms."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import html
import json
import re
import sqlite3
from threading import RLock
from time import monotonic
from typing import Callable, Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import requests
import urllib3
from bs4 import BeautifulSoup

from app.config import Settings
from app.db.connections import (
    DatabaseUnavailableError,
    open_readonly,
    open_write,
    validate_database_pair,
)
from app.services.backups import create_backup_pair


ABS_LOGIN_URL = "https://ob.tolubay.kg/OnlineBank.Management.MVC/Account/SignIn"
ABS_SEARCH_URL = "https://ob.tolubay.kg/OnlineBank.Management.MVC/Customers/SearchResult"
ABS_CUSTOMER_URL = (
    "https://ob.tolubay.kg/OnlineBank.Management.MVC/Customers/Edit"
    "?customerID={customer_id}"
)
ABS_CUSTOMER_DETAILS_URL = (
    "https://ob.tolubay.kg/OnlineBank.Management.MVC/Customers/Details"
    "?customerID={customer_id}"
)
REQUEST_TIMEOUT_SECONDS = 30
MAX_SEARCH_RESULTS = 50

CURRENCY_MAP = {
    417: "KGS",
    840: "USD",
    978: "EUR",
    643: "RUB",
    398: "KZT",
    156: "CNY",
}
STATUS_MAP = {
    1: "Активный",
    2: "Закрыт",
    3: "Заблокирован",
    4: "Дормант",
    5: "Открыт удалённо",
}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class AbsIntegrationError(RuntimeError):
    """Base error that is safe to show in the local application."""


class AbsValidationError(AbsIntegrationError):
    pass


class AbsAuthenticationError(AbsIntegrationError):
    pass


class AbsSessionRequiredError(AbsIntegrationError):
    pass


class AbsConnectionError(AbsIntegrationError):
    pass


class AbsResponseError(AbsIntegrationError):
    pass


@dataclass(frozen=True)
class AbsCustomerSearchResult:
    customer_id: str
    summary: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AbsAccount:
    account_no: str
    product: str
    currency: str
    balance: str
    status: str


@dataclass(frozen=True)
class AbsCustomerData:
    abs_customer_id: str
    client_full_name: str
    client_phone: str
    account_number: str
    id_card_number: str
    id_card_issuer: str
    id_card_issue_date: str
    client_whatsapp_phone: str = ""
    accounts: tuple[AbsAccount, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AbsSyncResult:
    updated_count: int
    skipped_count: int
    linked_count: int
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_abs_session_minutes(settings: Settings) -> int:
    """Read the shared session timeout without retaining a database connection."""

    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            row = connection.execute(
                "SELECT value FROM config WHERE key='abs_session_minutes'"
            ).fetchone()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AbsConnectionError(
            "Не удалось прочитать длительность сеанса АБС из общей базы."
        ) from exc
    try:
        minutes = int(row["value"] if row is not None else 60)
    except (TypeError, ValueError) as exc:
        raise AbsResponseError(
            "Настройка длительности сеанса АБС повреждена."
        ) from exc
    if not 1 <= minutes <= 1_440:
        raise AbsResponseError(
            "Настройка длительности сеанса АБС должна быть от 1 до 1440 минут."
        )
    return minutes


def refresh_linked_contracts(
    settings: Settings,
    *,
    manager: "AbsSessionManager",
    employee_name: str,
    occurred_at: datetime,
) -> AbsSyncResult:
    """Refresh linked active clients; incomplete ABS replies never change data."""

    try:
        paths = validate_database_pair(settings)
        with open_readonly(
            paths.working, busy_timeout_ms=settings.busy_timeout_ms
        ) as connection:
            linked = connection.execute(
                "SELECT contract_id, cell_number, abs_customer_id FROM contracts "
                "WHERE abs_customer_id IS NOT NULL ORDER BY cell_number"
            ).fetchall()
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AbsConnectionError(
            "Не удалось прочитать договоры для обновления из АБС."
        ) from exc

    profiles: dict[str, AbsCustomerData] = {}
    skipped = 0
    for row in linked:
        try:
            profile = manager.customer(str(row["abs_customer_id"]), employee_name)
        except (AbsConnectionError, AbsResponseError, AbsValidationError):
            skipped += 1
            continue
        complete = (
            profile.client_full_name
            and (profile.client_phone or profile.client_whatsapp_phone)
            and profile.id_card_number
            and profile.id_card_issuer
            and profile.id_card_issue_date
        )
        if not complete or profile.abs_customer_id != str(row["abs_customer_id"]):
            skipped += 1
            continue
        profiles[str(row["contract_id"])] = profile
    if not profiles:
        return AbsSyncResult(0, skipped, len(linked))

    operation_id = str(uuid4())
    timestamp = occurred_at.isoformat(timespec="seconds")
    updated_count = 0
    try:
        with open_write(settings, attach_archive=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for contract_id, profile in profiles.items():
                current = connection.execute(
                    "SELECT * FROM main.contracts WHERE contract_id=? "
                    "AND abs_customer_id=?",
                    (contract_id, profile.abs_customer_id),
                ).fetchone()
                if current is None:
                    skipped += 1
                    continue
                values = {
                    "client_full_name": profile.client_full_name,
                    "client_phone": profile.client_phone,
                    "client_whatsapp_phone": profile.client_whatsapp_phone,
                    "id_card_number": profile.id_card_number,
                    "id_card_issuer": profile.id_card_issuer,
                    "id_card_issue_date": profile.id_card_issue_date,
                }
                changed_fields = [
                    key for key, value in values.items() if current[key] != value
                ]
                if not changed_fields:
                    continue
                connection.execute(
                    "UPDATE main.contracts SET client_full_name=?, client_phone=?, "
                    "client_whatsapp_phone=?, id_card_number=?, id_card_issuer=?, "
                    "id_card_issue_date=?, updated_at=?, updated_by=? "
                    "WHERE contract_id=? AND abs_customer_id=?",
                    (*values.values(), timestamp, employee_name,
                     contract_id, profile.abs_customer_id),
                )
                connection.execute(
                    "INSERT INTO archive.log(log_id, operation_id, occurred_at, "
                    "employee, action, contract_id, cell_number, changes_json) "
                    "VALUES(?, ?, ?, ?, 'contract.abs_refreshed', ?, ?, ?)",
                    (
                        str(uuid4()), str(uuid4()), timestamp, employee_name,
                        contract_id, str(current["cell_number"]),
                        json.dumps({"fields": changed_fields}, sort_keys=True),
                    ),
                )
                updated_count += 1
            connection.commit()
            warning = None
            if updated_count:
                try:
                    create_backup_pair(
                        connection, settings, operation_id=operation_id,
                        occurred_at=occurred_at,
                    )
                except Exception:
                    warning = (
                        "Данные из АБС обновлены, но резервную копию создать не удалось."
                    )
            return AbsSyncResult(updated_count, skipped, len(linked), warning)
    except (DatabaseUnavailableError, OSError, sqlite3.Error) as exc:
        raise AbsConnectionError(
            "Не удалось безопасно сохранить обновлённые данные из АБС."
        ) from exc


def _normalized_text(value: object, *, maximum: int = 300) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def _field_value(soup: BeautifulSoup, names: str | tuple[str, ...]) -> str:
    candidates = (names,) if isinstance(names, str) else names
    tags = soup.find_all(["input", "select"])
    for candidate in candidates:
        candidate_lower = candidate.lower()
        for tag in tags:
            tag_id = str(tag.get("id", "")).lower()
            tag_name = str(tag.get("name", "")).lower()
            if candidate_lower not in tag_id and candidate_lower not in tag_name:
                continue
            if tag.name == "select":
                selected = tag.find("option", selected=True)
                if selected is not None and selected.get("value", "") != "":
                    return _normalized_text(selected.get_text(" ", strip=True))
                continue
            if str(tag.get("type", "")).lower() in {"radio", "checkbox"}:
                continue
            value = _normalized_text(tag.get("value", ""))
            if value:
                return value
    return ""


def _customer_id_from_link(href: str) -> str:
    query = parse_qs(urlparse(href).query)
    values = query.get("customerID") or query.get("customerId") or []
    if not values:
        match = re.search(r"customerID=([^&]+)", href, flags=re.IGNORECASE)
        values = [match.group(1)] if match else []
    value = _normalized_text(values[0] if values else "", maximum=50)
    return value if re.fullmatch(r"[A-Za-z0-9_-]+", value) else ""


def _search_fields(query: str) -> dict[str, str]:
    value = _normalized_text(query, maximum=200)
    if not value:
        raise AbsValidationError("Введите ID клиента или ФИО.")
    if value.isdigit():
        return {
            "SearchCustomerID": value,
            "SearchSurname": "",
            "SearchCustomerName": "",
            "SearchOtchestvo": "",
        }

    parts = value.split()
    surname = parts[0]
    name = parts[1] if len(parts) > 1 else ""
    patronymic = " ".join(parts[2:]) if len(parts) > 2 else ""
    if len(parts) >= 3 and parts[1].casefold() in {"уулу", "кызы"}:
        surname = " ".join(parts[:2])
        name = parts[2]
        patronymic = " ".join(parts[3:])
    return {
        "SearchCustomerID": "",
        "SearchSurname": surname,
        "SearchCustomerName": name,
        "SearchOtchestvo": patronymic,
    }


def _date_to_iso(value: str) -> str:
    cleaned = _normalized_text(value, maximum=40).split(" ")[0]
    if not cleaned:
        return ""
    for date_format in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, date_format).date().isoformat()
        except ValueError:
            continue
    return ""


def _accounts_from_html(page: str) -> tuple[AbsAccount, ...]:
    raw_html = html.unescape(page)
    products: dict[str, str] = {}
    patterns = (
        (
            r'\{[^{}]*?["\']?(?:ProductID|ProgramID|Value)["\']?\s*:\s*(\d+)'
            r'[^{}]*?["\']?(?:Name|Text)["\']?\s*:\s*["\']([^"\']+)["\']',
            False,
        ),
        (
            r'\{[^{}]*?["\']?(?:Name|Text)["\']?\s*:\s*["\']([^"\']+)["\']'
            r'[^{}]*?["\']?(?:ProductID|ProgramID|Value)["\']?\s*:\s*(\d+)',
            True,
        ),
    )
    for pattern, reversed_groups in patterns:
        for match in re.finditer(pattern, raw_html):
            first, second = match.group(1), match.group(2)
            product_id, name = (
                (second, first) if reversed_groups else (first, second)
            )
            products[product_id] = _normalized_text(name)

    match = re.search(
        r'"Deposits"\s*:\s*(\[\s*\{.*?\}\s*\])',
        raw_html,
        flags=re.DOTALL,
    )
    if match is None:
        return ()
    try:
        deposits = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(deposits, list):
        return ()

    accounts: list[AbsAccount] = []
    for item in deposits:
        if not isinstance(item, dict):
            continue
        account_no = _normalized_text(
            item.get("MainAccountNo") or item.get("AccountNo"), maximum=100
        )
        if not account_no:
            continue
        product_id = str(
            item.get("ProgramID") or item.get("ProductID") or ""
        )
        product_name = products.get(product_id, "")
        if not product_name:
            raw_name = _normalized_text(item.get("AccountName"))
            parts = [part.strip() for part in raw_name.split(",")]
            known_currencies = {"KGS", "USD", "RUB", "EUR", "KZT", "CNY"}
            if len(parts) >= 2:
                product_name = ", ".join(
                    part
                    for part in parts[1:]
                    if part and part.upper() not in known_currencies
                )
        if not product_name:
            product_name = (
                f"Продукт #{product_id}" if product_id else "Без названия"
            )
        currency_value = item.get("CurrencyID")
        currency = CURRENCY_MAP.get(
            currency_value, str(currency_value or "—")
        )
        status_value = (
            item.get("DepositAccountStatusID") or item.get("Status") or 1
        )
        status = STATUS_MAP.get(status_value, str(status_value))
        balance = item.get("MainBalance")
        if balance is None:
            balance = item.get("AvailableSumV", 0.0)
        balance_text = (
            f"{balance:.2f}"
            if isinstance(balance, (int, float)) and not isinstance(balance, bool)
            else _normalized_text(balance, maximum=50)
        )
        accounts.append(
            AbsAccount(
                account_no=account_no,
                product=product_name,
                currency=currency,
                balance=balance_text,
                status=status,
            )
        )
    return tuple(accounts)


class AbsSessionManager:
    """Keeps ABS credentials out of the database and only retains a live session."""

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._lock = RLock()
        self._session: requests.Session | None = None
        self._employee_name: str | None = None
        self._expires_at: float | None = None
        self._clock = clock

    def clear(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.close()
            self._session = None
            self._employee_name = None
            self._expires_at = None

    def is_authenticated(self, employee_name: str) -> bool:
        with self._lock:
            if self._session is not None and self._session_expired():
                self.clear()
                return False
            return (
                self._session is not None
                and self._employee_name == employee_name
            )

    def login(
        self,
        login: str,
        password: str,
        employee_name: str,
        *,
        lifetime_minutes: int = 60,
    ) -> None:
        username = _normalized_text(login, maximum=200)
        if not username or not password:
            raise AbsValidationError("Введите логин и пароль АБС.")
        if isinstance(lifetime_minutes, bool) or not isinstance(lifetime_minutes, int):
            raise AbsValidationError("Некорректная длительность сеанса АБС.")
        if not 1 <= lifetime_minutes <= 1_440:
            raise AbsValidationError("Сеанс АБС должен быть от 1 до 1440 минут.")

        session = requests.Session()
        # These settings intentionally match the already working bank script.
        session.verify = False
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                ),
                "Origin": "https://ob.tolubay.kg",
                "Referer": ABS_LOGIN_URL,
            }
        )
        try:
            login_page = session.get(
                ABS_LOGIN_URL, timeout=REQUEST_TIMEOUT_SECONDS
            )
            soup = BeautifulSoup(login_page.text, "html.parser")
            token_input = soup.find(
                "input", {"name": "__RequestVerificationToken"}
            )
            payload = {"UserName": username, "Password": password}
            if token_input is not None:
                token = str(token_input.get("value", ""))
                if token:
                    payload["__RequestVerificationToken"] = token
            response = session.post(
                ABS_LOGIN_URL,
                data=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            session.close()
            raise AbsConnectionError(
                "Не удалось подключиться к АБС. Проверьте сеть и повторите вход."
            ) from exc
        if response.status_code != 200:
            session.close()
            raise AbsAuthenticationError(
                f"АБС отклонила вход (код {response.status_code})."
            )

        with self._lock:
            if self._session is not None:
                self._session.close()
            self._session = session
            self._employee_name = employee_name
            self._expires_at = self._clock() + lifetime_minutes * 60

    def search(
        self, query: str, employee_name: str
    ) -> list[AbsCustomerSearchResult]:
        search_fields = _search_fields(query)
        with self._lock:
            session = self._require_session(employee_name)
            payload = {
                "ShowLinks": "True",
                **search_fields,
                "SearchAgreementNo": "",
                "SearchAccountNo": "",
                "SearchCompanyName": "",
                "SearchIdentificationNo": "",
                "SearchGroupName": "",
                "SearchStreetName": "",
                "SearchHouseNo": "",
                "SearchFlatNo": "",
                "SearchPhoneNumber": "",
            }
            headers = {
                "Accept": "text/html, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": (
                    "application/x-www-form-urlencoded; charset=UTF-8"
                ),
            }
            try:
                response = session.post(
                    ABS_SEARCH_URL,
                    data=payload,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise AbsConnectionError(
                    "Не удалось выполнить поиск в АБС. Проверьте сеть."
                ) from exc
        if response.status_code != 200:
            raise AbsResponseError(
                f"АБС не выполнила поиск (код {response.status_code})."
            )

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[AbsCustomerSearchResult] = []
        seen: set[str] = set()
        for row in soup.select("table tbody tr"):
            link = row.find("a", href=True)
            customer_id = _customer_id_from_link(
                str(link.get("href", "")) if link else ""
            )
            if not customer_id or customer_id in seen:
                continue
            columns = [
                _normalized_text(cell.get_text(" ", strip=True))
                for cell in row.find_all("td")
            ]
            visible_columns = columns[1:] if len(columns) > 1 else columns
            summary = " | ".join(item for item in visible_columns if item)
            results.append(
                AbsCustomerSearchResult(
                    customer_id=customer_id,
                    summary=summary or f"Клиент ID {customer_id}",
                )
            )
            seen.add(customer_id)
            if len(results) >= MAX_SEARCH_RESULTS:
                break
        return results

    def customer(
        self, customer_id: str, employee_name: str
    ) -> AbsCustomerData:
        normalized_id = _normalized_text(customer_id, maximum=50)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized_id):
            raise AbsValidationError("Некорректный ID клиента АБС.")
        with self._lock:
            session = self._require_session(employee_name)
            try:
                response = session.get(
                    ABS_CUSTOMER_URL.format(customer_id=normalized_id),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                accounts_response = session.get(
                    ABS_CUSTOMER_DETAILS_URL.format(
                        customer_id=normalized_id
                    ),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise AbsConnectionError(
                    "Не удалось получить анкету клиента из АБС."
                ) from exc
        if response.status_code != 200:
            raise AbsResponseError(
                f"АБС не вернула анкету клиента (код {response.status_code})."
            )
        if accounts_response.status_code != 200:
            raise AbsResponseError(
                "АБС не вернула счета клиента "
                f"(код {accounts_response.status_code})."
            )

        soup = BeautifulSoup(response.text, "html.parser")
        surname = _field_value(
            soup, ("GeneralInfoModel.Surname", "Surname")
        )
        name = _field_value(
            soup, ("GeneralInfoModel.CustomerName", "CustomerName")
        )
        patronymic = _field_value(
            soup, ("GeneralInfoModel.Otchestvo", "Otchestvo")
        )
        document_series = _field_value(
            soup, ("GeneralInfoModel.DocumentSeries", "DocumentSeries")
        )
        document_number = _field_value(
            soup, ("GeneralInfoModel.DocumentNo", "DocumentNo")
        )
        phone = _field_value(
            soup,
            (
                "AdditionalInfoModel.ContactPhone1",
                "customizedPhoneNumber",
            ),
        )
        whatsapp_phone = _field_value(
            soup,
            (
                "AdditionalInfoModel.WhatsAppPhone",
                "AdditionalInfoModel_WhatsAppPhone",
            ),
        )
        account_number = _field_value(
            soup,
            (
                "AdditionalInfoModel.AccountNumber",
                "GeneralInfoModel.AccountNumber",
                "AccountNumber",
                "AccountNo",
            ),
        )
        full_name = " ".join(
            item for item in (surname, name, patronymic) if item
        )
        id_card_number = re.sub(
            r"\s+", "", f"{document_series}{document_number}"
        )
        return AbsCustomerData(
            abs_customer_id=_field_value(
                soup, ("GeneralInfoModel.CustomerId", "CustomerId")
            )
            or normalized_id,
            client_full_name=full_name,
            client_phone=phone,
            client_whatsapp_phone=whatsapp_phone,
            account_number=account_number,
            id_card_number=id_card_number,
            id_card_issuer=_field_value(
                soup, ("GeneralInfoModel.IssueAuthority", "IssueAuthority")
            ),
            id_card_issue_date=_date_to_iso(
                _field_value(
                    soup, ("GeneralInfoModel.IssueDate", "IssueDate")
                )
            ),
            accounts=_accounts_from_html(accounts_response.text),
        )

    def _require_session(self, employee_name: str) -> requests.Session:
        if self._session is not None and self._session_expired():
            self.clear()
            raise AbsSessionRequiredError(
                "Сеанс АБС истёк. Введите логин и пароль заново."
            )
        if self._session is None or self._employee_name != employee_name:
            raise AbsSessionRequiredError(
                "Сначала войдите в АБС для текущего сотрудника."
            )
        return self._session

    def _session_expired(self) -> bool:
        return self._expires_at is None or self._clock() >= self._expires_at
