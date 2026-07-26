from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app import create_app
from app.db.connections import DatabasePaths, open_readonly, open_write
from app.services.phone_numbers import (
    PhoneNumberValidationError,
    normalize_whatsapp_phone,
)
from app.services.cells import list_cells
from app.services.renewals import renew_contract
from app.services.reminders import (
    ReminderConflictError,
    ReminderValidationError,
    build_reminder_message,
    reminder_status_text,
    send_reminder,
)


TZ = timezone(timedelta(hours=6))
WHEN = datetime(2026, 7, 26, 14, 7, tzinfo=TZ)


def reminder_payload(**overrides) -> dict:
    payload = {
        "operation_id": str(uuid4()),
        "cell_number": "1",
        "contract_ref": "contract-test-1",
    }
    payload.update(overrides)
    return payload


def test_phone_is_normalized_for_whatsapp_and_invalid_values_are_rejected():
    assert normalize_whatsapp_phone("+996 (555) 123-456") == "996555123456"
    for value in ("", "0555 123 456", "+996 TEST 555123456", "+123"):
        with pytest.raises(PhoneNumberValidationError):
            normalize_whatsapp_phone(value)


def test_approved_messages_are_selected_by_current_status():
    expiring = build_reminder_message(
        status="expiring",
        client_full_name="Иванов Иван Иванович",
        cell_number="12",
        end_date=date(2026, 7, 31),
    )
    overdue = build_reminder_message(
        status="overdue",
        client_full_name="Иванов Иван Иванович",
        cell_number="12",
        end_date=date(2026, 7, 20),
    )

    assert expiring == (
        "Здравствуйте, Иван Иванович!\n\n"
        "Напоминаем, что срок аренды вашей банковской сейфовой ячейки "
        "№12 истекает 31.07.2026.\n\n"
        "Для продления аренды или освобождения ячейки просим обратиться "
        "в отделение банка.\n\n"
        "С уважением, ЗАО АКБ «Толубай»."
    )
    assert overdue == (
        "Здравствуйте, Иван Иванович!\n\n"
        "Срок аренды вашей банковской сейфовой ячейки №12 истёк 20.07.2026.\n\n"
        "Просим обратиться в отделение банка для продления аренды или "
        "освобождения ячейки. За период просрочки начисляется штраф "
        "согласно условиям договора.\n\n"
        "С уважением, ЗАО АКБ «Толубай»."
    )


def test_reminder_status_uses_today_yesterday_and_days_ago():
    assert reminder_status_text(None, as_of=WHEN) == "Не оповещён"
    assert reminder_status_text(
        "2026-07-26T09:05:00+06:00", as_of=WHEN
    ) == "Оповещён сегодня в 09:05"
    assert reminder_status_text(
        "2026-07-25T18:30:00+06:00", as_of=WHEN
    ) == "Оповещён вчера в 18:30"
    assert reminder_status_text(
        "2026-07-22T18:30:00+06:00", as_of=WHEN
    ) == "Оповещён 4 дней назад"


def test_reminder_saves_exact_contract_state_and_builds_encoded_whatsapp_link(
    settings, insert_test_contract
):
    insert_test_contract(
        cell_number="1",
        start_date="2026-07-01",
        end_date="2026-07-28",
        client_name="Иванов Иван Иванович",
        client_phone="+996 (555) 123-456",
    )
    request = reminder_payload()

    result = send_reminder(
        settings,
        payload=request,
        employee="Тестовый Сотрудник",
        occurred_at=WHEN,
        as_of_date=WHEN.date(),
    )

    assert result.status == "expiring"
    assert result.last_reminded_at == "2026-07-26T14:07:00+06:00"
    assert result.reminder_count == 1
    assert result.reminder_status == "Оповещён сегодня в 14:07"
    assert result.repeated is False
    parsed = urlsplit(result.whatsapp_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "wa.me"
    assert parsed.path == "/996555123456"
    message = parse_qs(parsed.query)["text"][0]
    assert "Здравствуйте, Иван Иванович!" in message
    assert "истекает 28.07.2026" in message

    paths = DatabasePaths.from_settings(settings)
    with open_readonly(paths.working) as connection:
        stored = connection.execute(
            """
            SELECT last_reminded_at, reminder_count
            FROM contracts WHERE contract_id='contract-test-1'
            """
        ).fetchone()
    with open_readonly(paths.archive) as connection:
        audit = connection.execute(
            "SELECT * FROM log WHERE action='contract.reminded'"
        ).fetchone()
    assert tuple(stored) == ("2026-07-26T14:07:00+06:00", 1)
    changes = json.loads(audit["changes_json"])
    assert changes["reminder_count"] == 1
    assert "client" not in audit["changes_json"]
    assert "phone" not in audit["changes_json"]


def test_repeat_operation_is_idempotent_and_new_click_increments_counter(
    settings, insert_test_contract
):
    insert_test_contract(
        cell_number="1",
        start_date="2026-07-01",
        end_date="2026-07-20",
    )
    request = reminder_payload()
    first = send_reminder(
        settings, payload=request, employee="Сотрудник", occurred_at=WHEN
    )
    repeated = send_reminder(
        settings, payload=request, employee="Сотрудник", occurred_at=WHEN
    )
    second = send_reminder(
        settings,
        payload=reminder_payload(),
        employee="Сотрудник",
        occurred_at=WHEN + timedelta(minutes=15),
    )

    assert first.reminder_count == 1
    assert repeated.repeated is True and repeated.reminder_count == 1
    assert second.reminder_count == 2
    assert second.reminder_status == "Оповещён сегодня в 14:22"
    paths = DatabasePaths.from_settings(settings)
    with open_readonly(paths.archive) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM log WHERE action='contract.reminded'"
        ).fetchone()[0] == 2


def test_invalid_or_missing_phone_does_not_change_notification_state(
    settings, insert_test_contract
):
    insert_test_contract(
        cell_number="1",
        start_date="2026-07-01",
        end_date="2026-07-28",
    )
    with open_write(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE contracts SET client_phone=NULL WHERE contract_id='contract-test-1'"
        )
        connection.commit()

    with pytest.raises(ReminderValidationError, match="не указан номер"):
        send_reminder(
            settings,
            payload=reminder_payload(),
            employee="Сотрудник",
            occurred_at=WHEN,
        )

    paths = DatabasePaths.from_settings(settings)
    with open_readonly(paths.working) as connection:
        stored = connection.execute(
            "SELECT last_reminded_at, reminder_count FROM contracts"
        ).fetchone()
    with open_readonly(paths.archive) as connection:
        logs = connection.execute(
            "SELECT COUNT(*) FROM log WHERE action='contract.reminded'"
        ).fetchone()[0]
    assert tuple(stored) == (None, 0)
    assert logs == 0


def test_normal_contract_cannot_be_reminded_and_state_stays_unchanged(
    settings, insert_test_contract
):
    insert_test_contract(
        cell_number="1",
        start_date="2026-07-01",
        end_date="2026-08-20",
    )

    with pytest.raises(ReminderConflictError, match="только для истекающей"):
        send_reminder(
            settings,
            payload=reminder_payload(),
            employee="Сотрудник",
            occurred_at=WHEN,
        )

    paths = DatabasePaths.from_settings(settings)
    with open_readonly(paths.working) as connection:
        assert connection.execute(
            "SELECT reminder_count FROM contracts"
        ).fetchone()[0] == 0


def test_reminder_api_uses_server_time_and_returns_current_status(
    settings, insert_test_contract
):
    insert_test_contract(
        cell_number="1",
        start_date="2026-07-01",
        end_date="2026-07-20",
        client_name="Иванов Иван Иванович",
    )
    app = create_app(settings)
    app.config.update(
        EMPLOYEE_PROVIDER=lambda: "API Сотрудник",
        TODAY_PROVIDER=lambda: WHEN.date(),
        TIMESTAMP_PROVIDER=lambda: WHEN,
    )

    response = app.test_client().post("/api/reminders", json=reminder_payload())
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] == "overdue"
    assert body["reminder_count"] == 1
    assert body["reminder_status"] == "Оповещён сегодня в 14:07"
    assert parse_qs(urlsplit(body["whatsapp_url"]).query)["text"][0].startswith(
        "Здравствуйте, Иван Иванович!"
    )


def test_confirmed_renewal_changes_status_and_makes_reminder_ineligible(
    settings, insert_test_contract
):
    insert_test_contract(
        cell_number="1",
        start_date="2026-07-01",
        end_date="2026-07-28",
    )
    send_reminder(
        settings,
        payload=reminder_payload(),
        employee="Сотрудник",
        occurred_at=WHEN,
    )

    renew_contract(
        settings,
        payload={
            "operation_id": str(uuid4()),
            "cell_number": "1",
            "contract_ref": "contract-test-1",
            "expected_end_date": "2026-07-28",
            "new_end_date": "2026-08-27",
            "renewal_days": 30,
        },
        employee="Сотрудник",
        renewal_date=WHEN.date(),
        occurred_at=WHEN + timedelta(minutes=5),
    )

    cell = list_cells(
        settings,
        as_of_date=WHEN.date(),
        as_of_datetime=WHEN + timedelta(minutes=5),
    )["cells"][0]
    assert cell["status"] == "normal"
    assert cell["reminder_count"] == 1
    with pytest.raises(ReminderConflictError, match="только для истекающей"):
        send_reminder(
            settings,
            payload=reminder_payload(),
            employee="Сотрудник",
            occurred_at=WHEN + timedelta(minutes=6),
        )
