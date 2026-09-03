from __future__ import annotations

import asyncio
from getpass import getpass
from typing import Awaitable, Callable, TypeVar

from src.adapter.mail.provider_presets import PRESETS, preset_by_slug, preset_for_email
from src.application.mail.dto.account_dto import MailAccountDTO
from src.application.mail.dto.message_dto import MessageDTO
from src.application.mail.dto.outgoing_message_dto import OutgoingMessageDTO
from src.application.mail.exceptions import MailException
from src.application.mail.usecases.fetch_all_inboxes_usecase import (
    FetchAllInboxesUseCase,
)
from src.main.dependency_injection import Container, container

T = TypeVar("T")


def run_async(coro: Awaitable[T]) -> T:
    """Run one async use case from the synchronous menu loop."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Generic console menu  (SRP: owns loop + render only)
# ---------------------------------------------------------------------------

MenuItem = tuple[str, Callable[[], None]]


class Menu:
    """
    Reusable interactive console menu.

    Renders numbered items, reads one integer, dispatches to the matching
    action, and loops until the implicit "Back / Exit" option is chosen.
    Adding an item never requires editing this class (OCP): callers extend
    the *items* list.
    """

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


# ---------------------------------------------------------------------------
# Input helpers  (DRY: one place for each repeated input pattern)
# ---------------------------------------------------------------------------


def _prompt(prompt: str, default: str | None = None) -> str:
    """Read a string; return *default* if the user just hits enter."""
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def _prompt_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _prompt_list(prompt: str) -> list[str]:
    """Read a comma-separated list of addresses."""
    raw = input(f"{prompt}: ").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# MailApp  (SRP: wires use cases to console screens)
# ---------------------------------------------------------------------------


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

    # ------------------------------------------------------------------
    # Inbox screens
    # ------------------------------------------------------------------

    def _unified_inbox(self) -> None:
        if not self._require_accounts():
            return
        usecase: FetchAllInboxesUseCase = self._di.fetch_all_inboxes_usecase()
        print("\nFetching every account, please wait...")
        try:
            messages = run_async(usecase(limit_per_account=self._limit))
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
            messages = run_async(usecase(account.name, limit=self._limit))
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

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _send_message(self) -> None:
        account = self._pick_account()
        if account is None:
            return
        to = _prompt_list("To (comma-separated)")
        if not to:
            print("No recipients — cancelled.")
            return
        cc = _prompt_list("Cc (optional, comma-separated)")
        subject = _prompt("Subject")
        print("Body (finish with a single '.' on its own line):")
        body = self._read_body()

        message = OutgoingMessageDTO(
            account=account.name, to=to, cc=cc, subject=subject, body=body
        )
        try:
            run_async(self._di.send_message_usecase()(message))
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

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

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
        email = _prompt("Email address")
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
            imap_host = _prompt("IMAP host")
            imap_port = _prompt_int("IMAP port", 993)
            smtp_host = _prompt("SMTP host")
            smtp_port = _prompt_int("SMTP port (465=SSL, else STARTTLS)", 465)

        name = _prompt("Label for this account", email)
        username = _prompt("Login (username)", email)

        # Gather credentials: an OAuth2 device flow, or a plain password.
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
        """
        Run the device-code flow for *provider* and return (client_id, refresh).

        Returns (None, None) on failure so the caller can abort the add cleanly.
        """
        if provider == "microsoft":
            print(
                "\nOutlook needs OAuth2. Register a free app in Azure "
                "(Entra ID -> App registrations):\n"
                "  - Supported accounts: personal Microsoft accounts\n"
                "  - Authentication -> Allow public client flows: Yes\n"
                "Then paste its Application (client) ID below.\n"
            )
        client_id = _prompt("Client ID (app id)")
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

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        MailApp(container).run()
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")


if __name__ == "__main__":
    main()
