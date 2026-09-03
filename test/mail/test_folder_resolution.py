from src.adapter.mail.imap_smtp_adapter import ImapSmtpMailAdapter


class FakeConn:
    def __init__(self, lines):
        self._lines = lines

    def list(self):
        return "OK", self._lines


def _adapter() -> ImapSmtpMailAdapter:
    return ImapSmtpMailAdapter()


def test_inbox_is_constant():
    assert _adapter()._resolve_folder(FakeConn([]), "inbox") == "INBOX"


def test_sent_by_special_use_flag():
    conn = FakeConn(
        [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
            b'(\\HasNoChildren \\Junk) "/" "Junk"',
        ]
    )
    assert _adapter()._resolve_folder(conn, "sent") == "Sent Items"
    assert _adapter()._resolve_folder(conn, "spam") == "Junk"


def test_sent_by_localized_name_when_no_flag():
    localized = '(\\HasNoChildren) "/" "Отправленные"'.encode("utf-8")
    conn = FakeConn([b'(\\HasNoChildren) "/" "INBOX"', localized])
    assert _adapter()._resolve_folder(conn, "sent") == "Отправленные"


def test_missing_folder_returns_none():
    conn = FakeConn([b'(\\HasNoChildren) "/" "INBOX"'])
    assert _adapter()._resolve_folder(conn, "spam") is None
