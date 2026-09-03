from abc import ABC, abstractmethod
from typing import Callable


class IOAuthTokenProvider(ABC):
    """
    Mints OAuth2 tokens for mailboxes that reject password auth (e.g. Outlook).

    Kept synchronous on purpose: the IMAP/SMTP adapter already runs its blocking
    work in a worker thread and calls this from there, so async would only add
    ceremony.
    """

    @abstractmethod
    def acquire_refresh_token(
        self,
        provider: str,
        client_id: str,
        on_prompt: Callable[[str, str], None],
    ) -> str:
        """
        Run the device-code flow and return a long-lived refresh token.

        ``on_prompt(verification_uri, user_code)`` is called once so the caller
        can tell the user where to go and which code to enter.
        """
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
