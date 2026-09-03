from __future__ import annotations

import os

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Argon2id parameters for deriving the encryption key from the master password.
_TIME_COST = 3
_MEMORY_COST = 64 * 1024  # 64 MiB
_PARALLELISM = 4
_KEY_LEN = 32  # AES-256
_SALT_LEN = 16
_NONCE_LEN = 12


def new_salt() -> bytes:
    return os.urandom(_SALT_LEN)


def derive_key(password: str, salt: bytes) -> bytearray:
    """
    Derive a 32-byte key from the master password via Argon2id.

    Returned as a bytearray so the caller can overwrite it with `wipe` when the
    store is locked; an immutable `bytes` would linger in the heap until the
    garbage collector happens to reclaim it.
    """
    return bytearray(
        hash_secret_raw(
            password.encode("utf-8"),
            salt,
            time_cost=_TIME_COST,
            memory_cost=_MEMORY_COST,
            parallelism=_PARALLELISM,
            hash_len=_KEY_LEN,
            type=Type.ID,
        )
    )


def wipe(buffer: bytearray) -> None:
    """
    Overwrite a key buffer in place.

    Best effort: CPython can still hold copies (the password string itself, the
    bytes argon2 handed back) that no library can reach, so this shrinks the
    window a memory dump has rather than closing it.
    """
    for i in range(len(buffer)):
        buffer[i] = 0


def encrypt(data: bytes, key: bytes | bytearray) -> tuple[bytes, bytes]:
    """Return (nonce, ciphertext) for *data* under AES-256-GCM."""
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(bytes(key)).encrypt(nonce, data, None)
    return nonce, ciphertext


def decrypt(nonce: bytes, ciphertext: bytes, key: bytes | bytearray) -> bytes:
    """Decrypt; raises cryptography.exceptions.InvalidTag on a wrong key."""
    return AESGCM(bytes(key)).decrypt(nonce, ciphertext, None)
