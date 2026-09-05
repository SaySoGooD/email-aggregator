from __future__ import annotations

import re

from src.application.exceptions import MailFetchError
from src.entities.account.models import MailAccountDTO

_APP_PASSWORD = re.compile(r"^(?:[a-z]{4}\s+){3}[a-z]{4}$", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_credential(value: str) -> str:
    """Normalise a password for the wire."""
    value = _CONTROL.sub("", value).strip()
    if _APP_PASSWORD.match(value):
        return "".join(value.split())
    return value


def quote_mailbox(name: str) -> str:
    """Quote a mailbox name for use as an IMAP command argument."""
    if _CONTROL.search(name):
        raise MailFetchError(f"Refusing mailbox name with control characters: {name!r}")
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def resolve_login_user(account: MailAccountDTO) -> str:
    """The login name; falls back to the email when username is blank."""
    return account.username.strip() or account.email.strip()
