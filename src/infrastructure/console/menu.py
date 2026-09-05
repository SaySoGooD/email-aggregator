from __future__ import annotations

import asyncio
from getpass import getpass
from typing import Callable

from src.adapter.imap.provider_presets import PRESETS, preset_by_slug, preset_for_email
from src.application.dto.outgoing_message_dto import OutgoingMessageDTO
from src.application.exceptions import MailException
from src.application.usecases.fetch_all_inboxes_usecase import (
    FetchAllInboxesUseCase,
)
from src.entities.account.models import MailAccountDTO
from src.entities.message.models import MessageDTO
from src.infrastructure.console.console_prompts import prompt, prompt_int, prompt_list
from src.main.dependency_injection import Container

MenuItem = tuple[str, Callable[[], None]]


class Menu:
    """Reusable interactive console menu."""

    def __init__(
        self,
        title: str,
        items: list[MenuItem],
        subtitle: Callable[[], str] | None = None,
        back_label: str = "Back",
    ) -> None:
        self._title = title
        self._items = items
        self._subtitle = subtitle
        self._back_label = back_label

    def run(self) -> None:
        while True:
            self._render()
            choice = self._read_int()
            if choice == len(self._items) + 1:
                break
            if 1 <= choice <= len(self._items):
                self._items[choice - 1][1]()

    def _render(self) -> None:
        print(f"\n{'=' * 40}\n  {self._title}")
        if self._subtitle:
            print(f"  {self._subtitle()}")
        print("=" * 40)
        for i, (label, _) in enumerate(self._items, 1):
            print(f"{i}. {label}")
        print(f"{len(self._items) + 1}. {self._back_label}\n")

    @staticmethod
    def _read_int() -> int:
        try:
            return int(input("> ").strip())
        except ValueError:
            return -1


class MailApp:
    """Top-level console application built from the DI container."""

    def __init__(self, di: Container) -> None:
        self._di = di
        self._repo = di.account_repository()
        self._limit = di.config().DEFAULT_FETCH_LIMIT

    def run(self) -> None:
        Menu(
            "EMAIL AGGREGATOR",
            [
                ("Unified inbox (all accounts)", self._unified_inbox),
                ("One account's inbox", self._single_inbox),
                ("Send a message", self._send_message),
                ("Accounts", self._accounts_menu),
            ],
            subtitle=lambda: f"{len(self._repo.list())} account(s) configured",
            back_label="Exit",
        ).run()

    def _unified_inbox(self) -> None:
        if not self._require_accounts():
            return
        usecase: FetchAllInboxesUseCase = self._di.fetch_all_inboxes_usecase()
        print("\nFetching every account, please wait...")
        try:
            messages = asyncio.run(usecase(limit_per_account=self._limit))
        except MailException as e:
            print(f"Error: {e}")
            return

        self._render_messages(messages, show_account=True)
        for name, error in usecase.errors.items():
            print(f"  ! {name}: {error}")

    def _single_inbox(self) -> None:
        account = self._pick_account()
        if account is None:
            return
        usecase = self._di.fetch_inbox_usecase()
        print(f"\nFetching {account.name}...")
        try:
            messages = asyncio.run(usecase(account.name, limit=self._limit))
        except MailException as e:
            print(f"Error: {e}")
            return
        self._render_messages(messages, show_account=False)

    @staticmethod
    def _render_messages(messages: list[MessageDTO], show_account: bool) -> None:
        if not messages:
            print("\n(no messages)")
            return
        print(f"\n{len(messages)} message(s):\n")
        for msg in messages:
            flag = " " if msg.seen else "*"
            origin = f"[{msg.account}] " if show_account else ""
            print(f"{flag} {msg.short_date()}  {origin}{msg.sender}")
            print(f"    {msg.subject}")
            if msg.preview:
                print(f"    {msg.preview}")
            print()

    def _send_message(self) -> None:
        account = self._pick_account()
        if account is None:
            return
        to = prompt_list("To (comma-separated)")
        if not to:
            print("No recipients — cancelled.")
            return
        cc = prompt_list("Cc (optional, comma-separated)")
        subject = prompt("Subject")
        print("Body (finish with a single '.' on its own line):")
        body = self._read_body()

        message = OutgoingMessageDTO(
            account=account.name, to=to, cc=cc, subject=subject, body=body
        )
        try:
            asyncio.run(self._di.send_message_usecase()(message))
        except MailException as e:
            print(f"Send failed: {e}")
            return
        print(f"Sent from {account.email} to {', '.join(to)}.")

    @staticmethod
    def _read_body() -> str:
        lines: list[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line == ".":
                break
            lines.append(line)
        return "\n".join(lines)

    def _accounts_menu(self) -> None:
        Menu(
            "ACCOUNTS",
            [
                ("List accounts", self._list_accounts),
                ("Add account", self._add_account),
                ("Remove account", self._remove_account),
            ],
            subtitle=lambda: f"{len(self._repo.list())} configured",
        ).run()

    def _list_accounts(self) -> None:
        accounts = self._repo.list()
        if not accounts:
            print("\n(no accounts yet)")
            return
        print()
        for account in accounts:
            print(f"  - {account.masked()}")

    def _add_account(self) -> None:
        email = prompt("Email address")
        if "@" not in email:
            print("Not a valid email — cancelled.")
            return

        preset = preset_for_email(email)
        if preset is None:
            print("Unknown provider. Choose one or enter servers manually:")
            preset = self._pick_preset()

        auth = "password"
        oauth_provider: str | None = None
        if preset is not None:
            print(f"Using preset: {preset.name}")
            if preset.note:
                print(f"  note: {preset.note}")
            imap_host, imap_port = preset.imap_host, preset.imap_port
            smtp_host, smtp_port = preset.smtp_host, preset.smtp_port
            auth, oauth_provider = preset.auth, preset.oauth_provider
        else:
            imap_host = prompt("IMAP host")
            imap_port = prompt_int("IMAP port", 993)
            smtp_host = prompt("SMTP host")
            smtp_port = prompt_int("SMTP port (465=SSL, else STARTTLS)", 465)

        name = prompt("Label for this account", email)
        username = prompt("Login (username)", email)

        password = ""
        client_id: str | None = None
        refresh_token: str | None = None
        if auth == "oauth2":
            client_id, refresh_token = self._oauth_login(oauth_provider)
            if refresh_token is None:
                return
        else:
            password = getpass("Password / app password (hidden): ")

        account = MailAccountDTO(
            name=name,
            email=email,
            username=username,
            password=password,
            imap_host=imap_host,
            imap_port=imap_port,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            auth=auth,
            oauth_provider=oauth_provider,
            client_id=client_id,
            refresh_token=refresh_token,
        )
        try:
            self._repo.add(account)
        except MailException as e:
            print(f"Could not add account: {e}")
            return
        print(f"Added {account.masked()}")

    def _oauth_login(
        self, provider: str | None
    ) -> tuple[str | None, str | None]:
        """Run the device-code flow for *provider*; (None, None) on failure."""
        if provider == "microsoft":
            print(
                "\nOutlook needs OAuth2. Register a free app in Azure "
                "(Entra ID -> App registrations):\n"
                "  - Supported accounts: personal Microsoft accounts\n"
                "  - Authentication -> Allow public client flows: Yes\n"
                "Then paste its Application (client) ID below.\n"
            )
        client_id = prompt("Client ID (app id)")
        if not client_id:
            print("No client id — cancelled.")
            return None, None

        def on_prompt(uri: str, code: str) -> None:
            print(f"\n  1. Open: {uri}\n  2. Enter code: {code}\n  Waiting...")

        try:
            refresh = self._di.oauth_token_provider().acquire_refresh_token(
                provider, client_id, on_prompt
            )
        except MailException as e:
            print(f"OAuth sign-in failed: {e}")
            return None, None
        print("Signed in.")
        return client_id, refresh

    def _pick_preset(self):
        slugs = list(PRESETS)
        for i, slug in enumerate(slugs, 1):
            print(f"  {i}. {PRESETS[slug].name}")
        print(f"  {len(slugs) + 1}. Enter manually")
        try:
            idx = int(input("> ").strip()) - 1
        except ValueError:
            return None
        if 0 <= idx < len(slugs):
            return preset_by_slug(slugs[idx])
        return None

    def _remove_account(self) -> None:
        account = self._pick_account()
        if account is None:
            return
        self._repo.remove(account.name)
        print(f"Removed {account.name}.")

    def _require_accounts(self) -> bool:
        if not self._repo.list():
            print("\nNo accounts configured yet — add one from the Accounts menu.")
            return False
        return True

    def _pick_account(self) -> MailAccountDTO | None:
        accounts = self._repo.list()
        if not accounts:
            print("\nNo accounts configured yet — add one from the Accounts menu.")
            return None
        print()
        for i, account in enumerate(accounts, 1):
            print(f"  {i}. {account.name} <{account.email}>")
        try:
            idx = int(input("> ").strip()) - 1
        except ValueError:
            return None
        return accounts[idx] if 0 <= idx < len(accounts) else None
