from abc import ABC, abstractmethod

from src.application.dto.outgoing_message_dto import OutgoingMessageDTO
from src.entities.account.models import MailAccountDTO
from src.entities.message.models import MessageDTO


class IMailAdapter(ABC):
    """Interface for talking to one mailbox over IMAP (read) and SMTP (send)."""

    @abstractmethod
    async def fetch_folder(
        self,
        account: MailAccountDTO,
        folder: str = "inbox",
        limit: int = 20,
    ) -> list[MessageDTO]: ...

    @abstractmethod
    async def list_folders(
        self,
        account: MailAccountDTO,
    ) -> list[str]: ...

    @abstractmethod
    async def send(
        self,
        account: MailAccountDTO,
        message: OutgoingMessageDTO,
    ) -> None: ...
