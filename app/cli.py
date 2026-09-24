"""Explicit administrative commands for database initialization."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from app.config import ConfigError, load_settings
from app.db.migrations import (
    DatabaseMigrationError,
    migrate_v2_to_v3,
    migrate_v3_to_v4,
    migrate_v4_to_v5,
    migrate_v5_to_v6,
    migrate_v6_to_v7,
    migrate_v7_to_v8,
    migrate_v8_to_v9,
    migrate_v9_to_v10,
    migrate_v10_to_v11,
    migrate_v11_to_v12,
)
from app.db.schema import DatabaseInitializationError, initialize_databases
from app.db.seed import SeedDataError


CONFIRMATION_TEXT = "INITIALIZE"
MIGRATION_CONFIRMATION_TEXT = "MIGRATE-TO-3"
MIGRATION_V4_CONFIRMATION_TEXT = "MIGRATE-TO-4"
MIGRATION_V5_CONFIRMATION_TEXT = "MIGRATE-TO-5"
MIGRATION_V6_CONFIRMATION_TEXT = "MIGRATE-TO-6"
MIGRATION_V7_CONFIRMATION_TEXT = "MIGRATE-TO-7"
MIGRATION_V8_CONFIRMATION_TEXT = "MIGRATE-TO-8"
MIGRATION_V9_CONFIRMATION_TEXT = "MIGRATE-TO-9"
MIGRATION_V10_CONFIRMATION_TEXT = "MIGRATE-TO-10"
MIGRATION_V11_CONFIRMATION_TEXT = "MIGRATE-TO-11"
MIGRATION_V12_CONFIRMATION_TEXT = "MIGRATE-TO-12"


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
    migrate_v4_parser = subparsers.add_parser(
        "migrate-v4", description="Явно обновить обе базы со схемы 3 до схемы 4."
    )
    migrate_v4_parser.add_argument("--config", type=Path, required=True)
    migrate_v4_parser.add_argument("--confirm", required=True)
    migrate_v5_parser = subparsers.add_parser(
        "migrate-v5", description="Явно обновить обе базы со схемы 4 до схемы 5."
    )
    migrate_v5_parser.add_argument("--config", type=Path, required=True)
    migrate_v5_parser.add_argument("--confirm", required=True)
    migrate_v6_parser = subparsers.add_parser(
        "migrate-v6", description="Явно обновить обе базы со схемы 5 до схемы 6."
    )
    migrate_v6_parser.add_argument("--config", type=Path, required=True)
    migrate_v6_parser.add_argument("--confirm", required=True)
    migrate_v7_parser = subparsers.add_parser(
        "migrate-v7", description="Явно обновить обе базы со схемы 6 до схемы 7."
    )
    migrate_v7_parser.add_argument("--config", type=Path, required=True)
    migrate_v7_parser.add_argument("--confirm", required=True)
    migrate_v8_parser = subparsers.add_parser(
        "migrate-v8", description="Явно обновить обе базы со схемы 7 до схемы 8."
    )
    migrate_v8_parser.add_argument("--config", type=Path, required=True)
    migrate_v8_parser.add_argument("--confirm", required=True)
    migrate_v9_parser = subparsers.add_parser(
        "migrate-v9", description="Явно обновить обе базы со схемы 8 до схемы 9."
    )
    migrate_v9_parser.add_argument("--config", type=Path, required=True)
    migrate_v9_parser.add_argument("--confirm", required=True)
    migrate_v10_parser = subparsers.add_parser(
        "migrate-v10", description="Явно обновить обе базы со схемы 9 до схемы 10."
    )
    migrate_v10_parser.add_argument("--config", type=Path, required=True)
    migrate_v10_parser.add_argument("--confirm", required=True)
    migrate_v11_parser = subparsers.add_parser(
        "migrate-v11", description="Явно обновить обе базы со схемы 10 до схемы 11."
    )
    migrate_v11_parser.add_argument("--config", type=Path, required=True)
    migrate_v11_parser.add_argument("--confirm", required=True)
    migrate_v12_parser = subparsers.add_parser(
        "migrate-v12", description="Явно обновить обе базы со схемы 11 до схемы 12."
    )
    migrate_v12_parser.add_argument("--config", type=Path, required=True)
    migrate_v12_parser.add_argument("--confirm", required=True)
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
    if args.command == "migrate-v4":
        if args.confirm != MIGRATION_V4_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_V4_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v3_to_v4(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 4"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    if args.command == "migrate-v5":
        if args.confirm != MIGRATION_V5_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_V5_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v4_to_v5(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 5"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    if args.command == "migrate-v6":
        if args.confirm != MIGRATION_V6_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_V6_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v5_to_v6(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 6"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    if args.command == "migrate-v7":
        if args.confirm != MIGRATION_V7_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_V7_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v6_to_v7(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 7"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    if args.command == "migrate-v8":
        if args.confirm != MIGRATION_V8_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_V8_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v7_to_v8(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 8"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    if args.command == "migrate-v9":
        if args.confirm != MIGRATION_V9_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_V9_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v8_to_v9(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 9"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    if args.command == "migrate-v10":
        if args.confirm != MIGRATION_V10_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_V10_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v9_to_v10(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 10"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    if args.command == "migrate-v11":
        if args.confirm != MIGRATION_V11_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_V11_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v10_to_v11(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 11"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    if args.command == "migrate-v12":
        if args.confirm != MIGRATION_V12_CONFIRMATION_TEXT:
            parser.error(
                f"Для миграции укажите --confirm {MIGRATION_V12_CONFIRMATION_TEXT}."
            )
        try:
            settings = load_settings(args.config)
            result = migrate_v11_to_v12(
                settings, occurred_at=datetime.now().astimezone()
            )
        except (ConfigError, DatabaseMigrationError) as exc:
            parser.error(str(exc))
        action = "обновлены" if result.changed else "уже соответствуют версии 12"
        print(f"Базы {action}. Версия схемы: {result.to_version}.")
        return 0
    parser.error("Неизвестная команда.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
