from __future__ import annotations

import atexit
import shutil
import tempfile

_EXPORT_DIR: str | None = None


def export_dir() -> str:
    """A private, owner-only directory for messages exported to the system browser."""
    global _EXPORT_DIR
    if _EXPORT_DIR is None:
        _EXPORT_DIR = tempfile.mkdtemp(prefix="email-aggregator-")
        atexit.register(shutil.rmtree, _EXPORT_DIR, True)
    return _EXPORT_DIR
