from src.application.mail.dto.message_dto import MessageDTO
from src.application.mail.exceptions import AccountNotFoundError
from src.application.mail.interfaces.i_account_repository import IAccountRepository
from src.application.mail.interfaces.i_fetch_inbox_usecase import IFetchInboxUseCase
from src.application.mail.interfaces.i_mail_adapter import IMailAdapter


class FetchInboxUseCase(IFetchInboxUseCase):
    """Fetch the inbox of a single named account."""

    def __init__(
        self,
        adapter: IMailAdapter,
        repository: IAccountRepository,
    ) -> None:
        self._adapter = adapter
        self._repository = repository

    async def __call__(
        self,
        account_name: str,
        folder: str = "inbox",
        limit: int = 20,
    ) -> list[MessageDTO]:
        account = self._repository.get(account_name)
        if account is None:
            raise AccountNotFoundError(f"Unknown account: {account_name!r}")

        return await self._adapter.fetch_folder(account, folder=folder, limit=limit)
