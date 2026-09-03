from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.exceptions import InvalidTag

from src.adapter.mail import crypto
from src.adapter.mail.secure_file import shred, write_private_bytes
from src.application.mail.dto.account_dto import MailAccountDTO
from src.application.mail.exceptions import AccountAlreadyExistsError, MailException
from src.application.mail.interfaces.i_account_repository import IAccountRepository


class LockedError(MailException):
    """Raised when the store is used before being unlocked."""


class EncryptedAccountRepository(IAccountRepository):
    """
    Account store encrypted at rest with AES-256-GCM, keyed by a master password
    stretched through Argon2id + a random salt.

    Credentials (passwords, OAuth refresh tokens) never touch disk in the clear.
    The store must be unlocked (or initialized) before any read/write; the
    derived key and decrypted accounts live only in memory.
    """

    def __init__(self, path: str, legacy_path: str | None = None) -> None:
        self._path = Path(path)
        self._legacy = Path(legacy_path) if legacy_path else None
        self._key: bytearray | None = None
        self._salt: bytes | None = None
        self._accounts: list[MailAccountDTO] | None = None

    # -- lifecycle -----------------------------------------------------

    def is_initialized(self) -> bool:
        return self._path.exists()

    def initialize(self, password: str) -> None:
        """Create a new encrypted store, importing any legacy plaintext accounts."""
        self.lock()
        self._salt = crypto.new_salt()
        self._key = crypto.derive_key(password, self._salt)
        self._accounts = self._read_legacy()
        self._write()
        # Only once the ciphertext is safely on disk is it right to destroy the
        # plaintext original; shredding first would lose every account if the
        # write failed.
        self._retire_legacy()

    def unlock(self, password: str) -> None:
        """Decrypt the store with *password*; raises ValueError if it's wrong."""
        blob = json.loads(self._path.read_text(encoding="utf-8"))
        salt = base64.b64decode(blob["salt"])
        nonce = base64.b64decode(blob["nonce"])
        ciphertext = base64.b64decode(blob["ct"])
        key = crypto.derive_key(password, salt)
        try:
            plaintext = crypto.decrypt(nonce, ciphertext, key)
        except InvalidTag as e:
            crypto.wipe(key)
            raise ValueError("Wrong master password") from e
        self.lock()
        self._key = key
        self._salt = salt
        self._accounts = [MailAccountDTO.from_dict(d) for d in json.loads(plaintext)]

    def lock(self) -> None:
        """Drop the decrypted accounts and overwrite the derived key."""
        if self._key is not None:
            crypto.wipe(self._key)
        self._key = None
        self._accounts = None

    # -- IAccountRepository -------------------------------------------

    def list(self) -> list[MailAccountDTO]:
        return list(self._require())

    def get(self, name: str) -> MailAccountDTO | None:
        return next((a for a in self._require() if a.name == name), None)

    def add(self, account: MailAccountDTO) -> None:
        accounts = self._require()
        if any(a.name == account.name for a in accounts):
            raise AccountAlreadyExistsError(
                f"Account named {account.name!r} already exists."
            )
        accounts.append(account)
        self._write()

    def remove(self, name: str) -> None:
        self._accounts = [a for a in self._require() if a.name != name]
        self._write()

    # -- internals -----------------------------------------------------

    def _require(self) -> list[MailAccountDTO]:
        if self._accounts is None:
            raise LockedError("Account store is locked.")
        return self._accounts

    def _write(self) -> None:
        assert self._key is not None and self._salt is not None
        assert self._accounts is not None
        payload = json.dumps([a.to_dict() for a in self._accounts]).encode("utf-8")
        nonce, ciphertext = crypto.encrypt(payload, self._key)
        blob = {
            "v": 1,
            "kdf": "argon2id",
            "salt": base64.b64encode(self._salt).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "ct": base64.b64encode(ciphertext).decode(),
        }
        write_private_bytes(self._path, json.dumps(blob, indent=2).encode("utf-8"))

    def _read_legacy(self) -> list[MailAccountDTO]:
        """Parse the plaintext accounts.json (if any). Does not touch the file."""
        if not self._legacy or not self._legacy.exists():
            return []
        try:
            raw = json.loads(self._legacy.read_text(encoding="utf-8"))
            return [MailAccountDTO.from_dict(d) for d in raw]
        except (ValueError, TypeError):
            return []

    def _retire_legacy(self) -> None:
        """
        Destroy the imported plaintext store.

        This used to rename the file to accounts.json.migrated, which left every
        password sitting on disk in the clear while the UI reported the accounts
        as encrypted — the migration has to actually remove the plaintext for
        the encryption to mean anything.
        """
        if self._legacy and self._legacy.exists():
            shred(self._legacy)

    def purge_plaintext_remnants(self) -> None:
        """
        Remove plaintext credential files older versions left behind.

        Earlier releases "retired" accounts.json by renaming it to
        accounts.json.migrated, so anyone upgrading still has every mailbox
        password sitting on disk in the clear. The un-renamed accounts.json is
        deliberately left alone: if it is still there next to an initialized
        store it may hold accounts that were never imported, and deleting it
        would destroy them.
        """
        if not self._legacy:
            return
        for name in (".json.migrated", ".enc.migrated"):
            remnant = self._legacy.with_suffix(name)
            if remnant != self._path and remnant.exists():
                shred(remnant)
