import asyncio
from datetime import datetime, timezone

from src.application.exceptions import MailException
from src.application.interfaces.i_account_repository import IAccountRepository
from src.application.interfaces.i_fetch_all_inboxes_usecase import (
    IFetchAllInboxesUseCase,
)
from src.application.interfaces.i_mail_adapter import IMailAdapter
from src.entities.account.models import MailAccountDTO
from src.entities.message.models import MessageDTO


class FetchAllInboxesUseCase(IFetchAllInboxesUseCase):
    """Fetch every account concurrently and merge results newest-first."""

    def __init__(
        self,
        adapter: IMailAdapter,
        repository: IAccountRepository,
    ) -> None:
        self._adapter = adapter
        self._repository = repository
        self.errors: dict[str, str] = {}

    async def __call__(
        self,
        limit_per_account: int = 20,
        folder: str = "inbox",
    ) -> list[MessageDTO]:
        self.errors = {}
        accounts = self._repository.list()
        if not accounts:
            return []

        results = await asyncio.gather(
            *(
                self._safe_fetch(account, folder, limit_per_account)
                for account in accounts
            )
        )

        merged: list[MessageDTO] = [msg for batch in results for msg in batch]
        merged.sort(key=self._sort_key, reverse=True)
        return merged

    async def _safe_fetch(
        self,
        account: MailAccountDTO,
        folder: str,
        limit: int,
    ) -> list[MessageDTO]:
        try:
            return await self._adapter.fetch_folder(account, folder=folder, limit=limit)
        except MailException as e:
            self.errors[account.name] = str(e)
            return []

    @staticmethod
    def _sort_key(message: MessageDTO) -> datetime:
        dt = message.date
        if dt is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
