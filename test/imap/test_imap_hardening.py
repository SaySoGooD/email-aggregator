import imaplib
import ssl

import pytest

from src.adapter.imap import imap_wire
from src.adapter.imap.imap_smtp_adapter import ImapSmtpMailAdapter
from src.adapter.imap.imap_wire import clean_credential, quote_mailbox
from src.application.exceptions import MailFetchError
from src.entities.account.models import MailAccountDTO


def _account() -> MailAccountDTO:
    return MailAccountDTO(
        name="Work",
        email="a@b.c",
        username="a@b.c",
        password="pw",
        imap_host="imap.x",
        imap_port=993,
        smtp_host="smtp.x",
        smtp_port=465,
    )


def test_imap_verifies_the_server_certificate(monkeypatch):
    # Without an explicit context imaplib falls back to a stdlib context that
    # verifies nothing, so any MITM could read the login off the wire.
    seen = {}

    class FakeImap:
        def __init__(self, host, port, ssl_context=None, timeout=None):
            seen["context"] = ssl_context

        def login(self, user, password):
            return "OK", []

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeImap)
    ImapSmtpMailAdapter()._imap_login(_account())

    context = seen["context"]
    assert context is not None
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_app_password_groups_are_joined():
    assert clean_credential("abcd efgh ijkl mnop") == "abcdefghijklmnop"


def test_interior_spaces_of_a_real_password_survive():
    # Joining every password would silently strip entropy and break logins.
    assert clean_credential("  correct horse battery staple  ") == "correct horse battery staple"


def test_control_characters_are_removed_from_passwords():
    # imaplib does not validate LOGIN arguments; a CR/LF would start a second
    # IMAP command.
    assert clean_credential("pw\r\nA001 DELETE INBOX") == "pwA001 DELETE INBOX"


def test_mailbox_names_are_escaped_not_interpolated():
    assert quote_mailbox("INBOX") == '"INBOX"'
    assert quote_mailbox('od"d') == '"od\\"d"'
    assert quote_mailbox("back\\slash") == '"back\\\\slash"'


def test_mailbox_name_with_crlf_is_refused():
    # The name comes from the server's own LIST reply, so a hostile server
    # controls it.
    with pytest.raises(MailFetchError):
        quote_mailbox("INBOX\r\nA001 LOGOUT")


def test_control_regex_covers_the_c0_range():
    assert imap_wire._CONTROL.search("\x00")
    assert imap_wire._CONTROL.search("\x1f")
    assert imap_wire._CONTROL.search("\x7f")
    assert not imap_wire._CONTROL.search("ordinary text")
