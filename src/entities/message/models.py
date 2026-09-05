from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MessageDTO:
    """A received message, normalized across every provider."""

    account: str
    uid: str
    subject: str
    sender: str
    date: datetime | None
    preview: str
    seen: bool
    folder: str = "inbox"

    recipients: str = ""
    body_text: str | None = None
    body_html: str | None = None

    def short_date(self) -> str:
        """Compact date string for list rendering."""
        return self.date.strftime("%Y-%m-%d %H:%M") if self.date else "—"
