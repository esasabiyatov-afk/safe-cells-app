"""Development entry point. The desktop shortcut launcher is added in stage 12."""

from __future__ import annotations

import argparse
from pathlib import Path

from app import create_app
from app.config import ConfigError, load_settings
from app.db.connections import DatabaseUnavailableError, validate_database_pair


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe Cells local development server")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.local.json"),
        help="Путь к локальному JSON-файлу конфигурации.",
    )
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    try:
        settings = load_settings(args.config)
        validate_database_pair(settings)
    except (ConfigError, DatabaseUnavailableError) as exc:
        parser.error(str(exc))

    app = create_app(settings)
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
