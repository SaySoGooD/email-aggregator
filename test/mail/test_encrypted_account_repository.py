import json

import pytest

from src.adapter.mail.encrypted_account_repository import (
    EncryptedAccountRepository,
    LockedError,
)
from src.application.mail.dto.account_dto import MailAccountDTO


def _account(name: str = "Work") -> MailAccountDTO:
    return MailAccountDTO(
        name=name,
        email=f"{name}@x.com",
        username=f"{name}@x.com",
        password="s3cret",
        imap_host="imap.x",
        imap_port=993,
        smtp_host="smtp.x",
        smtp_port=465,
    )


def test_initialize_encrypts_and_unlock_roundtrips(tmp_path):
    path = str(tmp_path / "accounts.enc")
    repo = EncryptedAccountRepository(path)
    repo.initialize("hunter2")
    repo.add(_account("Work"))

    # The file on disk must not contain the plaintext secret.
    raw = (tmp_path / "accounts.enc").read_text(encoding="utf-8")
    assert "s3cret" not in raw
    assert json.loads(raw)["kdf"] == "argon2id"

    reopened = EncryptedAccountRepository(path)
    reopened.unlock("hunter2")
    assert reopened.get("Work").password == "s3cret"


def test_wrong_password_raises(tmp_path):
    path = str(tmp_path / "accounts.enc")
    EncryptedAccountRepository(path).initialize("right")
    repo = EncryptedAccountRepository(path)
    with pytest.raises(ValueError):
        repo.unlock("wrong")


def test_locked_before_unlock(tmp_path):
    path = str(tmp_path / "accounts.enc")
    EncryptedAccountRepository(path).initialize("pw")
    repo = EncryptedAccountRepository(path)  # not unlocked
    with pytest.raises(LockedError):
        repo.list()


def test_migrates_legacy_plaintext(tmp_path):
    legacy = tmp_path / "accounts.json"
    legacy.write_text(
        json.dumps([_account("Old").to_dict()]), encoding="utf-8"
    )
    repo = EncryptedAccountRepository(str(tmp_path / "accounts.enc"), str(legacy))
    repo.initialize("pw")

    assert {a.name for a in repo.list()} == {"Old"}
    # The plaintext file is destroyed, not renamed: leaving an accounts.json.migrated
    # behind kept every password on disk in the clear.
    assert not legacy.exists()
    assert list(tmp_path.glob("accounts.json*")) == []
