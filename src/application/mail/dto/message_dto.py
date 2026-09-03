from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MessageDTO:
    """A received message, normalized across every provider."""

    account: str  # name of the MailAccountDTO it was fetched from
    uid: str  # stable IMAP UID within (account, folder)
    subject: str
    sender: str
    date: datetime | None
    preview: str  # short, single-line body excerpt
    seen: bool
    folder: str = "inbox"  # logical folder: inbox / sent / spam

    recipients: str = ""  # raw To header
    body_text: str | None = None  # plain-text body, if any
    body_html: str | None = None  # HTML body, if any

    def short_date(self) -> str:
        """Compact date string for list rendering."""
        return self.date.strftime("%Y-%m-%d %H:%M") if self.date else "—"
