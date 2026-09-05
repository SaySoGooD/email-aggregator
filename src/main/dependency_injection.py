from dependency_injector import containers, providers

from src.adapter.database.sqlite_message_store import SqliteMessageStore
from src.adapter.imap.imap_smtp_adapter import ImapSmtpMailAdapter
from src.adapter.imap.oauth_token_provider import OAuthTokenProvider
from src.adapter.repository.encrypted_account_repository import (
    EncryptedAccountRepository,
)
from src.adapter.repository.json_display_settings_repository import (
    JsonDisplaySettingsRepository,
)
from src.application.interfaces.i_account_repository import IAccountRepository
from src.application.interfaces.i_display_settings_repository import (
    IDisplaySettingsRepository,
)
from src.application.interfaces.i_fetch_all_inboxes_usecase import (
    IFetchAllInboxesUseCase,
)
from src.application.interfaces.i_fetch_inbox_usecase import IFetchInboxUseCase
from src.application.interfaces.i_mail_adapter import IMailAdapter
from src.application.interfaces.i_message_store import IMessageStore
from src.application.interfaces.i_oauth_token_provider import IOAuthTokenProvider
from src.application.interfaces.i_send_message_usecase import ISendMessageUseCase
from src.application.usecases.fetch_all_inboxes_usecase import (
    FetchAllInboxesUseCase,
)
from src.application.usecases.fetch_inbox_usecase import FetchInboxUseCase
from src.application.usecases.send_message_usecase import SendMessageUseCase
from src.main.config import Config


class Container(containers.DeclarativeContainer):
    """Application dependency injection container."""

    config: providers.Singleton[Config] = providers.Singleton(Config)

    account_repository: providers.Singleton[IAccountRepository] = providers.Singleton(
        EncryptedAccountRepository,
        path=config.provided.ACCOUNTS_ENC,
        legacy_path=config.provided.ACCOUNTS_FILE,
    )

    message_store: providers.Singleton[IMessageStore] = providers.Singleton(
        SqliteMessageStore,
        path=config.provided.MESSAGES_DB,
    )

    display_settings_repository: providers.Singleton[IDisplaySettingsRepository] = (
        providers.Singleton(
            JsonDisplaySettingsRepository,
            path=config.provided.SETTINGS_FILE,
            default_limit=config.provided.DEFAULT_FETCH_LIMIT,
        )
    )

    oauth_token_provider: providers.Singleton[IOAuthTokenProvider] = (
        providers.Singleton(OAuthTokenProvider)
    )

    mail_adapter: providers.Singleton[IMailAdapter] = providers.Singleton(
        ImapSmtpMailAdapter,
        oauth=oauth_token_provider,
    )

    fetch_inbox_usecase: providers.Factory[IFetchInboxUseCase] = providers.Factory(
        FetchInboxUseCase,
        adapter=mail_adapter,
        repository=account_repository,
    )

    fetch_all_inboxes_usecase: providers.Factory[IFetchAllInboxesUseCase] = (
        providers.Factory(
            FetchAllInboxesUseCase,
            adapter=mail_adapter,
            repository=account_repository,
        )
    )

    send_message_usecase: providers.Factory[ISendMessageUseCase] = providers.Factory(
        SendMessageUseCase,
        adapter=mail_adapter,
        repository=account_repository,
    )


container = Container()
