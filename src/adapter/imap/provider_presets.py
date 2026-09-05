from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    """Ready-to-use IMAP/SMTP endpoints for a known mail provider."""

    name: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    note: str = ""
    auth: str = "password"
    oauth_provider: str | None = None


PRESETS: dict[str, ProviderPreset] = {
    "gmail": ProviderPreset(
        "Gmail",
        "imap.gmail.com",
        993,
        "smtp.gmail.com",
        465,
        note="Requires an App Password (2FA must be on).",
    ),
    "outlook": ProviderPreset(
        "Outlook / Office 365",
        "outlook.office365.com",
        993,
        "smtp-mail.outlook.com",
        587,
        note="Basic auth is disabled — sign in via OAuth2 (device code).",
        auth="oauth2",
        oauth_provider="microsoft",
    ),
    "mailru": ProviderPreset(
        "Mail.ru",
        "imap.mail.ru",
        993,
        "smtp.mail.ru",
        465,
        note="Requires an app password from the Mail.ru security page.",
    ),
    "yandex": ProviderPreset(
        "Yandex",
        "imap.yandex.com",
        993,
        "smtp.yandex.com",
        465,
        note="Enable IMAP and use an app password.",
    ),
    "icloud": ProviderPreset(
        "iCloud",
        "imap.mail.me.com",
        993,
        "smtp.mail.me.com",
        587,
        note="Requires an app-specific password.",
    ),
    "yahoo": ProviderPreset(
        "Yahoo",
        "imap.mail.yahoo.com",
        993,
        "smtp.mail.yahoo.com",
        465,
        note="Requires an app password.",
    ),
}

_DOMAIN_TO_SLUG: dict[str, str] = {
    "gmail.com": "gmail",
    "googlemail.com": "gmail",
    "outlook.com": "outlook",
    "hotmail.com": "outlook",
    "live.com": "outlook",
    "office365.com": "outlook",
    "mail.ru": "mailru",
    "inbox.ru": "mailru",
    "list.ru": "mailru",
    "bk.ru": "mailru",
    "internet.ru": "mailru",
    "yandex.ru": "yandex",
    "yandex.com": "yandex",
    "ya.ru": "yandex",
    "icloud.com": "icloud",
    "me.com": "icloud",
    "yahoo.com": "yahoo",
}


def preset_by_slug(slug: str) -> ProviderPreset | None:
    """Look up a preset by its slug (e.g. ``"gmail"``)."""
    return PRESETS.get(slug.lower().strip())


def slug_for_email(email: str) -> str | None:
    """Return the provider slug (gmail/outlook/mailru/...) for an address, or None."""
    _, _, domain = email.partition("@")
    return _DOMAIN_TO_SLUG.get(domain.lower().strip())


def preset_for_email(email: str) -> ProviderPreset | None:
    """Guess the provider from an email address' domain, or None if unknown."""
    _, _, domain = email.partition("@")
    slug = _DOMAIN_TO_SLUG.get(domain.lower().strip())
    return PRESETS.get(slug) if slug else None
