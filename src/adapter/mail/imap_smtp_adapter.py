from __future__ import annotations

import asyncio
import imaplib
import re
import smtplib
import ssl
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr

from src.application.mail.dto.account_dto import MailAccountDTO
from src.application.mail.dto.message_dto import MessageDTO
from src.application.mail.dto.outgoing_message_dto import OutgoingMessageDTO
from src.application.mail.exceptions import (
    MailAuthError,
    MailConnectionError,
    MailFetchError,
    MailSendError,
    OAuthError,
)
from src.application.mail.interfaces.i_mail_adapter import IMailAdapter
from src.application.mail.interfaces.i_oauth_token_provider import IOAuthTokenProvider

_PREVIEW_LEN = 160
_TIMEOUT = 30  # seconds; without it imaplib/smtplib block forever on a dead server


# Providers print app passwords as four groups of four letters; the groups are
# presentation only and are not part of the secret.
_APP_PASSWORD = re.compile(r"^(?:[a-z]{4}\s+){3}[a-z]{4}$", re.IGNORECASE)
# C0/C1 controls. Never legitimate in a credential or a mailbox name, and
# imaplib does not validate command arguments, so a CR/LF slipping through
# would splice a second IMAP command into the session.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value: str) -> str:
    """
    Normalise a password for the wire.

    Only the two transformations that are always safe: control characters are
    removed (they cannot be transmitted and are an injection vector), and the
    surrounding whitespace a copy-paste picks up is trimmed. The four-group app
    password format providers display is joined, because there the spaces are
    known not to be part of the secret — every other password keeps its
    interior spaces, since stripping them silently destroys entropy and breaks
    logins that used to work.
    """
    value = _CONTROL.sub("", value).strip()
    if _APP_PASSWORD.match(value):
        return "".join(value.split())
    return value


def _quote_mailbox(name: str) -> str:
    """
    Quote a mailbox name for use as an IMAP command argument.

    The name arrives from the server's own LIST reply, so a hostile or
    compromised server controls it. Reject control characters and escape the
    two characters that are special inside an IMAP quoted string.
    """
    if _CONTROL.search(name):
        raise MailFetchError(f"Refusing mailbox name with control characters: {name!r}")
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _login_user(account: MailAccountDTO) -> str:
    """The login name; falls back to the email when username is blank (an empty
    user makes servers reject LOGIN with 'Not enough arguments')."""
    return account.username.strip() or account.email.strip()
_WHITESPACE = re.compile(r"\s+")
_HTML_TAG = re.compile(r"<[^>]+>")

# Logical folders the UI knows about, mapped to how they're found on the server.
# Special-use flags (RFC 6154) are tried first, then localized name heuristics.
_SPECIAL_USE = {"sent": "\\sent", "spam": "\\junk"}
_NAME_HINTS = {
    "sent": ("sent", "отправленные", "отправл", "gesendet", "enviados"),
    "spam": ("junk", "spam", "спам", "нежелательная"),
}
_LIST_LINE = re.compile(rb'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$')


class ImapSmtpMailAdapter(IMailAdapter):
    """
    Provider-agnostic mailbox adapter over IMAP4 (read) and SMTP (send).

    The public methods are async to fit the application's async use cases, but
    the underlying stdlib clients are blocking, so each call is dispatched to a
    worker thread. Connections are opened and closed per call — simple and
    stateless, which is fine for an interactive console tool.

    Accounts with ``auth == "oauth2"`` (e.g. Outlook, which disabled basic
    auth) authenticate with the XOAUTH2 SASL mechanism using a token minted by
    the injected ``IOAuthTokenProvider``; password accounts are unaffected.
    """

    def __init__(self, oauth: IOAuthTokenProvider | None = None) -> None:
        self._oauth = oauth

    async def fetch_folder(
        self,
        account: MailAccountDTO,
        folder: str = "inbox",
        limit: int = 20,
    ) -> list[MessageDTO]:
        # Gmail (and others) occasionally answer a UID command with a transient
        # "System Error"; retry once on a fresh connection before giving up.
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

    # ------------------------------------------------------------------
    # IMAP (blocking)
    # ------------------------------------------------------------------

    def _imap_login(self, account: MailAccountDTO) -> imaplib.IMAP4_SSL:
        try:
            # Without an explicit context imaplib falls back to
            # ssl._create_stdlib_context(), which verifies neither the
            # certificate chain nor the hostname — any MITM would then read the
            # LOGIN password or the OAuth bearer token in the clear.
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
                conn.login(_login_user(account), _clean(account.password))
        except imaplib.IMAP4.error as e:
            raise MailAuthError(f"IMAP login failed for {account.email}: {e}") from e
        return conn

    def _xoauth2_authobject(self, account: MailAccountDTO):
        """
        SASL callback for imaplib.authenticate.

        The first (empty) challenge gets the credentials; if the server rejects
        them it sends a second challenge carrying an error JSON, and the SASL
        spec requires an empty reply there — returning the credentials again
        would garble the server's error text.
        """
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
                return []  # provider has no such folder (e.g. no Spam)

            status, _ = conn.select(_quote_mailbox(real), readonly=True)
            if status != "OK":
                raise MailFetchError(f"Cannot open {folder!r} ({real}) for {account.email}")

            # UID SEARCH/FETCH: UIDs are stable across sessions, so the local
            # history store can key on them reliably.
            status, data = conn.uid("search", None, "ALL")
            if status != "OK" or not data or not data[0]:
                return []

            uids = data[0].split()
            chosen = uids[-limit:] if limit > 0 else uids

            messages: list[MessageDTO] = []
            for uid in reversed(chosen):  # newest first
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
        # BODY.PEEK[] leaves the \Seen flag untouched; FLAGS tells us if it is read.
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
                return name  # special-use flag is authoritative
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
                # Last quoted token (or last token) is the folder name.
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

    # ------------------------------------------------------------------
    # SMTP (blocking)
    # ------------------------------------------------------------------

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
            # email.policy.default refuses header values containing CR/LF, which
            # is what stops a crafted recipient or subject from injecting extra
            # headers. Surface it as a send failure instead of crashing the
            # worker thread with an unhandled exception.
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
            # smtplib base64-encodes whatever the authobject returns.
            server.auth("XOAUTH2", lambda: xoauth2, initial_response_ok=True)
        else:
            server.login(_login_user(account), _clean(account.password))

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

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

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
