from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

_OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR


def restrict(path: Path) -> None:
    """Make *path* readable only by its owner (no-op on Windows)."""
    if sys.platform.startswith("win"):
        return
    try:
        os.chmod(path, _OWNER_ONLY)
    except OSError:
        pass


def write_private_bytes(path: Path, data: bytes) -> None:
    """Replace *path* with *data*, atomically and with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        restrict(tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def shred(path: Path) -> None:
    """Overwrite and delete a file that held plaintext secrets (best effort)."""
    try:
        size = path.stat().st_size
        with path.open("r+b") as fh:
            for _ in range(3):
                fh.seek(0)
                fh.write(os.urandom(size))
                fh.flush()
                os.fsync(fh.fileno())
    except OSError:
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
