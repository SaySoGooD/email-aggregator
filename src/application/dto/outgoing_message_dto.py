from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OutgoingMessageDTO:
    """A message the user wants to send from one of their accounts."""

    account: str
    to: list[str]
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
