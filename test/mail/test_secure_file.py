import os

import pytest

from src.adapter.mail.secure_file import shred, write_private_bytes


def test_write_replaces_content(tmp_path):
    target = tmp_path / "store.enc"
    write_private_bytes(target, b"first")
    write_private_bytes(target, b"second")
    assert target.read_bytes() == b"second"


def test_write_leaves_no_temp_files_behind(tmp_path):
    target = tmp_path / "store.enc"
    write_private_bytes(target, b"payload")
    assert [p.name for p in tmp_path.iterdir()] == ["store.enc"]


def test_failed_write_keeps_the_previous_file_intact(tmp_path, monkeypatch):
    target = tmp_path / "store.enc"
    write_private_bytes(target, b"original")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_private_bytes(target, b"nope")

    # The point of the temp-file-then-replace dance: a half-written store would
    # mean every mailbox credential lost.
    assert target.read_bytes() == b"original"
    assert [p.name for p in tmp_path.iterdir()] == ["store.enc"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_written_file_is_owner_only(tmp_path):
    target = tmp_path / "store.enc"
    write_private_bytes(target, b"secret")
    assert oct(target.stat().st_mode & 0o777) == "0o600"


def test_shred_removes_the_file(tmp_path):
    plaintext = tmp_path / "accounts.json"
    plaintext.write_text("password: hunter2", encoding="utf-8")
    shred(plaintext)
    assert not plaintext.exists()


def test_shred_overwrites_before_unlinking(tmp_path, monkeypatch):
    plaintext = tmp_path / "accounts.json"
    plaintext.write_text("password: hunter2", encoding="utf-8")

    # Capture what the file held at the moment it was unlinked.
    contents_at_unlink = {}
    real_unlink = os.unlink

    def spy(path, *args, **kwargs):
        with open(path, "rb") as fh:
            contents_at_unlink["data"] = fh.read()
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", spy)
    shred(plaintext)

    assert b"hunter2" not in contents_at_unlink["data"]


def test_shred_tolerates_a_missing_file(tmp_path):
    shred(tmp_path / "never-existed.json")  # must not raise
