from abc import ABC, abstractmethod

from src.application.mail.dto.message_dto import MessageDTO


class IMessageStore(ABC):
    """
    Local persistence of fetched messages, so the app keeps a running history
    from the moment it is first used — messages stay readable even after the
    server drops them, and bodies open instantly without a re-fetch.
    """

    @abstractmethod
    def upsert_many(self, messages: list[MessageDTO]) -> None: ...

    @abstractmethod
    def list(self, folder: str) -> list[MessageDTO]:
        """All stored messages for a logical folder, newest first."""
        ...

    @abstractmethod
    def get(self, account: str, folder: str, uid: str) -> MessageDTO | None: ...

    # Favorites live in their own table, independent of folder history.

    @abstractmethod
    def add_favorite(self, message: MessageDTO) -> None: ...

    @abstractmethod
    def remove_favorite(self, account: str, folder: str, uid: str) -> None: ...

    @abstractmethod
    def list_favorites(self) -> list[MessageDTO]: ...

    @abstractmethod
    def favorite_keys(self) -> set[tuple[str, str, str]]: ...

    # Local read/unread state (independent of the server's \Seen flag).

    @abstractmethod
    def set_read(self, account: str, folder: str, uid: str, is_read: bool) -> None: ...

    @abstractmethod
    def read_overrides(self) -> dict[tuple[str, str, str], bool]: ...

    # Local spam sender blocklist (independent of any server-side filtering).

    @abstractmethod
    def add_spam_sender(self, sender: str) -> None: ...

    @abstractmethod
    def remove_spam_sender(self, sender: str) -> None: ...

    @abstractmethod
    def spam_senders(self) -> set[str]: ...

    @abstractmethod
    def list_all(self) -> list[MessageDTO]: ...
