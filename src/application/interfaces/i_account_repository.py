from abc import ABC, abstractmethod

from src.entities.account.models import MailAccountDTO


class IAccountRepository(ABC):
    """Interface for persisting the user's mail accounts."""

    @abstractmethod
    def list(self) -> list[MailAccountDTO]: ...

    @abstractmethod
    def get(self, name: str) -> MailAccountDTO | None: ...

    @abstractmethod
    def add(self, account: MailAccountDTO) -> None: ...

    @abstractmethod
    def remove(self, name: str) -> None: ...
