from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_dir() -> Path:
    """Base dir for bundled read-only assets (fonts, icons)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """Per-user writable dir for the account store, history and settings."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "EmailAggregator"
    path.mkdir(parents=True, exist_ok=True)
    return path
