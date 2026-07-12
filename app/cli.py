"""Explicit administrative commands for database initialization."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from app.config import ConfigError, load_settings
from app.db.migrations import DatabaseMigrationError, migrate_v2_to_v3
from app.db.schema import DatabaseInitializationError, initialize_databases
from app.db.seed import SeedDataError


CONFIRMATION_TEXT = "INITIALIZE"
MIGRATION_CONFIRMATION_TEXT = "MIGRATE-TO-3"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Администрирование Safe Cells")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser(
        "init-db", description="Явно создать или проверить две базы."
    )
    init_parser.add_argument("--config", type=Path, required=True)
    init_parser.add_argument(
        "--cells-csv", type=Path, default=Path("data/cell_heights.csv")
    )
    init_parser.add_argument("--confirm", required=True)
    migrate_parser = subparsers.add_parser(
        "migrate-v3", description="Явно обновить обе базы со схемы 2 до схемы 3."
    )
    migrate_parser.add_argument("--config", type=Path, required=True)
    migrate_parser.add_argument("--confirm", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init-db":
        if args.confirm != CONFIRMATION_TEXT:
            parser.error(
                f"Для явной инициализации укажите --confirm {CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = initialize_databases(
                settings, cells_csv_path=args.cells_csv
            )
        except (ConfigError, DatabaseInitializationError, SeedDataError) as exc:
            parser.error(str(exc))
        action = "созданы" if result.created else "проверены без дублирования"
        print(
            f"Базы {action}. Ячеек: {result.cell_count}. "
            f"Тарифов: {result.tariff_count}. Версия схемы: {result.schema_version}."
        )
        return 0
    if args.command == "migrate-v3":
        if args.confirm != MIGRATION_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v2_to_v3(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 3"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    parser.error("Неизвестная команда.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
