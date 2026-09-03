from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

from src.adapter.mail.provider_presets import preset_for_email, slug_for_email
from src.application.mail.dto.account_dto import MailAccountDTO
from src.application.mail.dto.display_settings_dto import DisplaySettingsDTO
from src.application.mail.dto.message_dto import MessageDTO
from src.application.mail.dto.outgoing_message_dto import OutgoingMessageDTO
from src.application.mail.usecases.fetch_all_inboxes_usecase import (
    FetchAllInboxesUseCase,
)
from src.main.dependency_injection import Container

# Default OAuth client id (Thunderbird's public app) so users need not register
# their own Azure app.
_DEFAULT_CLIENT_ID = {
    "microsoft": "9e5f94bc-e8a4-4e73-b8be-63364c29d753",
}

FOLDERS = ("inbox", "sent", "spam")


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _addr(sender: str) -> str:
    """The bare lowercase email address from a From header."""
    return parseaddr(sender)[1].lower()


class MailService:
    """
    Synchronous facade the Qt frontend calls off the GUI thread.

    It adapts the async use cases into JSON-friendly dicts and adds the two
    things a desktop client needs on top of the domain: a local message history
    (so folders keep their contents between runs and bodies open instantly) and
    user display/filter settings.
    """

    def __init__(self, di: Container) -> None:
        self._di = di
        self._repo = di.account_repository()
        self._store = di.message_store()
        self._settings_repo = di.display_settings_repository()
        self._oauth: dict[str, Any] = {"status": "idle"}

    # -- accounts ------------------------------------------------------

    def accounts(self) -> list[dict[str, Any]]:
        return [
            {"name": a.name, "email": a.email, "auth": a.auth}
            for a in self._repo.list()
        ]

    def provider(self, email: str) -> dict[str, Any] | None:
        preset = preset_for_email(email)
        if preset is None:
            return None
        return {
            "name": preset.name,
            "imap_host": preset.imap_host,
            "imap_port": preset.imap_port,
            "smtp_host": preset.smtp_host,
            "smtp_port": preset.smtp_port,
            "auth": preset.auth,
            "oauth_provider": preset.oauth_provider,
            "note": preset.note,
            "default_client_id": _DEFAULT_CLIENT_ID.get(preset.oauth_provider or "", ""),
        }

    def add_account(self, data: dict[str, Any]) -> None:
        email = data["email"].strip()
        account = MailAccountDTO(
            name=data["name"].strip(),
            email=email,
            username=data["username"].strip() or email,  # never leave login blank
            password=data.get("password", ""),
            imap_host=data["imap_host"].strip(),
            imap_port=int(data["imap_port"]),
            smtp_host=data["smtp_host"].strip(),
            smtp_port=int(data["smtp_port"]),
            auth=data.get("auth", "password"),
            oauth_provider=data.get("oauth_provider") or None,
            client_id=data.get("client_id") or None,
            refresh_token=data.get("refresh_token") or None,
        )
        self._repo.add(account)

    def remove_account(self, name: str) -> None:
        self._repo.remove(name)

    # -- settings ------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        return self._settings_repo.load().to_dict()

    def save_settings(self, data: dict[str, Any]) -> None:
        self._settings_repo.save(DisplaySettingsDTO.from_dict(data))

    # -- mail ----------------------------------------------------------

    def cached(self, folder: str = "inbox") -> dict[str, Any]:
        """Instant, network-free view of a folder from the local history."""
        blocked = self._store.spam_senders()
        if folder == "starred":
            source = self._store.list_favorites()
        elif folder == "spam":
            # Server Junk plus everything locally blocked by sender.
            source = list(self._store.list("spam"))
            seen = {(m.account, m.folder, m.uid) for m in source}
            for m in self._store.list_all():
                if _addr(m.sender) in blocked and (m.account, m.folder, m.uid) not in seen:
                    source.append(m)
        else:
            # Blocked senders are hidden from inbox/sent (they live in Spam now).
            source = [m for m in self._store.list(folder) if _addr(m.sender) not in blocked]
        return {"messages": self._to_dicts(source), "errors": {}}

    def toggle_spam_sender(self, sender: str) -> bool:
        """Block/unblock a sender; returns the new blocked state."""
        addr = _addr(sender)
        if addr in self._store.spam_senders():
            self._store.remove_spam_sender(addr)
            return False
        self._store.add_spam_sender(addr)
        return True

    def toggle_favorite(self, account: str, folder: str, uid: str) -> bool:
        """Star/unstar a message; returns the new starred state."""
        if (account, folder, uid) in self._store.favorite_keys():
            self._store.remove_favorite(account, folder, uid)
            return False
        message = self._store.get(account, folder, uid)
        if message is not None:
            self._store.add_favorite(message)
        return True

    def folder(self, folder: str = "inbox") -> dict[str, Any]:
        """Refresh a folder across all accounts, fold into local history, return it."""
        # Starred is a purely local view — no server round-trip.
        if folder == "starred":
            return self.cached("starred")

        settings = self._settings_repo.load()
        usecase: FetchAllInboxesUseCase = self._di.fetch_all_inboxes_usecase()
        fresh = _run(
            usecase(limit_per_account=settings.limit_per_account, folder=folder)
        )
        self._store.upsert_many(fresh)

        # Reuse cached() so blocked-sender routing stays consistent.
        result = self.cached(folder)
        result["errors"] = usecase.errors
        return result

    def poll_new(self) -> list[dict[str, Any]]:
        """Sync the inbox and return only messages that just arrived (for alerts)."""
        settings = self._settings_repo.load()
        before = {(m.account, m.folder, m.uid) for m in self._store.list("inbox")}
        usecase = self._di.fetch_all_inboxes_usecase()
        fresh = _run(
            usecase(limit_per_account=settings.limit_per_account, folder="inbox")
        )
        self._store.upsert_many(fresh)
        blocked = self._store.spam_senders()
        new = [
            m
            for m in fresh
            if (m.account, m.folder, m.uid) not in before
            and _addr(m.sender) not in blocked
        ]
        return self._to_dicts(new)

    def message(self, account: str, folder: str, uid: str) -> dict[str, Any] | None:
        stored = self._store.get(account, folder, uid)
        if stored is None:
            return None
        # Opening a message marks it read locally.
        self._store.set_read(account, folder, uid, True)
        data = self._msg(stored, full=True)
        data["provider"] = self._account_brands().get(stored.account, "other")
        data["starred"] = (account, folder, uid) in self._store.favorite_keys()
        data["seen"] = True
        return data

    def _to_dicts(self, rows: list[MessageDTO]) -> list[dict[str, Any]]:
        """Serialize messages, tagging provider, star state and local read state."""
        brands = self._account_brands()
        favs = self._store.favorite_keys()
        reads = self._store.read_overrides()
        blocked = self._store.spam_senders()
        result = []
        for m in rows:
            key = (m.account, m.folder, m.uid)
            data = self._msg(m)
            data["provider"] = brands.get(m.account, "other")
            data["starred"] = key in favs
            data["seen"] = reads.get(key, m.seen)  # local override wins
            data["spam_sender"] = _addr(m.sender) in blocked
            result.append(data)
        return result

    def mark_messages(
        self, keys: list[tuple[str, str, str]], is_read: bool
    ) -> None:
        for account, folder, uid in keys:
            self._store.set_read(account, folder, uid, is_read)

    def _account_brands(self) -> dict[str, str]:
        return {
            a.name: (slug_for_email(a.email) or "other") for a in self._repo.list()
        }

    def send(self, data: dict[str, Any]) -> None:
        message = OutgoingMessageDTO(
            account=data["account"],
            to=[a.strip() for a in data.get("to", []) if a.strip()],
            cc=[a.strip() for a in data.get("cc", []) if a.strip()],
            subject=data.get("subject", ""),
            body=data.get("body", ""),
        )
        _run(self._di.send_message_usecase()(message))

    @staticmethod
    def _msg(m: MessageDTO, full: bool = False) -> dict[str, Any]:
        name, addr = parseaddr(m.sender)
        display = name or addr or m.sender
        if len(display) > 20:  # 20 chars, then an ellipsis
            display = display[:20] + "…"
        data = {
            "account": m.account,
            "uid": m.uid,
            "subject": m.subject,
            "sender": m.sender,
            "from": display,  # display name, else the email — capped at 20 chars
            "recipients": m.recipients,
            "date": m.short_date(),
            "when": MailService._gmail_when(m.date),
            "preview": m.preview,
            "seen": m.seen,
            "folder": m.folder,
        }
        if full:
            data["body_text"] = m.body_text
            data["body_html"] = m.body_html
        return data

    @staticmethod
    def _gmail_when(dt: datetime | None) -> str:
        """Gmail-style: time for today, 'Mon DD' this year, else MM/DD/YY.

        Compared in the *local* timezone: the message time is converted to local
        so a message is "today" only when it falls on today's local date, not on
        today's date in the message's own (often UTC) timezone.
        """
        if dt is None:
            return "—"
        if dt.tzinfo is not None:
            dt = dt.astimezone()  # convert to local time
            now = datetime.now(timezone.utc).astimezone()
        else:
            now = datetime.now()  # naive dt assumed local already
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        if dt.year == now.year:
            return dt.strftime("%b %d")
        return dt.strftime("%m/%d/%y")

    # -- OAuth device flow --------------------------------------------

    def oauth_start(self, provider: str, client_id: str) -> dict[str, Any]:
        """Kick off the device-code flow; return the URL + code to display."""
        self._oauth = {"status": "pending", "uri": None, "code": None, "error": None}
        token_provider = self._di.oauth_token_provider()

        def on_prompt(uri: str, code: str) -> None:
            self._oauth["uri"] = uri
            self._oauth["code"] = code

        def worker() -> None:
            try:
                refresh = token_provider.acquire_refresh_token(
                    provider, client_id, on_prompt
                )
                self._oauth["refresh"] = refresh
                self._oauth["status"] = "done"
            except Exception as exc:
                self._oauth["error"] = str(exc)
                self._oauth["status"] = "error"

        threading.Thread(target=worker, daemon=True).start()

        for _ in range(100):
            if self._oauth["uri"] or self._oauth["status"] == "error":
                break
            time.sleep(0.1)
        return {
            "status": self._oauth["status"],
            "uri": self._oauth["uri"],
            "code": self._oauth["code"],
            "error": self._oauth["error"],
        }

    def oauth_poll(self) -> dict[str, Any]:
        return {"status": self._oauth["status"], "error": self._oauth.get("error")}

    def oauth_refresh_token(self) -> str | None:
        return self._oauth.get("refresh")
