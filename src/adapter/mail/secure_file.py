from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

_OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR  # 0600


def restrict(path: Path) -> None:
    """
    Make *path* readable only by its owner.

    A no-op on Windows, where the file inherits the ACL of %APPDATA% and is
    already limited to the current user; elsewhere the default umask would
    otherwise leave the account store world-readable at 0644.
    """
    if sys.platform.startswith("win"):
        return
    try:
        os.chmod(path, _OWNER_ONLY)
    except OSError:
        pass


def write_private_bytes(path: Path, data: bytes) -> None:
    """
    Replace *path* with *data*, atomically and with owner-only permissions.

    Writing straight over the file leaves a truncated stub if the process dies
    mid-write — for the account store that is every mailbox credential gone
    with no way back. Write a sibling temp file first and let os.replace swap
    it in as a single filesystem operation, so the old file survives intact
    until the new one is complete on disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        restrict(tmp)  # mkstemp already creates at 0600; keep it so after replace
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def shred(path: Path) -> None:
    """
    Destroy a file that held plaintext secrets.

    Overwrite the bytes before unlinking, so an undelete does not hand the
    credentials back. On a journalling or copy-on-write filesystem, or an SSD
    that remaps blocks internally, the old content may still survive somewhere
    this process cannot address — a real improvement over a bare unlink, not a
    guarantee.
    """
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
