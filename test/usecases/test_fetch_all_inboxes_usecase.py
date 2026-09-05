from datetime import datetime, timezone

import pytest

from src.application.exceptions import MailAuthError
from src.application.interfaces.i_account_repository import IAccountRepository
from src.application.interfaces.i_mail_adapter import IMailAdapter
from src.application.usecases.fetch_all_inboxes_usecase import (
    FetchAllInboxesUseCase,
)
from src.entities.account.models import MailAccountDTO
from src.entities.message.models import MessageDTO


def _account(name: str) -> MailAccountDTO:
    return MailAccountDTO(
        name=name,
        email=f"{name}@example.com",
        username=name,
        password="x",
        imap_host="imap",
        imap_port=993,
        smtp_host="smtp",
        smtp_port=465,
    )


def _msg(account: str, minute: int) -> MessageDTO:
    return MessageDTO(
        account=account,
        uid=str(minute),
        subject=f"subj-{minute}",
        sender="a@b.c",
        date=datetime(2026, 1, 1, 12, minute, tzinfo=timezone.utc),
        preview="",
        seen=False,
    )


class FakeRepo(IAccountRepository):
    def __init__(self, accounts):
        self._accounts = accounts

    def list(self):
        return self._accounts

    def get(self, name):
        return next((a for a in self._accounts if a.name == name), None)

    def add(self, account):  # pragma: no cover - unused
        self._accounts.append(account)

    def remove(self, name):  # pragma: no cover - unused
        self._accounts = [a for a in self._accounts if a.name != name]


class FakeAdapter(IMailAdapter):
    def __init__(self, by_account, failing=frozenset()):
        self._by_account = by_account
        self._failing = failing

    async def fetch_folder(self, account, folder="inbox", limit=20):
        if account.name in self._failing:
            raise MailAuthError(f"bad login for {account.name}")
        return self._by_account.get(account.name, [])

    async def list_folders(self, account):  # pragma: no cover - unused
        return ["INBOX"]

    async def send(self, account, message):  # pragma: no cover - unused
        ...


async def test_merges_and_sorts_newest_first():
    accounts = [_account("A"), _account("B")]
    adapter = FakeAdapter(
        {
            "A": [_msg("A", 10), _msg("A", 30)],
            "B": [_msg("B", 20)],
        }
    )
    usecase = FetchAllInboxesUseCase(adapter, FakeRepo(accounts))

    result = await usecase()

    assert [m.uid for m in result] == ["30", "20", "10"]
    assert usecase.errors == {}


async def test_one_failing_account_does_not_sink_the_others():
    accounts = [_account("A"), _account("B")]
    adapter = FakeAdapter({"A": [_msg("A", 10)]}, failing={"B"})
    usecase = FetchAllInboxesUseCase(adapter, FakeRepo(accounts))

    result = await usecase()

    assert [m.uid for m in result] == ["10"]
    assert "B" in usecase.errors


async def test_no_accounts_returns_empty():
    usecase = FetchAllInboxesUseCase(FakeAdapter({}), FakeRepo([]))
    assert await usecase() == []


async def test_mixes_naive_and_aware_dates_without_crashing():
    naive = _msg("A", 5)
    naive.date = datetime(2026, 1, 1, 12, 5)  # no tzinfo, as some Date headers
    aware = _msg("B", 40)  # tz-aware
    adapter = FakeAdapter({"A": [naive], "B": [aware]})
    usecase = FetchAllInboxesUseCase(adapter, FakeRepo([_account("A"), _account("B")]))

    result = await usecase()

    assert [m.uid for m in result] == ["40", "5"]
