from abc import ABC, abstractmethod

from src.application.mail.dto.account_dto import MailAccountDTO
from src.application.mail.dto.message_dto import MessageDTO
from src.application.mail.dto.outgoing_message_dto import OutgoingMessageDTO


class IMailAdapter(ABC):
    """
    Interface for talking to one mailbox over IMAP (read) and SMTP (send).

    Implementations must be provider-agnostic: everything specific to Gmail,
    Outlook, Mail.ru, ... is carried by the MailAccountDTO (hosts and ports).
    """

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
