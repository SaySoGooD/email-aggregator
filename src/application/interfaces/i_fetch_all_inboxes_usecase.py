from abc import ABC, abstractmethod

from src.entities.message.models import MessageDTO


class IFetchAllInboxesUseCase(ABC):
    """Aggregate the inboxes of every configured account into one merged list."""

    @abstractmethod
    async def __call__(
        self,
        limit_per_account: int = 20,
        folder: str = "inbox",
    ) -> list[MessageDTO]: ...
