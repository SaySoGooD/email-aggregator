from datetime import datetime, timezone

from src.adapter.mail.sqlite_message_store import SqliteMessageStore
from src.application.mail.dto.message_dto import MessageDTO


def _msg(uid: str, minute: int, folder: str = "inbox", seen: bool = False) -> MessageDTO:
    return MessageDTO(
        account="A",
        uid=uid,
        subject=f"subj-{uid}",
        sender="a@b.c",
        date=datetime(2026, 1, 1, 12, minute, tzinfo=timezone.utc),
        preview="hi",
        seen=seen,
        folder=folder,
        recipients="me@x",
        body_text="body",
        body_html="<b>body</b>",
    )


def test_upsert_and_list_newest_first(tmp_path):
    store = SqliteMessageStore(str(tmp_path / "m.db"))
    store.upsert_many([_msg("1", 10), _msg("2", 30), _msg("3", 20)])

    rows = store.list("inbox")
    assert [m.uid for m in rows] == ["2", "3", "1"]
    assert rows[0].body_html == "<b>body</b>"


def test_get_returns_full_body(tmp_path):
    store = SqliteMessageStore(str(tmp_path / "m.db"))
    store.upsert_many([_msg("1", 10)])
    got = store.get("A", "inbox", "1")
    assert got is not None
    assert got.body_text == "body"
    assert got.recipients == "me@x"


def test_history_persists_and_seen_updates(tmp_path):
    path = str(tmp_path / "m.db")
    SqliteMessageStore(path).upsert_many([_msg("1", 10, seen=False)])

    # Re-open (new run) and re-upsert the same UID as read: history kept, flag updated.
    store = SqliteMessageStore(path)
    store.upsert_many([_msg("1", 10, seen=True)])

    rows = store.list("inbox")
    assert len(rows) == 1
    assert rows[0].seen is True


def test_folders_are_isolated(tmp_path):
    store = SqliteMessageStore(str(tmp_path / "m.db"))
    store.upsert_many([_msg("1", 10, folder="inbox"), _msg("1", 10, folder="sent")])
    assert len(store.list("inbox")) == 1
    assert len(store.list("sent")) == 1


def test_favorites_add_list_remove(tmp_path):
    store = SqliteMessageStore(str(tmp_path / "m.db"))
    store.add_favorite(_msg("1", 10))
    store.add_favorite(_msg("2", 20))

    assert {m.uid for m in store.list_favorites()} == {"1", "2"}
    assert store.favorite_keys() == {("A", "inbox", "1"), ("A", "inbox", "2")}

    store.remove_favorite("A", "inbox", "1")
    assert {m.uid for m in store.list_favorites()} == {"2"}


def test_read_overrides(tmp_path):
    store = SqliteMessageStore(str(tmp_path / "m.db"))
    assert store.read_overrides() == {}
    store.set_read("A", "inbox", "1", True)
    store.set_read("A", "inbox", "2", False)
    assert store.read_overrides() == {
        ("A", "inbox", "1"): True,
        ("A", "inbox", "2"): False,
    }
    store.set_read("A", "inbox", "1", False)  # override flips
    assert store.read_overrides()[("A", "inbox", "1")] is False


def test_spam_senders(tmp_path):
    store = SqliteMessageStore(str(tmp_path / "m.db"))
    assert store.spam_senders() == set()
    store.add_spam_sender("Bad@X.com")  # stored lowercased
    store.add_spam_sender("bad@x.com")  # idempotent
    assert store.spam_senders() == {"bad@x.com"}
    store.remove_spam_sender("bad@x.com")
    assert store.spam_senders() == set()


def test_favorites_survive_message_history(tmp_path):
    # Favorites are a separate table, independent of the folder history.
    store = SqliteMessageStore(str(tmp_path / "m.db"))
    store.add_favorite(_msg("1", 10))
    assert store.list("inbox") == []  # never went into the messages table
    assert len(store.list_favorites()) == 1
