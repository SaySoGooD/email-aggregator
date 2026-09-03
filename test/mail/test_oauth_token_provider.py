import base64

import pytest

from src.adapter.mail.imap_smtp_adapter import ImapSmtpMailAdapter
from src.adapter.mail.oauth_token_provider import OAuthTokenProvider
from src.application.mail.dto.account_dto import MailAccountDTO
from src.application.mail.exceptions import OAuthError
from src.application.mail.interfaces.i_oauth_token_provider import IOAuthTokenProvider


def _oauth_account() -> MailAccountDTO:
    return MailAccountDTO(
        name="Outlook",
        email="me@outlook.com",
        username="me@outlook.com",
        password="",
        imap_host="outlook.office365.com",
        imap_port=993,
        smtp_host="smtp-mail.outlook.com",
        smtp_port=587,
        auth="oauth2",
        oauth_provider="microsoft",
        client_id="cid",
        refresh_token="rtok",
    )


class StubTokens(IOAuthTokenProvider):
    def acquire_refresh_token(self, provider, client_id, on_prompt):  # pragma: no cover
        return "rtok"

    def access_token(self, provider, client_id, refresh_token):
        return "ACCESS123"


def test_xoauth2_string_is_well_formed():
    adapter = ImapSmtpMailAdapter(oauth=StubTokens())
    raw = adapter._xoauth2(_oauth_account())
    assert raw == b"user=me@outlook.com\x01auth=Bearer ACCESS123\x01\x01"
    # Base64-round-trips (that is what IMAP/SMTP put on the wire).
    assert base64.b64encode(raw)


def test_xoauth2_without_provider_configured_raises():
    adapter = ImapSmtpMailAdapter(oauth=None)
    with pytest.raises(OAuthError):
        adapter._xoauth2(_oauth_account())


def test_xoauth2_missing_credentials_raises():
    account = _oauth_account()
    account.refresh_token = None
    adapter = ImapSmtpMailAdapter(oauth=StubTokens())
    with pytest.raises(OAuthError):
        adapter._xoauth2(account)


def test_access_token_is_cached(monkeypatch):
    provider = OAuthTokenProvider()
    calls = []

    def fake_post(url, fields):
        calls.append(fields["grant_type"])
        return {"access_token": "AT", "expires_in": 3600}

    monkeypatch.setattr(provider, "_post", staticmethod(fake_post))

    first = provider.access_token("microsoft", "cid", "rtok")
    second = provider.access_token("microsoft", "cid", "rtok")

    assert first == second == "AT"
    assert calls == ["refresh_token"]  # second call served from cache


def test_unknown_provider_raises():
    provider = OAuthTokenProvider()
    with pytest.raises(OAuthError):
        provider.access_token("nope", "cid", "rtok")
