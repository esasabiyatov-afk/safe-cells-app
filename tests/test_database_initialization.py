from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

import pytest

from app.config import Settings
from app.db.connections import (
    DatabasePaths,
    DatabaseUnavailableError,
    open_readonly,
    open_write,
    validate_database_pair,
)
from app.db.schema import DatabaseInitializationError, initialize_databases
from app.db.seed import DOCUMENT_TEMPLATE_SEEDS, SeedDataError


@contextmanager
def _connect_readonly(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(
        f"{path.absolute().as_uri()}?mode=ro", uri=True
    )
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def _connect_writable(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def test_initialization_registers_only_supplied_approved_document_templates(
    settings: Settings, cells_csv_path: Path
) -> None:
    template_directory = settings.database_directory / "templates"
    template_directory.mkdir()
    for _template_id, _event, _display, file_name, _required in DOCUMENT_TEMPLATE_SEEDS:
        (template_directory / file_name).write_bytes(b"test placeholder file")

    result = initialize_databases(settings, cells_csv_path=cells_csv_path)

    with _connect_readonly(result.working_database) as connection:
        rows = connection.execute(
            """SELECT document_type, COUNT(*)
               FROM document_templates GROUP BY document_type
               ORDER BY document_type"""
        ).fetchall()
    assert rows == [("closing", 1), ("opening", 3), ("renewal", 1)]


def test_initialization_creates_two_complete_databases(
    settings: Settings, cells_csv_path: Path
) -> None:
    result = initialize_databases(settings, cells_csv_path=cells_csv_path)
    paths = DatabasePaths.from_settings(settings)

    assert result.created is True
    assert result.cell_count == 126
    assert result.tariff_count == 24
    assert paths.working.is_file()
    assert paths.archive.is_file()

    with _connect_readonly(paths.working) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "schema_version",
            "vault_defaults",
            "cells",
            "tariffs",
            "config",
            "contracts",
            "admin_credentials",
            "document_templates",
        } <= tables
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"

    with _connect_readonly(paths.archive) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"schema_version", "contracts_archive", "renewals", "log"} <= tables
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_seed_values_are_exact(
    settings: Settings, initialized_databases
) -> None:
    paths = DatabasePaths.from_settings(settings)
    with _connect_readonly(paths.working) as connection:
        assert connection.execute(
            "SELECT width_mm, depth_mm FROM vault_defaults WHERE id = 1"
        ).fetchone() == (220, 330)
        assert connection.execute("SELECT COUNT(*) FROM cells").fetchone()[0] == 126
        assert connection.execute("SELECT COUNT(*) FROM tariffs").fetchone()[0] == 24
        assert connection.execute(
            """
            SELECT price_per_day_minor FROM tariffs
            WHERE height_mm = 50 AND period_from_days = 1
            """
        ).fetchone()[0] == 15
        assert connection.execute(
            """
            SELECT price_per_day_minor FROM tariffs
            WHERE height_mm = 300 AND period_from_days = 181
            """
        ).fetchone()[0] == 17
        config = dict(connection.execute("SELECT key, value FROM config"))
        assert config == {
            "admin_access_mode": "password",
            "currency_code": "KGS",
            "currency_scale": "0",
            "deposit_amount_minor": "1500",
            "employees_json": "[]",
            "expiring_soon_days": "7",
            "penalty_manual_rates_json": '{"100":17,"125":20,"175":25,"300":30,"50":15,"75":17}',
            "penalty_rate_mode": "linked",
        }


def test_repeated_initialization_is_idempotent_and_preserves_admin_changes(
    settings: Settings, cells_csv_path: Path, initialized_databases
) -> None:
    paths = DatabasePaths.from_settings(settings)
    with _connect_writable(paths.working) as connection:
        connection.execute(
            """
            UPDATE tariffs SET price_per_day_minor = 99
            WHERE height_mm = 50 AND period_from_days = 1
            """
        )
        connection.execute(
            """
            UPDATE config
            SET value = '2000', updated_by = 'test-admin'
            WHERE key = 'deposit_amount_minor'
            """
        )

    result = initialize_databases(settings, cells_csv_path=cells_csv_path)

    assert result.created is False
    assert result.cell_count == 126
    assert result.tariff_count == 24
    with _connect_readonly(paths.working) as connection:
        assert connection.execute(
            """
            SELECT price_per_day_minor FROM tariffs
            WHERE height_mm = 50 AND period_from_days = 1
            """
        ).fetchone()[0] == 99
        assert connection.execute(
            "SELECT value FROM config WHERE key = 'deposit_amount_minor'"
        ).fetchone()[0] == "2000"


def test_reinitialization_fills_previously_unconfigured_money_settings(
    settings: Settings, cells_csv_path: Path, initialized_databases
) -> None:
    paths = DatabasePaths.from_settings(settings)
    with _connect_writable(paths.working) as connection:
        connection.execute(
            """
            UPDATE config SET value = ''
            WHERE key IN ('deposit_amount_minor', 'currency_code', 'currency_scale')
              AND updated_by = 'system-seed'
            """
        )

    initialize_databases(settings, cells_csv_path=cells_csv_path)

    with _connect_readonly(paths.working) as connection:
        money_config = dict(
            connection.execute(
                """
                SELECT key, value FROM config
                WHERE key IN ('deposit_amount_minor', 'currency_code', 'currency_scale')
                """
            )
        )
    assert money_config == {
        "currency_code": "KGS",
        "currency_scale": "0",
        "deposit_amount_minor": "1500",
    }


def test_conflicting_existing_cell_height_aborts_seed(
    settings: Settings, cells_csv_path: Path, initialized_databases
) -> None:
    paths = DatabasePaths.from_settings(settings)
    with _connect_writable(paths.working) as connection:
        connection.execute("UPDATE cells SET height_mm = 75 WHERE number = '1'")

    with pytest.raises(SeedDataError, match="не совпадает"):
        initialize_databases(settings, cells_csv_path=cells_csv_path)

    with _connect_readonly(paths.working) as connection:
        assert connection.execute(
            "SELECT height_mm FROM cells WHERE number = '1'"
        ).fetchone()[0] == 75


def test_database_unique_constraint_blocks_two_active_contracts(
    settings: Settings, initialized_databases
) -> None:
    insert_sql = """
        INSERT INTO contracts(
            contract_id, cell_number, client_full_name,
            id_card_number, id_card_issuer, id_card_issue_date,
            account_number, start_date, end_date, rent_days,
            price_per_day_minor, rent_price_minor, deposit_amount_minor,
            created_at, created_by, updated_at, updated_by
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    first = (
        "contract-test-1",
        "1",
        "Тестовый Клиент Один",
        "TEST-ID-001",
        "Тестовый орган",
        "2030-12-31",
        "TEST-ACCOUNT-001",
        "2026-07-01",
        "2026-07-01",
        1,
        15,
        15,
        0,
        "2026-07-01T09:00:00+06:00",
        "test-user",
        "2026-07-01T09:00:00+06:00",
        "test-user",
    )
    second = list(first)
    second[0] = "contract-test-2"

    with open_write(settings) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(insert_sql, first)
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="contracts.cell_number"):
        with open_write(settings) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(insert_sql, tuple(second))

    paths = DatabasePaths.from_settings(settings)
    with _connect_readonly(paths.working) as connection:
        assert connection.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 1


def test_write_connection_uses_required_pragmas(
    settings: Settings, initialized_databases
) -> None:
    with open_write(settings, attach_archive=True) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 15_000
        assert connection.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete"
        assert connection.execute("PRAGMA main.synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA main.locking_mode").fetchone()[0] == "normal"
        assert connection.execute("PRAGMA archive.journal_mode").fetchone()[0] == "delete"
        assert connection.execute("PRAGMA archive.synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA archive.locking_mode").fetchone()[0] == "normal"


def test_readonly_connection_rejects_write_and_closes(
    settings: Settings, initialized_databases
) -> None:
    paths = DatabasePaths.from_settings(settings)
    connection: sqlite3.Connection
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        with open_readonly(paths.working) as connection:
            assert connection.execute("SELECT COUNT(*) FROM cells").fetchone()[0] == 126
            connection.execute("INSERT INTO cells(number, height_mm) VALUES('999', 50)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    with _connect_readonly(paths.working) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM cells WHERE number = '999'"
        ).fetchone()[0] == 0


def test_unavailable_directory_does_not_create_local_database(tmp_path: Path) -> None:
    missing = tmp_path / "network is unavailable"
    settings = Settings(database_directory=missing, testing=True)

    with pytest.raises(DatabaseUnavailableError, match="сетевого диска"):
        validate_database_pair(settings)

    assert not missing.exists()
    assert not (tmp_path / "vault_cells.sqlite3").exists()
    assert not (tmp_path / "vault_archive.sqlite3").exists()


def test_initialization_refuses_incomplete_database_pair(
    settings: Settings, cells_csv_path: Path
) -> None:
    paths = DatabasePaths.from_settings(settings)
    with _connect_writable(paths.working):
        pass
    size_before = paths.working.stat().st_size

    with pytest.raises(DatabaseInitializationError, match="только одна"):
        initialize_databases(settings, cells_csv_path=cells_csv_path)

    assert paths.working.stat().st_size == size_before
    assert not paths.archive.exists()


def test_invalid_seed_leaves_no_database_files(
    settings: Settings, tmp_path: Path
) -> None:
    invalid_csv = tmp_path / "invalid.csv"
    invalid_csv.write_text("number,height_mm\n1,50\n", encoding="utf-8")
    paths = DatabasePaths.from_settings(settings)

    with pytest.raises(SeedDataError):
        initialize_databases(settings, cells_csv_path=invalid_csv)

    assert not paths.working.exists()
    assert not paths.archive.exists()
    assert not list(paths.directory.glob("*.initializing"))


def test_failure_after_temporary_databases_start_leaves_no_pair(
    settings: Settings,
    cells_csv_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = DatabasePaths.from_settings(settings)

    def fail_after_schema(*args, **kwargs) -> None:
        raise RuntimeError("simulated seed failure")

    monkeypatch.setattr("app.db.schema.seed_working_database", fail_after_schema)

    with pytest.raises(RuntimeError, match="simulated"):
        initialize_databases(settings, cells_csv_path=cells_csv_path)

    assert not paths.working.exists()
    assert not paths.archive.exists()
    assert not list(paths.directory.glob("*.initializing"))


def test_incompatible_schema_version_is_rejected_without_change(
    settings: Settings, cells_csv_path: Path, initialized_databases
) -> None:
    paths = DatabasePaths.from_settings(settings)
    with _connect_writable(paths.working) as connection:
        connection.execute("UPDATE schema_version SET version = 99 WHERE singleton = 1")

    with pytest.raises(DatabaseInitializationError, match="несовместима"):
        initialize_databases(settings, cells_csv_path=cells_csv_path)

    with _connect_readonly(paths.working) as connection:
        assert connection.execute(
            "SELECT version FROM schema_version WHERE singleton = 1"
        ).fetchone()[0] == 99
