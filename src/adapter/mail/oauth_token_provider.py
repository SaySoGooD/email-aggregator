from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from src.application.mail.exceptions import OAuthError
from src.application.mail.interfaces.i_oauth_token_provider import IOAuthTokenProvider


@dataclass(frozen=True)
class OAuthEndpoints:
    """OAuth2 device-code endpoints and scopes for one identity provider."""

    device_code_url: str
    token_url: str
    scopes: str


# One entry per identity provider. Adding Gmail later is just another row:
# Google's device_code/token URLs plus the https://mail.google.com/ scope.
OAUTH_PROVIDERS: dict[str, OAuthEndpoints] = {
    "microsoft": OAuthEndpoints(
        device_code_url="https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode",
        token_url="https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
        scopes=(
            "offline_access "
            "https://outlook.office.com/IMAP.AccessAsUser.All "
            "https://outlook.office.com/SMTP.Send"
        ),
    ),
}

_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_TIMEOUT = 20


class OAuthTokenProvider(IOAuthTokenProvider):
    """
    Device-code OAuth2 client built on the standard library.

    The device-code flow needs no local web server and no client secret: the
    user opens a URL, types a short code, and approves in their browser. That
    fits a console tool and a public (native) app registration.

    Access tokens are cached in memory until shortly before they expire, so a
    burst of fetch/send calls does not hammer the token endpoint.
    """

    def __init__(self) -> None:
        # key: (client_id, sha256(refresh_token)) -> (access_token, expires_at_epoch)
        # The refresh token is the long-lived secret, so it is not kept as a
        # dictionary key: that would be a second copy of it living for the whole
        # process lifetime, reachable in any memory dump or core file.
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}

    @staticmethod
    def _cache_key(client_id: str, refresh_token: str) -> tuple[str, str]:
        digest = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
        return (client_id, digest)

    def acquire_refresh_token(
        self,
        provider: str,
        client_id: str,
        on_prompt: Callable[[str, str], None],
    ) -> str:
        endpoints = self._endpoints(provider)

        start = self._post(
            endpoints.device_code_url,
            {"client_id": client_id, "scope": endpoints.scopes},
        )
        device_code = start["device_code"]
        interval = int(start.get("interval", 5))
        deadline = time.monotonic() + int(start.get("expires_in", 900))
        on_prompt(start["verification_uri"], start["user_code"])

        while time.monotonic() < deadline:
            time.sleep(interval)
            token = self._poll_token(endpoints.token_url, client_id, device_code)
            if token is None:
                continue
            if "slow_down" in token:
                interval += 5
                continue
            if "refresh_token" in token:
                return token["refresh_token"]
            raise OAuthError(f"Authorization failed: {token.get('error')}")

        raise OAuthError("Device-code authorization timed out.")

    def access_token(
        self,
        provider: str,
        client_id: str,
        refresh_token: str,
    ) -> str:
        key = self._cache_key(client_id, refresh_token)
        cached = self._cache.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]

        endpoints = self._endpoints(provider)
        data = self._post(
            endpoints.token_url,
            {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": endpoints.scopes,
            },
        )
        if "access_token" not in data:
            raise OAuthError(f"Token refresh failed: {data.get('error')}")

        access = data["access_token"]
        # Refresh a minute early to avoid using a token that expires mid-call.
        expires_at = time.monotonic() + int(data.get("expires_in", 3600)) - 60
        self._cache[key] = (access, expires_at)
        return access

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _endpoints(provider: str) -> OAuthEndpoints:
        endpoints = OAUTH_PROVIDERS.get(provider)
        if endpoints is None:
            raise OAuthError(f"Unknown OAuth provider: {provider!r}")
        return endpoints

    def _poll_token(
        self,
        token_url: str,
        client_id: str,
        device_code: str,
    ) -> dict | None:
        """
        One poll of the token endpoint.

        Returns the token payload on success, a dict with ``error`` for the
        expected pending/slow-down states, or None to keep waiting.
        """
        try:
            return self._post(
                token_url,
                {
                    "client_id": client_id,
                    "grant_type": _DEVICE_GRANT,
                    "device_code": device_code,
                },
            )
        except _HttpError as e:
            error = e.payload.get("error")
            if error == "authorization_pending":
                return None
            if error == "slow_down":
                return {"slow_down": True}
            raise OAuthError(f"Authorization failed: {error or e}") from e

    @staticmethod
    def _post(url: str, fields: dict[str, str]) -> dict:
        body = urllib.parse.urlencode(fields).encode()
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            # OAuth errors arrive as 400 with a JSON body we must inspect.
            try:
                payload = json.loads(e.read())
            except (ValueError, OSError):
                payload = {}
            raise _HttpError(payload) from e
        except urllib.error.URLError as e:
            raise OAuthError(f"Cannot reach {url}: {e.reason}") from e


class _HttpError(Exception):
    """Internal: carries the parsed JSON body of a 4xx token response."""

    def __init__(self, payload: dict) -> None:
        super().__init__(payload.get("error", "http error"))
        self.payload = payload
