from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    nullslast,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import URL
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
)

from src.adapter.mail.secure_file import restrict
from src.application.mail.dto.message_dto import MessageDTO
from src.application.mail.interfaces.i_message_store import IMessageStore

# pysqlite gives up after 5 seconds by default; the GUI fetches several
# mailboxes on background threads at once, so allow for a slower writer.
_BUSY_TIMEOUT = 30


class _Base(DeclarativeBase):
    pass


class _MessageColumns:
    """
    The stored shape of a message.

    Shared by the folder history and the favorites table: a favorite has to
    survive the message disappearing from its folder, so it keeps its own full
    copy of the row rather than a reference into ``messages``.
    """

    account: Mapped[str] = mapped_column(String, primary_key=True)
    folder: Mapped[str] = mapped_column(String, primary_key=True)
    uid: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str | None] = mapped_column(Text)
    sender: Mapped[str | None] = mapped_column(Text)
    recipients: Mapped[str | None] = mapped_column(Text)
    date_iso: Mapped[str | None] = mapped_column(String)
    date_epoch: Mapped[float | None] = mapped_column(Float)
    preview: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    seen: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[str] = mapped_column(String, nullable=False)


class _Message(_MessageColumns, _Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_folder", "folder", "date_epoch"),)


class _Favorite(_MessageColumns, _Base):
    __tablename__ = "favorites"


class _ReadOverride(_Base):
    """A local read/unread decision that overrides the server's own flag."""

    __tablename__ = "read_overrides"

    account: Mapped[str] = mapped_column(String, primary_key=True)
    folder: Mapped[str] = mapped_column(String, primary_key=True)
    uid: Mapped[str] = mapped_column(String, primary_key=True)
    is_read: Mapped[int] = mapped_column(Integer, nullable=False)


class _SpamSender(_Base):
    __tablename__ = "spam_senders"

    sender: Mapped[str] = mapped_column(String, primary_key=True)


# Fields a re-fetch is allowed to refresh on an existing row. fetched_at is not
# among them: it records when the message was first seen locally.
_MESSAGE_FIELDS = (
    "subject",
    "sender",
    "recipients",
    "date_iso",
    "date_epoch",
    "preview",
    "body_text",
    "body_html",
    "seen",
)
_KEY_FIELDS = ("account", "folder", "uid")


class SqliteMessageStore(IMessageStore):
    """
    SQLite-backed message history, mapped with SQLAlchemy. One row per
    (account, folder, uid).

    Every method opens a short-lived session and commits before returning, so
    no transaction stays open across the network calls the GUI worker threads
    make in parallel.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            URL.create("sqlite+pysqlite", database=str(self._path)),
            connect_args={
                # Sessions are short-lived, but the pool may hand a connection
                # to a different worker thread than the one that opened it.
                "check_same_thread": False,
                "timeout": _BUSY_TIMEOUT,
            },
        )
        _Base.metadata.create_all(self._engine)
        # The history holds full message bodies; under the default POSIX umask
        # the driver would otherwise create the file world-readable.
        restrict(self._path)
        self._session = sessionmaker(self._engine, expire_on_commit=False)

    def upsert_many(self, messages: list[MessageDTO]) -> None:
        if not messages:
            return
        now = datetime.now().isoformat()
        rows = [self._to_row(m, now) for m in messages]
        statement = sqlite_insert(_Message)
        statement = statement.on_conflict_do_update(
            index_elements=list(_KEY_FIELDS),
            set_={f: getattr(statement.excluded, f) for f in _MESSAGE_FIELDS},
        )
        with self._session.begin() as session:
            session.execute(statement, rows)

    def list(self, folder: str) -> list[MessageDTO]:
        with self._session() as session:
            rows = session.scalars(
                select(_Message)
                .where(_Message.folder == folder)
                .order_by(nullslast(_Message.date_epoch.desc()))
            ).all()
            return [self._to_dto(row) for row in rows]

    def get(self, account: str, folder: str, uid: str) -> MessageDTO | None:
        with self._session() as session:
            row = session.get(_Message, (account, folder, uid))
            return self._to_dto(row) if row else None

    # -- favorites (separate table) -----------------------------------

    def add_favorite(self, message: MessageDTO) -> None:
        row = self._to_row(message, datetime.now().isoformat())
        statement = sqlite_insert(_Favorite).values(row)
        statement = statement.on_conflict_do_update(
            index_elements=list(_KEY_FIELDS),
            set_={k: v for k, v in row.items() if k not in _KEY_FIELDS},
        )
        with self._session.begin() as session:
            session.execute(statement)

    def remove_favorite(self, account: str, folder: str, uid: str) -> None:
        with self._session.begin() as session:
            session.execute(
                delete(_Favorite).where(
                    _Favorite.account == account,
                    _Favorite.folder == folder,
                    _Favorite.uid == uid,
                )
            )

    def list_favorites(self) -> list[MessageDTO]:
        with self._session() as session:
            rows = session.scalars(
                select(_Favorite).order_by(nullslast(_Favorite.date_epoch.desc()))
            ).all()
            return [self._to_dto(row) for row in rows]

    def favorite_keys(self) -> set[tuple[str, str, str]]:
        with self._session() as session:
            rows = session.execute(
                select(_Favorite.account, _Favorite.folder, _Favorite.uid)
            ).all()
            return {(r.account, r.folder, r.uid) for r in rows}

    # -- local read/unread state --------------------------------------

    def set_read(self, account: str, folder: str, uid: str, is_read: bool) -> None:
        statement = sqlite_insert(_ReadOverride).values(
            account=account, folder=folder, uid=uid, is_read=int(is_read)
        )
        statement = statement.on_conflict_do_update(
            index_elements=list(_KEY_FIELDS),
            set_={"is_read": statement.excluded.is_read},
        )
        with self._session.begin() as session:
            session.execute(statement)

    def read_overrides(self) -> dict[tuple[str, str, str], bool]:
        with self._session() as session:
            rows = session.execute(
                select(
                    _ReadOverride.account,
                    _ReadOverride.folder,
                    _ReadOverride.uid,
                    _ReadOverride.is_read,
                )
            ).all()
            return {(r.account, r.folder, r.uid): bool(r.is_read) for r in rows}

    # -- local spam sender blocklist ----------------------------------

    def add_spam_sender(self, sender: str) -> None:
        statement = (
            sqlite_insert(_SpamSender)
            .values(sender=sender.lower())
            .on_conflict_do_nothing(index_elements=["sender"])
        )
        with self._session.begin() as session:
            session.execute(statement)

    def remove_spam_sender(self, sender: str) -> None:
        with self._session.begin() as session:
            session.execute(
                delete(_SpamSender).where(_SpamSender.sender == sender.lower())
            )

    def spam_senders(self) -> set[str]:
        with self._session() as session:
            return set(session.scalars(select(_SpamSender.sender)).all())

    def list_all(self) -> list[MessageDTO]:
        """Every stored message across folders, newest first."""
        with self._session() as session:
            rows = session.scalars(
                select(_Message).order_by(nullslast(_Message.date_epoch.desc()))
            ).all()
            return [self._to_dto(row) for row in rows]

    # ------------------------------------------------------------------

    @staticmethod
    def _to_row(m: MessageDTO, now: str) -> dict[str, object]:
        return {
            "account": m.account,
            "folder": m.folder,
            "uid": m.uid,
            "subject": m.subject,
            "sender": m.sender,
            "recipients": m.recipients,
            "date_iso": m.date.isoformat() if m.date else None,
            "date_epoch": m.date.timestamp() if m.date else None,
            "preview": m.preview,
            "body_text": m.body_text,
            "body_html": m.body_html,
            "seen": int(m.seen),
            "fetched_at": now,
        }

    @staticmethod
    def _to_dto(row: _MessageColumns) -> MessageDTO:
        return MessageDTO(
            account=row.account,
            uid=row.uid,
            subject=row.subject or "",
            sender=row.sender or "",
            date=datetime.fromisoformat(row.date_iso) if row.date_iso else None,
            preview=row.preview or "",
            seen=bool(row.seen),
            folder=row.folder,
            recipients=row.recipients or "",
            body_text=row.body_text,
            body_html=row.body_html,
        )
