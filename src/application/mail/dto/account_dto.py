from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class MailAccountDTO:
    """
    A single mailbox the aggregator can read from and send through.

    One DTO describes any provider (Gmail, Outlook, Mail.ru, Yandex, ...) —
    only the host/port pairs differ, so the rest of the app never has to know
    which service it is talking to.
    """

    name: str  # human label, unique across the app (e.g. "Work Gmail")
    email: str  # address shown as the From: of outgoing mail
    username: str  # IMAP/SMTP login (usually the same as email)
    password: str  # password or, for most providers, an app password

    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int

    use_ssl: bool = True  # IMAP over SSL; SMTP picks SSL/STARTTLS by port

    # Authentication. "password" uses `password`; "oauth2" ignores it and uses
    # the OAuth fields below (e.g. Outlook, which disabled basic auth).
    auth: str = "password"
    oauth_provider: str | None = None  # slug into OAUTH_PROVIDERS, e.g. "microsoft"
    client_id: str | None = None  # app id the user registered
    refresh_token: str | None = None  # long-lived token to mint access tokens

    def to_dict(self) -> dict[str, object]:
        """Serialize for the on-disk accounts store."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> MailAccountDTO:
        """Rebuild an account from the on-disk accounts store."""
        return cls(**data)  # type: ignore[arg-type]

    def masked(self) -> str:
        """One-line summary safe to print (password hidden)."""
        return f"{self.name} <{self.email}> imap={self.imap_host} smtp={self.smtp_host}"
