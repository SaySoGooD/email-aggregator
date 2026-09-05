from __future__ import annotations

import asyncio
import imaplib
import re
import smtplib
import ssl
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr

from src.adapter.imap.imap_wire import (
    clean_credential,
    quote_mailbox,
    resolve_login_user,
)
from src.application.dto.outgoing_message_dto import OutgoingMessageDTO
from src.application.exceptions import (
    MailAuthError,
    MailConnectionError,
    MailFetchError,
    MailSendError,
    OAuthError,
)
from src.application.interfaces.i_mail_adapter import IMailAdapter
from src.application.interfaces.i_oauth_token_provider import IOAuthTokenProvider
from src.entities.account.models import MailAccountDTO
from src.entities.message.models import MessageDTO

_PREVIEW_LEN = 160
_TIMEOUT = 30

_WHITESPACE = re.compile(r"\s+")
_HTML_TAG = re.compile(r"<[^>]+>")

_SPECIAL_USE = {"sent": "\\sent", "spam": "\\junk"}
_NAME_HINTS = {
    "sent": ("sent", "отправленные", "отправл", "gesendet", "enviados"),
    "spam": ("junk", "spam", "спам", "нежелательная"),
}
_LIST_LINE = re.compile(rb'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$')


class ImapSmtpMailAdapter(IMailAdapter):
    """Provider-agnostic mailbox adapter over IMAP4 (read) and SMTP (send)."""

    def __init__(self, oauth: IOAuthTokenProvider | None = None) -> None:
        self._oauth = oauth

    async def fetch_folder(
        self,
        account: MailAccountDTO,
        folder: str = "inbox",
        limit: int = 20,
    ) -> list[MessageDTO]:
        try:
            return await asyncio.to_thread(
                self._fetch_folder_sync, account, folder, limit
            )
        except MailFetchError:
            await asyncio.sleep(0.6)
            return await asyncio.to_thread(
                self._fetch_folder_sync, account, folder, limit
            )

    async def list_folders(self, account: MailAccountDTO) -> list[str]:
        return await asyncio.to_thread(self._list_folders_sync, account)

    async def send(
        self,
        account: MailAccountDTO,
        message: OutgoingMessageDTO,
    ) -> None:
        await asyncio.to_thread(self._send_sync, account, message)

    def _imap_login(self, account: MailAccountDTO) -> imaplib.IMAP4_SSL:
        try:
            conn = imaplib.IMAP4_SSL(
                account.imap_host,
                account.imap_port,
                ssl_context=ssl.create_default_context(),
                timeout=_TIMEOUT,
            )
        except OSError as e:
            raise MailConnectionError(
                f"Cannot reach IMAP {account.imap_host}:{account.imap_port}: {e}"
            ) from e
        try:
            if account.auth == "oauth2":
                conn.authenticate("XOAUTH2", self._xoauth2_authobject(account))
            else:
                conn.login(resolve_login_user(account), clean_credential(account.password))
        except imaplib.IMAP4.error as e:
            raise MailAuthError(f"IMAP login failed for {account.email}: {e}") from e
        return conn

    def _xoauth2_authobject(self, account: MailAccountDTO):
        """SASL callback for imaplib.authenticate."""
        sent = False

        def authobject(challenge: bytes) -> bytes:
            nonlocal sent
            if sent or challenge:
                return b""
            sent = True
            return self._xoauth2(account)

        return authobject

    def _xoauth2(self, account: MailAccountDTO) -> bytes:
        """Build the XOAUTH2 SASL initial-response bytes for *account*."""
        if self._oauth is None:
            raise OAuthError("OAuth is not configured for this adapter.")
        if not account.oauth_provider or not account.client_id or not account.refresh_token:
            raise OAuthError(f"Account {account.name!r} is missing OAuth credentials.")
        token = self._oauth.access_token(
            account.oauth_provider, account.client_id, account.refresh_token
        )
        return f"user={account.email}\x01auth=Bearer {token}\x01\x01".encode()

    def _fetch_folder_sync(
        self,
        account: MailAccountDTO,
        folder: str,
        limit: int,
    ) -> list[MessageDTO]:
        conn = self._imap_login(account)
        try:
            real = self._resolve_folder(conn, folder)
            if real is None:
                return []

            status, _ = conn.select(quote_mailbox(real), readonly=True)
            if status != "OK":
                raise MailFetchError(f"Cannot open {folder!r} ({real}) for {account.email}")

            status, data = conn.uid("search", None, "ALL")
            if status != "OK" or not data or not data[0]:
                return []

            uids = data[0].split()
            chosen = uids[-limit:] if limit > 0 else uids

            messages: list[MessageDTO] = []
            for uid in reversed(chosen):
                messages.append(self._fetch_one(conn, account, folder, uid))
            return messages
        except imaplib.IMAP4.error as e:
            raise MailFetchError(f"IMAP error for {account.email}: {e}") from e
        finally:
            self._safe_logout(conn)

    def _fetch_one(
        self,
        conn: imaplib.IMAP4_SSL,
        account: MailAccountDTO,
        folder: str,
        uid: bytes,
    ) -> MessageDTO:
        status, msg_data = conn.uid("fetch", uid, "(FLAGS BODY.PEEK[])")
        if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
            raise MailFetchError(f"Failed to fetch UID {uid!r}")

        meta, raw = msg_data[0]
        seen = b"\\Seen" in bytes(meta)
        msg = message_from_bytes(raw, policy=policy.default)
        text, html = self._bodies(msg)

        return MessageDTO(
            account=account.name,
            uid=uid.decode(),
            subject=self._header(msg, "Subject") or "(no subject)",
            sender=self._header(msg, "From") or "(unknown sender)",
            date=getattr(msg["Date"], "datetime", None) if msg["Date"] else None,
            preview=self._preview_from(text, html),
            seen=seen,
            folder=folder,
            recipients=self._header(msg, "To"),
            body_text=text,
            body_html=html,
        )

    def _resolve_folder(self, conn: imaplib.IMAP4_SSL, folder: str) -> str | None:
        """Map a logical folder (inbox/sent/spam) to the server's real name."""
        if folder == "inbox":
            return "INBOX"

        status, data = conn.list()
        if status != "OK" or not data:
            return None

        special = _SPECIAL_USE.get(folder)
        hints = _NAME_HINTS.get(folder, ())
        by_name: str | None = None
        for line in data:
            if not line:
                continue
            match = _LIST_LINE.match(line if isinstance(line, bytes) else bytes(line))
            if not match:
                continue
            flags = match.group("flags").decode("utf-8", "replace").lower()
            name = match.group("name").decode("utf-8", "replace").strip().strip('"')
            if special and special in flags:
                return name
            if by_name is None and any(h in name.lower() for h in hints):
                by_name = name
        return by_name

    def _list_folders_sync(self, account: MailAccountDTO) -> list[str]:
        conn = self._imap_login(account)
        try:
            status, data = conn.list()
            if status != "OK" or not data:
                return []
            folders: list[str] = []
            for line in data:
                if line is None:
                    continue
                text = line.decode(errors="replace")
                match = re.search(r'"([^"]*)"\s*$', text)
                folders.append(match.group(1) if match else text.split()[-1])
            return folders
        finally:
            self._safe_logout(conn)

    @staticmethod
    def _safe_logout(conn: imaplib.IMAP4_SSL) -> None:
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass

    def _send_sync(
        self,
        account: MailAccountDTO,
        message: OutgoingMessageDTO,
    ) -> None:
        try:
            mail = EmailMessage()
            mail["From"] = formataddr((account.name, account.email))
            mail["To"] = ", ".join(message.to)
            if message.cc:
                mail["Cc"] = ", ".join(message.cc)
            mail["Subject"] = message.subject
            mail.set_content(message.body)
        except ValueError as e:
            raise MailSendError(f"Refusing to send a malformed message: {e}") from e

        try:
            with self._smtp_connect(account) as server:
                self._smtp_auth(server, account)
                server.send_message(mail)
        except smtplib.SMTPAuthenticationError as e:
            raise MailAuthError(f"SMTP login failed for {account.email}: {e}") from e
        except (smtplib.SMTPException, OSError) as e:
            raise MailSendError(f"Failed to send from {account.email}: {e}") from e

    def _smtp_auth(self, server: smtplib.SMTP, account: MailAccountDTO) -> None:
        if account.auth == "oauth2":
            server.ehlo()
            xoauth2 = self._xoauth2(account).decode()
            server.auth("XOAUTH2", lambda: xoauth2, initial_response_ok=True)
        else:
            server.login(resolve_login_user(account), clean_credential(account.password))

    def _smtp_connect(self, account: MailAccountDTO) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if account.smtp_port == 465:
            server = smtplib.SMTP_SSL(
                account.smtp_host, account.smtp_port, context=context, timeout=_TIMEOUT
            )
            server.ehlo()
            return server
        server = smtplib.SMTP(
            account.smtp_host, account.smtp_port, timeout=_TIMEOUT
        )
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        return server

    @staticmethod
    def _header(msg: EmailMessage, name: str) -> str:
        value = msg[name]
        return _WHITESPACE.sub(" ", str(value)).strip() if value else ""

    @staticmethod
    def _bodies(msg: EmailMessage) -> tuple[str | None, str | None]:
        """Extract the plain-text and HTML bodies, if present."""
        text: str | None = None
        html: str | None = None
        for part in msg.walk():
            if part.get_content_maintype() != "text" or part.is_multipart():
                continue
            subtype = part.get_content_subtype()
            if subtype not in ("plain", "html"):
                continue
            try:
                content = part.get_content()
            except (LookupError, ValueError):
                continue
            if subtype == "plain" and text is None:
                text = content
            elif subtype == "html" and html is None:
                html = content
        return text, html

    @staticmethod
    def _preview_from(text: str | None, html: str | None) -> str:
        content = text
        if content is None and html is not None:
            content = _HTML_TAG.sub(" ", html)
        if not content:
            return ""
        return _WHITESPACE.sub(" ", content).strip()[:_PREVIEW_LEN]
