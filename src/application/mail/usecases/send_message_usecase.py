from src.application.mail.dto.outgoing_message_dto import OutgoingMessageDTO
from src.application.mail.exceptions import AccountNotFoundError
from src.application.mail.interfaces.i_account_repository import IAccountRepository
from src.application.mail.interfaces.i_mail_adapter import IMailAdapter
from src.application.mail.interfaces.i_send_message_usecase import ISendMessageUseCase


class SendMessageUseCase(ISendMessageUseCase):
    """Send a message through the account named on the message."""

    def __init__(
        self,
        adapter: IMailAdapter,
        repository: IAccountRepository,
    ) -> None:
        self._adapter = adapter
        self._repository = repository

    async def __call__(self, message: OutgoingMessageDTO) -> None:
        account = self._repository.get(message.account)
        if account is None:
            raise AccountNotFoundError(f"Unknown account: {message.account!r}")

        await self._adapter.send(account, message)
