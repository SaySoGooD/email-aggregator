from src.adapter.imap.provider_presets import (
    PRESETS,
    preset_by_slug,
    preset_for_email,
)


def test_known_domains_resolve_to_a_preset():
    assert preset_for_email("someone@gmail.com").imap_host == "imap.gmail.com"
    assert preset_for_email("user@mail.ru").smtp_host == "smtp.mail.ru"
    assert preset_for_email("user@bk.ru").imap_host == "imap.mail.ru"
    assert preset_for_email("me@outlook.com").imap_host == "outlook.office365.com"


def test_domain_match_is_case_insensitive():
    assert preset_for_email("USER@GMAIL.COM") is preset_for_email("user@gmail.com")


def test_unknown_domain_returns_none():
    assert preset_for_email("admin@self-hosted.example") is None


def test_preset_by_slug():
    assert preset_by_slug("mailru").name == "Mail.ru"
    assert preset_by_slug("nope") is None


def test_ssl_ports_are_sane():
    for preset in PRESETS.values():
        assert preset.imap_port == 993
        assert preset.smtp_port in (465, 587)
