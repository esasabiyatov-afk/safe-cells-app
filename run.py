"""Source and PyInstaller entry point for the local portable application."""

from __future__ import annotations

from app.runtime import main


if __name__ == "__main__":
    raise SystemExit(main())
