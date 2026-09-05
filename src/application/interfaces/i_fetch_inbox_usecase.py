from abc import ABC, abstractmethod

from src.entities.message.models import MessageDTO


class IFetchInboxUseCase(ABC):
    @abstractmethod
    async def __call__(
        self,
        account_name: str,
        folder: str = "inbox",
        limit: int = 20,
    ) -> list[MessageDTO]: ...
