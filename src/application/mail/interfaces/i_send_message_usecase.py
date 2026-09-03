from abc import ABC, abstractmethod

from src.application.mail.dto.outgoing_message_dto import OutgoingMessageDTO


class ISendMessageUseCase(ABC):
    @abstractmethod
    async def __call__(
        self,
        message: OutgoingMessageDTO,
    ) -> None: ...
