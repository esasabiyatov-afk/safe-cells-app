"""Validated local configuration for database locations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePath
from typing import Any, Mapping


DEFAULT_WORKING_DATABASE_NAME = "vault_cells.sqlite3"
DEFAULT_ARCHIVE_DATABASE_NAME = "vault_archive.sqlite3"
DEFAULT_BUSY_TIMEOUT_MS = 15_000


class ConfigError(ValueError):
    """Raised when the local configuration is absent or unsafe."""


def _validate_database_name(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Параметр {field_name} должен содержать имя файла базы.")

    name = value.strip()
    if PurePath(name).name != name or "/" in name or "\\" in name:
        raise ConfigError(f"Параметр {field_name} должен содержать только имя файла.")
    if not name.lower().endswith(".sqlite3"):
        raise ConfigError(f"Параметр {field_name} должен оканчиваться на .sqlite3.")
    return name


@dataclass(frozen=True, slots=True)
class Settings:
    """Settings shared by the Flask app and database layer."""

    database_directory: Path
    working_database_name: str = DEFAULT_WORKING_DATABASE_NAME
    archive_database_name: str = DEFAULT_ARCHIVE_DATABASE_NAME
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
    testing: bool = False

    def __post_init__(self) -> None:
        directory = Path(self.database_directory)
        if not str(directory).strip():
            raise ConfigError("Не указан путь к общей папке баз данных.")
        object.__setattr__(self, "database_directory", directory)

        working = _validate_database_name(
            self.working_database_name, "working_database_name"
        )
        archive = _validate_database_name(
            self.archive_database_name, "archive_database_name"
        )
        if working.casefold() == archive.casefold():
            raise ConfigError("Рабочая и архивная базы должны иметь разные имена.")
        object.__setattr__(self, "working_database_name", working)
        object.__setattr__(self, "archive_database_name", archive)

        if not isinstance(self.busy_timeout_ms, int) or isinstance(
            self.busy_timeout_ms, bool
        ):
            raise ConfigError("busy_timeout должен быть целым числом миллисекунд.")
        if self.busy_timeout_ms != DEFAULT_BUSY_TIMEOUT_MS and not self.testing:
            raise ConfigError("Производственный busy_timeout должен быть равен 15000 мс.")
        if self.busy_timeout_ms <= 0:
            raise ConfigError("busy_timeout должен быть положительным.")

    @classmethod
    def from_mapping(
        cls, values: Mapping[str, Any], *, testing: bool = False
    ) -> "Settings":
        directory = values.get("database_directory")
        if not isinstance(directory, str) or not directory.strip():
            raise ConfigError("В конфигурации не указан database_directory.")
        return cls(
            database_directory=Path(directory),
            working_database_name=values.get(
                "working_database_name", DEFAULT_WORKING_DATABASE_NAME
            ),
            archive_database_name=values.get(
                "archive_database_name", DEFAULT_ARCHIVE_DATABASE_NAME
            ),
            busy_timeout_ms=values.get("busy_timeout_ms", DEFAULT_BUSY_TIMEOUT_MS),
            testing=testing,
        )


def load_settings(config_path: Path | str, *, testing: bool = False) -> Settings:
    """Load a local JSON config without creating paths or database files."""

    path = Path(config_path)
    if not path.is_file():
        raise ConfigError(f"Файл конфигурации не найден: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Не удалось прочитать конфигурацию: {path}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("Корень конфигурации должен быть JSON-объектом.")
    return Settings.from_mapping(raw, testing=testing)
