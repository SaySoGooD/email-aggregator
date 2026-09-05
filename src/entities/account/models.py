from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class MailAccountDTO:
    """A single mailbox the aggregator can read from and send through."""

    name: str
    email: str
    username: str
    password: str

    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int

    use_ssl: bool = True

    auth: str = "password"
    oauth_provider: str | None = None
    client_id: str | None = None
    refresh_token: str | None = None

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
