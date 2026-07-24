from __future__ import annotations

import json
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).parents[1] / "scripts" / "configure_database.ps1"
TEMPLATE_NAMES = (
    "Акт приема передач сейф.docx",
    "бирка на конверт.docx",
    "Договор индивидуального сейфа ф.л.docx",
    "Распоряжение Открытие сейф.docx",
    "Доп. соглашение сейф ф.л.docx",
    "Распоряжение Закрытие сейф.docx",
)


def _portable(tmp_path: Path) -> Path:
    portable = tmp_path / "portable"
    portable.mkdir()
    (portable / "safe-cells.exe").write_bytes(b"test executable")
    return portable


def _shared(tmp_path: Path) -> Path:
    shared = tmp_path / "Общая папка"
    templates = shared / "templates"
    templates.mkdir(parents=True)
    (shared / "vault_cells.sqlite3").write_bytes(b"working")
    (shared / "vault_archive.sqlite3").write_bytes(b"archive")
    for name in TEMPLATE_NAMES:
        (templates / name).write_bytes(b"docx")
    return shared


def _run(portable: Path, shared: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-InstallDirectory",
            str(portable),
            "-DatabaseDirectory",
            str(shared),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_configuration_tool_writes_verified_utf8_json_without_disclosing_path(
    tmp_path: Path,
) -> None:
    portable = _portable(tmp_path)
    shared = _shared(tmp_path)
    previous = b'{"database_directory": "old"}\n'
    (portable / "config.json").write_bytes(previous)

    result = _run(portable, shared)

    assert result.returncode == 0, result.stderr
    assert str(shared) not in result.stdout
    assert str(shared) not in result.stderr
    assert (portable / "config.previous.json").read_bytes() == previous
    raw = (portable / "config.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8")) == {
        "database_directory": str(shared.resolve()),
        "working_database_name": "vault_cells.sqlite3",
        "archive_database_name": "vault_archive.sqlite3",
    }


def test_configuration_tool_rejects_incomplete_folder_without_replacing_config(
    tmp_path: Path,
) -> None:
    portable = _portable(tmp_path)
    existing = portable / "config.json"
    existing.write_text('{"existing": true}\n', encoding="utf-8")
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()

    result = _run(portable, incomplete)

    assert result.returncode != 0
    assert existing.read_text(encoding="utf-8") == '{"existing": true}\n'
    assert not (portable / "config.previous.json").exists()
