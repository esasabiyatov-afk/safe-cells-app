from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli import main
from app.db.connections import DatabasePaths
from app.config import Settings


def test_init_cli_requires_exact_confirmation(
    tmp_path: Path, cells_csv_path: Path
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"database_directory": str(tmp_path)}), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "init-db",
                "--config",
                str(config_path),
                "--cells-csv",
                str(cells_csv_path),
                "--confirm",
                "WRONG",
            ]
        )

    assert exc_info.value.code == 2
    paths = DatabasePaths.from_settings(
        Settings(database_directory=tmp_path, testing=True)
    )
    assert not paths.working.exists()
    assert not paths.archive.exists()


def test_init_cli_creates_pair_only_after_confirmation(
    tmp_path: Path, cells_csv_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"database_directory": str(tmp_path)}), encoding="utf-8"
    )

    exit_code = main(
        [
            "init-db",
            "--config",
            str(config_path),
            "--cells-csv",
            str(cells_csv_path),
            "--confirm",
            "INITIALIZE",
        ]
    )

    assert exit_code == 0
    assert "Ячеек: 126" in capsys.readouterr().out
    paths = DatabasePaths.from_settings(
        Settings(database_directory=tmp_path, testing=True)
    )
    assert paths.working.is_file()
    assert paths.archive.is_file()
