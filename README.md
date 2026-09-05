# email-aggregator

A single client that unifies several mailboxes — Gmail, Outlook, Mail.ru,
Yandex, and any other IMAP/SMTP service — into one interface: fetch and send
mail across all accounts at once.

The GUI is the primary way to use it (Qt/PySide6); a console mode also exists,
built on the same use-case layer, which stays independent of how input/output
happens.

## Idea

Gmail, Outlook, Mail.ru, and the rest differ only in their IMAP/SMTP server
addresses. So there's one universal adapter, `ImapSmtpMailAdapter`, and
provider differences are reduced to host/port presets in
`provider_presets.py`. Adding a new service is just one more entry in the
presets.

The "unified inbox" is the `FetchAllInboxesUseCase`: it pulls every account in
parallel (`asyncio.gather`) and merges the messages into one list sorted by
date. One account failing doesn't take down the rest.

## Architecture

Clean layered architecture:

```
src/
  adapter/mail/        IMAP/SMTP adapter, provider presets, JSON/encrypted account store
  application/mail/    dto/ interfaces/ usecases/ — business logic, no I/O
  main/                config, DI container, GUI and console entry points
```

Dependencies are wired through `dependency-injector`; use cases only know
about interfaces (`IMailAdapter`, `IAccountRepository`), never concrete
classes.

## Running from source

Graphical interface (Qt / PySide6):

```bash
uv sync
uv run python -m src.main.qt_gui
```

Console mode:

```bash
uv run python -m src
```

Both the GUI and the console share the **same** use cases from the DI
container. Between them sits `mail_service.py`: a synchronous facade that
turns the async use cases into JSON-compatible dicts (`asyncio.run` inside).
The GUI calls its methods from a `QThreadPool` and gets results back via
signals, so the window never freezes on network calls.

The look is inspired by `neural-background.html`:

- `qt_neural.py` — an animated "neural network" background (`QPainter` +
  `QTimer`, glowing nodes via radial gradients, amber connection lines);
- `qt_theme.py` — a dark amber palette, QSS (rounded corners, glass-panel
  cards), and Google Fonts Cormorant Garamond / Barlow loaded via
  `QFontDatabase` (falling back to Georgia / Segoe UI if the fonts aren't
  found);
- `qt_gui.py` — the main window: a folder sidebar, message list, reading pane,
  and dialogs (Compose / Accounts / Add account with OAuth device flow /
  Filter).

### Folders, history, and reading

- The sidebar has **Inbox / Sent / Spam** tabs. Logical folders are matched to
  real IMAP folder names via special-use flags (`\Sent`, `\Junk`, RFC 6154),
  falling back to localized name heuristics — see `imap_smtp_adapter.py`.
- **Message history** is kept locally in SQLite (`messages.db`,
  `sqlite_message_store.py`) via the SQLAlchemy ORM: every refresh upserts
  messages (with their bodies) keyed by the stable IMAP UID, so folders
  remember their contents between runs, messages survive even if the server
  removes them, and bodies open instantly without re-fetching.
- Clicking a message opens it in reading mode (QtWebEngine, HTML body) —
  Gmail-style: a large subject line, from/to/date, then the body. An email's
  HTML is input fully controlled by the sender, so it's routed through
  `mail_content.py`: active elements are stripped by a parser, and the
  rendering engine gets a document with a `Content-Security-Policy` that
  denies scripts and — until you explicitly click **Load remote content** —
  any network load. A tracking pixel won't fire until you allow it, and that
  permission only applies to the message you're viewing.
- **Filter** (button in the sidebar) opens display settings
  (`display_settings.json`): how many messages per account, unread-only,
  history from a given date, search by subject/sender.
- **Manual refresh** (on by default): the network is only polled on the
  Refresh button, and switching folders instantly shows local history. If
  turned off, a **Throttle** slider appears (auto-sync interval in seconds);
  rapid tab switching collapses into a single request.

Menu:

- **Unified inbox** — messages from every account together, newest first.
- **One account's inbox** — a single mailbox's inbox.
- **Send a message** — send from the selected account.
- **Accounts** — add/remove/view. The provider is detected from the domain
  automatically; for unknown domains, hosts/ports are entered manually.

## Accounts and passwords

Accounts are stored in `accounts.enc` — an encrypted store (AES-256-GCM, the
key derived from a master password via Argon2id with a random salt). Mailbox
passwords and OAuth refresh tokens never touch disk in the clear. The master
password is asked once on launch; the minimum length is 12 characters,
because it protects every other credential, and a short one can be brute
forced offline in hours if the file ever leaks.

The old plaintext `accounts.json` (see `accounts.example.json`) is imported on
first run and then **destroyed** — the file is overwritten and deleted, not
renamed. If you're upgrading from a version that left behind
`accounts.json.migrated`, that leftover is also shredded on first login.

Gmail, Mail.ru, Yandex, iCloud, and Yahoo require an **app password**, not
your main account password — a regular password won't be accepted for
IMAP/SMTP.

## Outlook: signing in via OAuth2

Microsoft has disabled password-based (basic auth) login for personal
Outlook/Hotmail accounts — IMAP/SMTP there only works via **OAuth2
(XOAUTH2)**. The app supports this through the **device-code flow**
(sign in via a browser and a short code, no local server needed).

You need to register a free app once:

1. [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID → App registrations → New registration**.
2. **Supported account types**: personal Microsoft accounts.
3. After creation: **Authentication → Allow public client flows → Yes**.
4. Copy the **Application (client) ID**.

Then in the app: **Accounts → Add account**, enter an `@outlook.com` address —
the preset will pick OAuth2 automatically, ask for the **Client ID**, and show
a link and code to sign in with. Once you approve it in the browser, the
refresh token is saved into the encrypted store, and the app refreshes the
short-lived access tokens itself.

OAuth providers live in `oauth_token_provider.py` — adding Gmail is just
another entry (its device-code endpoint plus the
`https://mail.google.com/` scope).

## Tests

```bash
uv run pytest
```

## Building and installing

You don't need to build anything to use the app — download a ready-made
installer from the [Releases](../../releases) page instead:

- **Windows** — download `All-in-one-Email-Setup-<version>.exe` and run it.
  No admin rights needed; it installs under
  `%LOCALAPPDATA%\Programs\All-in-one-Email`, adds a Start Menu shortcut, and
  registers an uninstaller. The installer isn't code-signed, so Windows
  SmartScreen will show a warning on first run — click **More info → Run
  anyway**.
- **Linux** — download `All-in-one-Email-Setup-<version>.sh` and run it with
  `sh All-in-one-Email-Setup-<version>.sh`. PyInstaller can't cross-compile,
  so this script clones the tagged source into a temp directory, builds the
  app locally, installs it under `~/.local/opt/email-aggregator` with a
  desktop menu entry, and deletes the cloned source afterwards — nothing but
  the installed program is left behind.

Once installed, the app is fully self-contained: it doesn't depend on this
repository, Python, or `uv` being present on the machine. Your data
(`accounts.enc`, `messages.db`, settings) lives separately in
`%APPDATA%\EmailAggregator` (Windows) or the platform equivalent, and survives
both uninstalling and deleting this repo.

### Building it yourself

Two scripts in the repo root automate the whole pipeline — checking for `uv`
and the platform's packaging tool, installing them if missing, building with
PyInstaller, and packaging the result:

```bash
# Windows (run in the repo — this is a dev-side build script, not what end
# users run):
windows_installer.bat
```

```bash
# Linux (this is the same script published in Releases — see above):
sh All-in-one-Email-Setup-<version>.sh
```

`windows_installer.bat` produces
`installer/Output/All-in-one-Email-Setup-<version>.exe` (~155 MB, built with
PyInstaller + Inno Setup) and copies it into the repo root, then cleans up
PyInstaller's `dist/`/`build/` scaffolding.

A few things that break if forgotten:

- **Don't change `AppId` in `installer/All-in-one-Email.iss`.** Windows uses
  it to recognize a new build as an upgrade of the old one; a different GUID
  means the user ends up with two installations side by side.
- **Uninstalling doesn't touch user data.** `accounts.enc`, `messages.db`,
  and settings live in `%APPDATA%\EmailAggregator`
  (see `_redirect_data_when_frozen` in `qt_gui.py`); the uninstaller leaves
  them alone, so reinstalling finds mail history and accounts still there.
- **Don't add `collect_all('PySide6')` back to the `.spec`.** It used to
  duplicate every Qt library in the bundle; PyInstaller's built-in hook
  already collects what's needed.
- **The Windows installer isn't code-signed.** SmartScreen will warn on first
  run; that's only fixed by a code-signing certificate, unrelated to the
  build itself.
- **Releasing a new version means a new git tag.** `All-in-one-Email-Setup-<version>.sh`
  clones a pinned tag (`VERSION_TAG` at the top of the script), not the
  moving `main` branch — so a published release keeps building the exact code
  it shipped with, even after `main` moves on. Bump `VERSION_TAG` to match
  the new tag before publishing the next release.
