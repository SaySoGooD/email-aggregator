from abc import ABC, abstractmethod

from src.application.mail.dto.message_dto import MessageDTO


class IFetchInboxUseCase(ABC):
    @abstractmethod
    async def __call__(
        self,
        account_name: str,
        folder: str = "inbox",
        limit: int = 20,
    ) -> list[MessageDTO]: ...
