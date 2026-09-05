from abc import ABC, abstractmethod

from src.entities.message.models import MessageDTO


class IMessageStore(ABC):
    """Local persistence of fetched messages."""

    @abstractmethod
    def upsert_many(self, messages: list[MessageDTO]) -> None: ...

    @abstractmethod
    def list(self, folder: str) -> list[MessageDTO]:
        """All stored messages for a logical folder, newest first."""
        ...

    @abstractmethod
    def get(self, account: str, folder: str, uid: str) -> MessageDTO | None: ...

    @abstractmethod
    def add_favorite(self, message: MessageDTO) -> None: ...

    @abstractmethod
    def remove_favorite(self, account: str, folder: str, uid: str) -> None: ...

    @abstractmethod
    def list_favorites(self) -> list[MessageDTO]: ...

    @abstractmethod
    def favorite_keys(self) -> set[tuple[str, str, str]]: ...

    @abstractmethod
    def set_read(self, account: str, folder: str, uid: str, is_read: bool) -> None: ...

    @abstractmethod
    def read_overrides(self) -> dict[tuple[str, str, str], bool]: ...

    @abstractmethod
    def add_spam_sender(self, sender: str) -> None: ...

    @abstractmethod
    def remove_spam_sender(self, sender: str) -> None: ...

    @abstractmethod
    def spam_senders(self) -> set[str]: ...

    @abstractmethod
    def list_all(self) -> list[MessageDTO]: ...
