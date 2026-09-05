from abc import ABC, abstractmethod
from typing import Callable


class IOAuthTokenProvider(ABC):
    """Mints OAuth2 tokens for mailboxes that reject password auth (e.g. Outlook)."""

    @abstractmethod
    def acquire_refresh_token(
        self,
        provider: str,
        client_id: str,
        on_prompt: Callable[[str, str], None],
    ) -> str:
        """Run the device-code flow and return a long-lived refresh token."""
        ...

    @abstractmethod
    def access_token(
        self,
        provider: str,
        client_id: str,
        refresh_token: str,
    ) -> str:
        """Exchange a refresh token for a short-lived access token."""
        ...
