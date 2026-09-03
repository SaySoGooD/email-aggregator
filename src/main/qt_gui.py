from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import time
from typing import Any, Callable

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QSystemTrayIcon,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.main import mail_content, qt_theme
from src.main.dependency_injection import container
from src.main.mail_service import MailService
from src.main.paths import resource_dir
from src.main.qt_neural import NeuralBackground

_FOLDERS = [
    ("inbox", "Inbox"),
    ("sent", "Sent"),
    ("spam", "Spam"),
    ("starred", "★ Starred"),
]
_FOLDER_TITLE = dict(_FOLDERS)

# Per-item roles carrying the brand colour and slug, so the row-border delegate
# can reach them from every column (not just column 0, which holds the message).
_BRAND_ROLE = Qt.ItemDataRole.UserRole + 1
_SLUG_ROLE = Qt.ItemDataRole.UserRole + 2
_PREVIEW_ROLE = Qt.ItemDataRole.UserRole + 3
_READ_ROLE = Qt.ItemDataRole.UserRole + 4

# Network refresh throttle: at most one server request per this many seconds,
# with a short debounce so rapid tab-switching coalesces into one fetch.
_MIN_REFRESH_INTERVAL = 5.0
_REFRESH_DEBOUNCE_MS = 300

# Per-provider branding: (badge background, badge text, badge letter, row text).
# Colours evoke each service so a row is recognizable at a glance.
_BRAND = {
    "gmail": ("#EA4335", "#FFFFFF", "G", "#4C8DF6"),
    "outlook": ("#0A84FF", "#FFFFFF", "O", "#4CA6FF"),
    "mailru": ("#F2F2F2", "#141414", "M", "#E8E8E8"),
    "yandex": ("#FC3F1D", "#FFFFFF", "Y", "#FF6A4D"),
    "icloud": ("#3693F3", "#FFFFFF", "i", "#5AA7F5"),
    "yahoo": ("#6001D2", "#FFFFFF", "Y", "#9B5CFF"),
    "other": (qt_theme.SURFACE, qt_theme.TEXT, "@", qt_theme.TEXT),
}

# Some brands get a multi-stop gradient outline instead of a flat colour:
# Gmail's four Google colours, Outlook's azure→blue→navy. Others stay solid.
_BRAND_GRADIENT = {
    "gmail": ["#4285F4", "#EA4335", "#FBBC05", "#34A853"],
    "outlook": ["#28A8EA", "#0078D4", "#005A9E"],
}

_ICONS_DIR = resource_dir() / "assets" / "icons"


# ---------------------------------------------------------------------------
# Background work
# ---------------------------------------------------------------------------


# Bridges keep the callbacks reachable until their queued signal is delivered.
_active_bridges: set["_Bridge"] = set()


class _Bridge(QObject):
    """
    Delivers a worker's result to the GUI thread.

    The signals are connected to this object's own bound methods, so — because
    the bridge is created on (and belongs to) the main thread — a cross-thread
    emit is auto-queued onto the GUI thread. Connecting to a bare lambda instead
    would run it directly in the worker thread and touch widgets off-thread.
    """

    done = Signal(object)
    error = Signal(str)

    def __init__(
        self, on_done: Callable[[Any], None], on_error: Callable[[str], None]
    ) -> None:
        super().__init__()
        self._on_done = on_done
        self._on_error = on_error
        self.done.connect(self._deliver_done)
        self.error.connect(self._deliver_error)

    def _deliver_done(self, result: Any) -> None:
        try:
            self._on_done(result)
        finally:
            _active_bridges.discard(self)

    def _deliver_error(self, message: str) -> None:
        try:
            self._on_error(message)
        finally:
            _active_bridges.discard(self)


class _Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], bridge: _Bridge, args: tuple) -> None:
        super().__init__()
        self._fn = fn
        self._bridge = bridge
        self._args = args

    def run(self) -> None:
        try:
            self._bridge.done.emit(self._fn(*self._args))
        except Exception as exc:  # marshalled to the GUI thread via the bridge
            self._bridge.error.emit(str(exc))


def run_bg(
    fn: Callable[..., Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[str], None],
    *args: Any,
) -> None:
    bridge = _Bridge(on_done, on_error)
    _active_bridges.add(bridge)
    QThreadPool.globalInstance().start(_Worker(fn, bridge, args))


def _glow(widget: QWidget) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(26)
    effect.setColor(QColor(240, 160, 20, 150))
    effect.setOffset(0, 0)
    widget.setGraphicsEffect(effect)


def _split(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


_EXPORT_DIR: str | None = None


def _export_dir() -> str:
    """
    A private directory for messages exported to the system browser.

    These files hold full message bodies, so they go in a per-process directory
    that mkdtemp creates with owner-only permissions and that is removed when
    the app exits — the previous NamedTemporaryFile(delete=False) left every
    message ever opened in the browser sitting in the system temp directory
    indefinitely.
    """
    global _EXPORT_DIR
    if _EXPORT_DIR is None:
        _EXPORT_DIR = tempfile.mkdtemp(prefix="email-aggregator-")
        atexit.register(shutil.rmtree, _EXPORT_DIR, True)
    return _EXPORT_DIR


# Schemes a clicked link in an email may be handed to the operating system.
# QDesktopServices.openUrl on an arbitrary scheme is a launcher: file: opens
# local content and the registered handler for some other scheme may do more.
_CLICKABLE_SCHEMES = frozenset({"http", "https", "mailto", "tel"})


class _MailPage(QWebEnginePage):
    """Renders the email; clicked links open in the system browser, not in-view."""

    def acceptNavigationRequest(self, url: object, nav_type: object, is_main: bool):  # noqa: N802
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            scheme = QUrl(url).scheme().lower()
            if scheme in _CLICKABLE_SCHEMES:
                QDesktopServices.openUrl(url)
            return False
        # A navigation the user did not click — a meta refresh, a redirect —
        # is the message moving itself off the document it was given. Block it;
        # setHtml's own about:blank load is unaffected.
        if is_main and QUrl(url).scheme().lower() in ("http", "https"):
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main)


class _SubjectDelegate(QStyledItemDelegate):
    """
    Renders the Subject cell like Gmail: the subject in the normal text colour,
    followed by a body snippet in a dimmer colour so it recedes behind the
    subject. Both share the cell and elide to fit.
    """

    def paint(self, painter: QPainter, option: Any, index: Any) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            hi = QColor(qt_theme.ACCENT)
            hi.setAlpha(40)
            painter.fillRect(option.rect, hi)

        subject = index.data(Qt.ItemDataRole.DisplayRole) or ""
        preview = index.data(_PREVIEW_ROLE) or ""
        read = bool(index.data(_READ_ROLE))
        rect = option.rect.adjusted(6, 0, -8, 0)
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

        subj_font = QFont(option.font)  # bold already if the row is unread
        subj_metrics = QFontMetrics(subj_font)
        if selected:
            subj_color = QColor(qt_theme.ACCENT_HI)
        else:  # read subjects recede to muted; unread stay bright
            subj_color = QColor(qt_theme.MUTED if read else qt_theme.TEXT)
        snippet_color = QColor(qt_theme.FAINT if read else qt_theme.MUTED)

        painter.save()
        subj_width = subj_metrics.horizontalAdvance(subject)
        # Enough room for the subject plus a bit of snippet? Show both.
        if preview and subj_width < rect.width() - 40:
            painter.setFont(subj_font)
            painter.setPen(subj_color)
            painter.drawText(rect, flags, subject)

            snippet_rect = rect.adjusted(subj_width + 12, 0, 0, 0)
            snippet_font = QFont(option.font)
            snippet_font.setBold(False)
            snippet_metrics = QFontMetrics(snippet_font)
            elided = snippet_metrics.elidedText(
                preview, Qt.TextElideMode.ElideRight, snippet_rect.width()
            )
            painter.setFont(snippet_font)
            painter.setPen(snippet_color)
            painter.drawText(snippet_rect, flags, elided)
        else:
            painter.setFont(subj_font)
            painter.setPen(subj_color)
            elided = subj_metrics.elidedText(
                subject, Qt.TextElideMode.ElideRight, rect.width()
            )
            painter.drawText(rect, flags, elided)
        painter.restore()


class _MailTree(QTreeWidget):
    """
    Message list that paints each row as one branded card: a faint brand-tinted
    background plus a full-width rounded outline in the service colour (a
    multi-stop gradient for Gmail/Outlook). Done in ``drawRow`` — which gets the
    whole-row rect — so the outline never breaks at column seams.
    """

    def drawRow(self, painter: QPainter, option: Any, index: Any) -> None:
        color = index.data(_BRAND_ROLE)
        if color:  # tint the row background before the cells are drawn
            tint = QColor(color)
            tint.setAlpha(26)
            painter.fillRect(option.rect, tint)

        super().drawRow(painter, option, index)

        if not color:
            return  # loading placeholder rows carry no brand
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen()
        pen.setWidth(1)
        stops = _BRAND_GRADIENT.get(index.data(_SLUG_ROLE))
        if stops:
            gradient = QLinearGradient(0, 0, self.viewport().width(), 0)
            last = len(stops) - 1
            for i, c in enumerate(stops):
                gradient.setColorAt(i / last, QColor(c))
            pen.setBrush(QBrush(gradient))
        else:
            pen.setColor(QColor(color))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(option.rect.adjusted(1, 1, -2, -1), 6, 6)
        painter.restore()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(NeuralBackground):
    def __init__(self, service: MailService, fonts: dict[str, str]) -> None:
        super().__init__()
        self._svc = service
        self._fonts = fonts
        self._messages: list[dict[str, Any]] = []
        self._all_messages: list[dict[str, Any]] = []
        self._errors: dict[str, str] = {}
        self._search_text = ""
        self._folder = "inbox"
        self._read_filter: bool | None = None  # None=all, True=read, False=unread
        self._last_fetch = 0.0
        self._fetching = False
        self._pending = False
        self._notify_errors = False
        self._manual = True
        self._throttle = _MIN_REFRESH_INTERVAL
        self._icon_cache: dict[str, QIcon] = {}
        self._load_settings()

        self.setWindowTitle("Email Aggregator")
        icon_path = _ICONS_DIR / "app.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1140, 720)
        self._build()

        self._fetch_timer = QTimer(self)
        self._fetch_timer.setSingleShot(True)
        self._fetch_timer.timeout.connect(self._fire_fetch)

        self._build_tray()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._apply_notifications()

        self.set_active(self._neural)  # apply neural-background setting
        self.refresh(force=True)

    # -- notifications -------------------------------------------------

    def _build_tray(self) -> None:
        icon = QIcon(str(_APP_ICON)) if _APP_ICON.exists() else self.windowIcon()
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("Email Aggregator")
        menu = QMenu()
        menu.addAction("Open", self._show_window)
        menu.addAction("Quit", QApplication.quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(lambda _reason: self._show_window())
        self._tray.show()

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _apply_notifications(self) -> None:
        if self._notifications and self._notify_minutes > 0:
            self._poll_timer.start(self._notify_minutes * 60_000)
        else:
            self._poll_timer.stop()

    def _poll(self) -> None:
        if not self._notifications:
            return
        run_bg(self._svc.poll_new, self._on_poll, lambda _e: None)

    def _on_poll(self, new: list[dict[str, Any]]) -> None:
        if not new:
            return
        self._notify(new)
        if self._folder == "inbox":
            self.refresh()  # surface the new messages in the list

    def _notify(self, new: list[dict[str, Any]]) -> None:
        if not self._tray.supportsMessages():
            return
        info = QSystemTrayIcon.MessageIcon.Information
        if len(new) == 1:
            m = new[0]
            self._tray.showMessage(m["sender"] or "New mail", m["subject"] or "", info, 6000)
        else:
            self._tray.showMessage(
                "New mail", f"{len(new)} new messages", info, 6000
            )

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_nav())

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self._build_sidebar())
        middle.addWidget(self._build_content(), 1)
        root.addLayout(middle, 1)

        root.addWidget(self._build_status())

    # -- nav -----------------------------------------------------------

    def _build_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("Nav")
        layout = QHBoxLayout(nav)
        layout.setContentsMargins(28, 16, 28, 16)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        logo = QLabel("Email Aggregator")
        logo.setObjectName("Logo")
        logo.setFont(QFont(self._fonts["serif"], 22))
        tagline = QLabel("O N E   I N B O X   F O R   A L L   Y O U R   M A I L")
        tagline.setObjectName("Tagline")
        title_box.addWidget(logo)
        title_box.addWidget(tagline)
        layout.addLayout(title_box)
        layout.addStretch(1)

        compose = QPushButton("Write…")
        compose.setObjectName("Primary")
        compose.setCursor(Qt.CursorShape.PointingHandCursor)
        compose.clicked.connect(self._compose)
        _glow(compose)

        refresh = QPushButton("Refresh")
        refresh.setObjectName("Ghost")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(lambda: self.refresh(force=True))

        accounts = QPushButton("Accounts")
        accounts.setObjectName("Ghost")
        accounts.setCursor(Qt.CursorShape.PointingHandCursor)
        accounts.clicked.connect(self._accounts)

        for btn in (compose, refresh, accounts):
            layout.addWidget(btn)
            layout.addSpacing(8)
        return nav

    # -- sidebar -------------------------------------------------------

    def _build_sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(200)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(4)

        self._folder_group = QButtonGroup(self)
        self._folder_group.setExclusive(True)

        def add_item(key: str, title: str, sub: bool = False) -> QPushButton:
            btn = QPushButton(title)
            btn.setObjectName("SubSide" if sub else "Side")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._switch_folder(k))
            if key == "inbox":
                btn.setChecked(True)
            self._folder_group.addButton(btn)
            return btn

        # Inbox, with read/unread sub-filters nested beneath it.
        layout.addWidget(add_item("inbox", "Inbox"))
        layout.addWidget(add_item("inbox:unread", "Unread", sub=True))
        layout.addWidget(add_item("inbox:read", "Read", sub=True))
        layout.addSpacing(6)

        for key, title in (("sent", "Sent"), ("spam", "Spam"), ("starred", "★ Starred")):
            layout.addWidget(add_item(key, title))

        layout.addStretch(1)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {qt_theme.BORDER};")
        layout.addWidget(divider)

        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("Side")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self._open_filter)
        layout.addWidget(settings_btn)
        return bar

    def _switch_folder(self, key: str) -> None:
        # "inbox:read" / "inbox:unread" select the inbox with a read/unread filter.
        if ":" in key:
            folder, mode = key.split(":", 1)
            self._folder = folder
            self._read_filter = mode == "read"
        else:
            self._folder = key
            self._read_filter = None
        # Reset the per-tab search when moving between tabs.
        self._search_text = ""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._stack.setCurrentIndex(0)
        self._load_folder()

    # -- content (list <-> reading) ------------------------------------

    def _build_content(self) -> QWidget:
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_list_page())  # 0
        self._stack.addWidget(self._build_reading_page())  # 1
        self._stack.addWidget(self._build_filter_page())  # 2
        return self._stack

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(10)

        head = QHBoxLayout()
        self._eyebrow = QLabel("I N B O X")
        self._eyebrow.setObjectName("Eyebrow")
        head.addWidget(self._eyebrow)
        head.addSpacing(18)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        head.addWidget(self._search, 1)
        head.addSpacing(18)

        self._select_all = QCheckBox("Select all")
        self._select_all.toggled.connect(self._toggle_all)
        head.addWidget(self._select_all)
        hint = QLabel("select, then right-click")
        hint.setStyleSheet(f"color: {qt_theme.FAINT}; font-size: 11px;")
        head.addWidget(hint)
        layout.addLayout(head)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 14, 14, 14)

        self._tree = self._build_tree()
        cl.addWidget(self._tree, 1)

        # Loading indicator lives inside the table as its own first 3 rows, so
        # it never covers messages — they simply start below it. The middle row
        # spans all columns and shows the animated "Loading" text.
        self._loading_items: list[QTreeWidgetItem] = []
        self._loading_item: QTreeWidgetItem | None = None
        self._loading_dots = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.timeout.connect(self._tick_loading)

        layout.addWidget(card, 1)
        return page

    def _tick_loading(self) -> None:
        self._loading_dots = (self._loading_dots % 3) + 1
        if self._loading_item is not None:
            self._loading_item.setText(0, "Loading" + "." * self._loading_dots)

    def _start_loading(self) -> None:
        self._clear_loading_rows()
        self._loading_dots = 0
        box = QColor(qt_theme.SURFACE)
        for i in range(3):
            item = QTreeWidgetItem(["", "", "", "", ""])
            for col in range(5):
                item.setBackground(col, box)
            self._tree.insertTopLevelItem(i, item)
            self._tree.setFirstColumnSpanned(i, self._tree.rootIndex(), True)
            self._loading_items.append(item)
        # Middle row carries the centered, animated label.
        self._loading_item = self._loading_items[1]
        self._loading_item.setText(0, "Loading.")
        self._loading_item.setForeground(0, QColor(qt_theme.ACCENT))
        self._loading_item.setTextAlignment(0, Qt.AlignmentFlag.AlignCenter)
        self._loading_timer.start(350)

    def _stop_loading(self) -> None:
        self._loading_timer.stop()
        self._clear_loading_rows()

    def _clear_loading_rows(self) -> None:
        for item in self._loading_items:
            try:
                idx = self._tree.indexOfTopLevelItem(item)
            except RuntimeError:
                continue  # already destroyed by a tree.clear()
            if idx >= 0:
                self._tree.takeTopLevelItem(idx)
        self._loading_items = []
        self._loading_item = None

    def _build_tree(self) -> QTreeWidget:
        # Gmail-style columns: [checkbox] [icon] [From] [Subject … snippet] [when].
        tree = _MailTree()
        tree.setColumnCount(5)
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setIconSize(QSize(22, 22))
        tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        tree.setCursor(Qt.CursorShape.PointingHandCursor)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        tree.setColumnWidth(0, 30)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        tree.setColumnWidth(1, 40)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        tree.setColumnWidth(2, 200)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        tree.setColumnWidth(4, 92)
        tree.setItemDelegateForColumn(3, _SubjectDelegate(tree))
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._row_menu)
        tree.itemClicked.connect(self._open_selected)
        return tree

    def _row_menu(self, pos: object) -> None:
        item = self._tree.itemAt(pos)
        msg = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not msg:
            return
        menu = QMenu(self)
        star_action = menu.addAction(
            "★ Remove from Starred" if msg.get("starred") else "☆ Add to Starred"
        )
        menu.addSeparator()
        # The read/unread action follows the section of the clicked row: rows in
        # the Unread section offer "mark as read", rows in Read offer "unread".
        target_read = not msg["seen"]
        read_action = menu.addAction(
            "Mark selected as read" if target_read else "Mark selected as unread"
        )
        menu.addSeparator()
        spam_action = menu.addAction(
            "Remove sender from Spam"
            if msg.get("spam_sender")
            else "Add sender to Spam"
        )

        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is star_action:
            self._svc.toggle_favorite(msg["account"], msg["folder"], msg["uid"])
            self.refresh()
        elif chosen is read_action:
            keys = self._checked_keys()
            if not keys:  # nothing ticked → act on the clicked row alone
                keys = [(msg["account"], msg["folder"], msg["uid"])]
            self._svc.mark_messages(keys, target_read)
            self.refresh()
        elif chosen is spam_action:
            self._svc.toggle_spam_sender(msg["sender"])
            self.refresh()

    def _provider_icon(self, brand: str) -> QIcon:
        if brand not in self._icon_cache:
            path = _ICONS_DIR / f"{brand}.png"
            pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
            if pixmap.isNull():  # unknown provider: fall back to a letter badge
                pixmap = self._letter_badge(brand)
            else:
                pixmap = pixmap.scaled(
                    22,
                    22,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self._icon_cache[brand] = QIcon(pixmap)
        return self._icon_cache[brand]

    def _letter_badge(self, brand: str) -> QPixmap:
        bg, fg, letter, _ = _BRAND.get(brand, _BRAND["other"])
        size = 22
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(0, 0, size, size, 6, 6)
        font = QFont(self._fonts["sans"], 11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(fg))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, letter)
        painter.end()
        return pixmap

    def _build_reading_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(10)

        back = QPushButton("←  Back")
        back.setObjectName("Ghost")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(lambda: self._stack.setCurrentIndex(0))

        open_browser = QPushButton("Open in browser")
        open_browser.setObjectName("Ghost")
        open_browser.setCursor(Qt.CursorShape.PointingHandCursor)
        open_browser.clicked.connect(self._open_in_browser)

        # Remote images are blocked until the reader asks for them: loading one
        # tells the sender the message was opened, when, and from which address.
        self._allow_remote = False
        self._remote_btn = QPushButton("Load remote content")
        self._remote_btn.setObjectName("Ghost")
        self._remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remote_btn.setToolTip(
            "This message wants to load images from the internet. Doing so tells "
            "the sender that you opened it."
        )
        self._remote_btn.clicked.connect(self._load_remote_content)
        self._remote_btn.hide()

        top = QHBoxLayout()
        top.addWidget(back)
        top.addWidget(open_browser)
        top.addWidget(self._remote_btn)
        top.addStretch(1)
        layout.addLayout(top)

        # Themed header (our chrome) above the message, which renders as-is.
        header = QFrame()
        header.setObjectName("Card")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(4)
        self._read_subject = QLabel()
        self._read_subject.setObjectName("Subject")
        self._read_subject.setWordWrap(True)
        self._read_subject.setFont(QFont(self._fonts["serif"], 20))
        self._read_meta = QLabel()
        self._read_meta.setObjectName("Meta")
        self._read_meta.setWordWrap(True)
        hl.addWidget(self._read_subject)
        hl.addWidget(self._read_meta)
        layout.addWidget(header)

        # Full HTML/CSS rendering via Chromium (QtWebEngine) — no text parsing.
        self._reader = QWebEngineView()
        self._reader.setPage(_MailPage(self._reader))
        # Harden against active/malicious content in email HTML.
        s = self._reader.settings()
        A = QWebEngineSettings.WebAttribute
        for attr in (
            A.JavascriptEnabled,  # no scripts run from emails
            A.LocalContentCanAccessFileUrls,
            A.LocalContentCanAccessRemoteUrls,
            A.PluginsEnabled,
            A.JavascriptCanAccessClipboard,
            A.JavascriptCanOpenWindows,
            A.AllowRunningInsecureContent,
        ):
            s.setAttribute(attr, False)
        layout.addWidget(self._reader, 1)
        return page

    def _build_filter_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 12)
        layout.setSpacing(10)

        back = QPushButton("←  Back")
        back.setObjectName("Ghost")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        save = QPushButton("Save")
        save.setObjectName("Primary")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save_filter)
        top = QHBoxLayout()
        top.addWidget(back)
        top.addStretch(1)
        top.addWidget(save)
        layout.addLayout(top)

        eyebrow = QLabel("S E T T I N G S")
        eyebrow.setObjectName("Eyebrow")
        layout.addWidget(eyebrow)

        card = QFrame()
        card.setObjectName("Card")
        body = QVBoxLayout(card)
        body.setContentsMargins(22, 20, 22, 20)
        body.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(12)
        self._f_limit = QSpinBox()
        self._f_limit.setRange(1, 200)
        form.addRow("Messages per account", self._f_limit)
        body.addLayout(form)

        self._f_show_preview = QCheckBox("Show message preview")
        body.addWidget(self._f_show_preview)
        self._f_neural = QCheckBox("Animated neural background")
        body.addWidget(self._f_neural)

        self._f_notify = QCheckBox("Desktop notifications on new mail")
        self._f_notify.toggled.connect(
            lambda checked: self._f_notify_row.setVisible(checked)
        )
        body.addWidget(self._f_notify)
        self._f_notify_row = QWidget()
        nrow = QHBoxLayout(self._f_notify_row)
        nrow.setContentsMargins(24, 0, 0, 0)
        nrow.addWidget(QLabel("Check every"))
        self._f_notify_min = QSpinBox()
        self._f_notify_min.setRange(1, 60)
        self._f_notify_min.setSuffix(" min")
        nrow.addWidget(self._f_notify_min)
        nrow.addStretch(1)
        body.addWidget(self._f_notify_row)

        self._f_manual = QCheckBox("Manual refresh (sync only via the button)")
        self._f_manual.toggled.connect(
            lambda checked: self._f_throttle_row.setVisible(not checked)
        )
        body.addWidget(self._f_manual)

        self._f_throttle_row = QWidget()
        trow = QHBoxLayout(self._f_throttle_row)
        trow.setContentsMargins(24, 0, 0, 0)
        trow.addWidget(QLabel("Auto-sync every"))
        self._f_throttle = QSlider(Qt.Orientation.Horizontal)
        self._f_throttle.setRange(1, 60)
        self._f_throttle_value = QLabel("5 sec")
        self._f_throttle.valueChanged.connect(
            lambda v: self._f_throttle_value.setText(f"{v} sec")
        )
        trow.addWidget(self._f_throttle, 1)
        trow.addWidget(self._f_throttle_value)
        body.addWidget(self._f_throttle_row)

        body.addStretch(1)
        layout.addWidget(card, 1)
        return page

    def _open_filter(self) -> None:
        """Show the settings page (in place of the message list), pre-filled."""
        s = self._svc.settings()
        self._f_limit.setValue(int(s.get("limit_per_account", 15)))
        self._f_show_preview.setChecked(bool(s.get("show_preview", True)))
        self._f_neural.setChecked(bool(s.get("neural_background", True)))
        self._f_notify.setChecked(bool(s.get("notifications", True)))
        self._f_notify_min.setValue(int(s.get("notify_minutes", 2)))
        self._f_notify_row.setVisible(self._f_notify.isChecked())
        self._f_manual.setChecked(bool(s.get("manual_refresh", True)))
        self._f_throttle.setValue(int(s.get("throttle_seconds", 5)))
        self._f_throttle_row.setVisible(not self._f_manual.isChecked())
        self._stack.setCurrentIndex(2)

    def _save_filter(self) -> None:
        self._svc.save_settings(
            {
                "limit_per_account": self._f_limit.value(),
                "show_preview": self._f_show_preview.isChecked(),
                "neural_background": self._f_neural.isChecked(),
                "notifications": self._f_notify.isChecked(),
                "notify_minutes": self._f_notify_min.value(),
                "manual_refresh": self._f_manual.isChecked(),
                "throttle_seconds": self._f_throttle.value(),
            }
        )
        self._load_settings()
        self.set_active(self._neural)  # apply background toggle
        self._apply_notifications()  # apply notification polling
        self._stack.setCurrentIndex(0)
        self.refresh()

    def _build_status(self) -> QWidget:
        wrap = QFrame()
        wrap.setStyleSheet(f"background: {qt_theme.SURFACE_ALT};")
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(26, 2, 26, 2)
        self._status = QLabel("Ready")
        self._status.setObjectName("Status")
        layout.addWidget(self._status)
        return wrap

    # -- data ----------------------------------------------------------

    def _load_settings(self) -> None:
        settings = self._svc.settings()
        self._manual = bool(settings.get("manual_refresh", True))
        self._throttle = float(settings.get("throttle_seconds", _MIN_REFRESH_INTERVAL))
        self._show_preview = bool(settings.get("show_preview", True))
        self._neural = bool(settings.get("neural_background", True))
        self._notifications = bool(settings.get("notifications", True))
        self._notify_minutes = int(settings.get("notify_minutes", 2))

    def refresh(self, force: bool = False) -> None:
        """Show local history instantly, then sync from the server per the mode.

        Manual mode syncs only on an explicit Refresh (``force``); auto mode
        syncs on every folder change, rate-limited by the throttle slider.
        """
        folder = self._folder
        title = _FOLDER_TITLE[folder]
        if self._read_filter is True:
            title += " / read"
        elif self._read_filter is False:
            title += " / unread"
        self._eyebrow.setText(" ".join(title.upper()))
        # Instant, network-free: local cache on the GUI thread.
        self._populate(self._svc.cached(folder)["messages"], {}, folder)
        if force:
            self._last_fetch = 0.0  # bypass the cooldown for an explicit Refresh
            self._notify_errors = True  # surface per-account failures to the user
        elif self._manual:
            return  # manual mode: no automatic network sync
        self._schedule_fetch()

    def _load_folder(self) -> None:
        self.refresh()

    def _schedule_fetch(self) -> None:
        """(Re)arm the debounced, rate-limited network fetch."""
        if self._fetching:
            self._pending = True  # a request is in flight; queue one after it
            return
        elapsed = time.monotonic() - self._last_fetch
        wait = max(_REFRESH_DEBOUNCE_MS, int((self._throttle - elapsed) * 1000))
        self._fetch_timer.start(wait)

    def _fire_fetch(self) -> None:
        if self._fetching:
            return
        folder = self._folder
        self._fetching = True
        self._last_fetch = time.monotonic()
        self._start_loading()
        run_bg(
            self._svc.folder,
            lambda result, f=folder: self._on_folder(result, f),
            self._on_fetch_error,
            folder,
        )

    def _after_fetch(self) -> None:
        """Common tail: honor a request queued while this one was in flight."""
        self._fetching = False
        self._stop_loading()
        if self._pending:
            self._pending = False
            self._schedule_fetch()

    def _on_folder(self, result: dict[str, Any], folder: str) -> None:
        if folder == self._folder:  # ignore results for a folder left behind
            errors = result.get("errors") or {}
            self._populate(result["messages"], errors, folder)
            if errors and self._notify_errors:
                self._notify_errors = False
                details = "\n".join(f"• {name}: {err}" for name, err in errors.items())
                QMessageBox.warning(
                    self, "Some accounts failed to sync", details
                )
        self._after_fetch()

    def _on_fetch_error(self, message: str) -> None:
        self._status.setText(f"Sync error: {message}")
        self._after_fetch()

    def _populate(
        self, messages: list[dict[str, Any]], errors: dict[str, str], folder: str
    ) -> None:
        self._all_messages = messages
        self._errors = errors
        self._render_list()

    def _on_search(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self._render_list()

    def _render_list(self) -> None:
        """Render the current folder applying the read/unread filter and search."""
        # tree.clear() below destroys any loading rows; drop their refs first so
        # nothing points at deleted C++ objects.
        self._loading_timer.stop()
        self._loading_items = []
        self._loading_item = None
        self._tree.clear()
        if self._select_all.isChecked():
            self._select_all.blockSignals(True)
            self._select_all.setChecked(False)
            self._select_all.blockSignals(False)

        # Inbox shows everything mixed (sorted by date); the sidebar read/unread
        # sub-filter and the search box narrow what's shown.
        visible = self._all_messages
        if self._read_filter is True:
            visible = [m for m in visible if m["seen"]]
        elif self._read_filter is False:
            visible = [m for m in visible if not m["seen"]]
        if self._search_text:
            visible = [m for m in visible if self._matches(m)]

        self._messages = visible
        for msg in visible:
            self._add_message_item(msg)

        unread = sum(1 for m in self._all_messages if not m["seen"])
        total = len(self._all_messages)
        summary = f"{unread} unread · {total - unread} read"
        if self._search_text:
            summary = f"{len(visible)} found · " + summary
        if self._errors:
            joined = "   ".join(f"⚠ {n}: {e}" for n, e in self._errors.items())
            summary += f"      {joined}"
        self._status.setText(summary)

    def _matches(self, msg: dict[str, Any]) -> bool:
        needle = self._search_text
        return any(
            needle in (msg.get(field) or "").lower()
            for field in ("from", "sender", "subject", "preview")
        )

    def _add_message_item(self, msg: dict[str, Any]) -> None:
        brand = msg.get("provider", "other")
        brand_color = _BRAND.get(brand, _BRAND["other"])[3]
        seen = msg["seen"]
        subject = msg["subject"]
        if msg.get("starred"):
            subject = f"★ {subject}"
        preview = msg.get("preview", "") if self._show_preview else ""
        item = QTreeWidgetItem(["", "", msg["from"], subject, msg["when"]])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setIcon(1, self._provider_icon(brand))
        # Read rows recede (muted); unread stay bright and bold — like Gmail.
        item.setForeground(2, QColor(qt_theme.MUTED if seen else qt_theme.TEXT))
        item.setForeground(4, QColor(qt_theme.MUTED))
        item.setTextAlignment(
            4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        if not seen:
            for col in (2, 3):
                font = item.font(col)
                font.setBold(True)
                item.setFont(col, font)
        item.setData(0, Qt.ItemDataRole.UserRole, msg)
        item.setData(3, _PREVIEW_ROLE, preview)
        item.setData(3, _READ_ROLE, seen)
        for col in range(5):  # brand reachable from every column for the delegate
            item.setData(col, _BRAND_ROLE, brand_color)
            item.setData(col, _SLUG_ROLE, brand)
        self._tree.addTopLevelItem(item)

    def _message_items(self):
        """Yield the top-level items that are messages (not headers/loading)."""
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole):
                yield item

    def _toggle_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item in self._message_items():
            item.setCheckState(0, state)

    def _checked_keys(self) -> list[tuple[str, str, str]]:
        return [
            (m["account"], m["folder"], m["uid"])
            for item in self._message_items()
            if item.checkState(0) == Qt.CheckState.Checked
            and (m := item.data(0, Qt.ItemDataRole.UserRole))
        ]

    def _open_selected(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:  # clicking the checkbox column shouldn't open the message
            return
        msg = item.data(0, Qt.ItemDataRole.UserRole)
        if not msg:  # a header or loading placeholder row
            return
        self._status.setText("Opening…")
        run_bg(
            self._svc.message,
            self._render_message,
            self._on_error,
            msg["account"],
            msg["folder"],
            msg["uid"],
        )

    def _render_message(self, msg: dict[str, Any] | None) -> None:
        if not msg:
            QMessageBox.information(self, "Message", "Message body unavailable.")
            return
        self._current_msg = msg
        self._read_subject.setText(msg.get("subject") or "(no subject)")
        meta = msg.get("sender", "")
        if msg.get("recipients"):
            meta += f"    →  {msg['recipients']}"
        meta += f"    ·  {msg.get('date', '')}"
        self._read_meta.setText(meta)
        # Each message starts blocked again; a decision made about one sender
        # must not silently carry over to the next.
        self._allow_remote = False
        self._remote_btn.setVisible(
            mail_content.has_remote_content(msg.get("body_html"))
        )
        self._reader.setHtml(self._message_document(msg))
        self._stack.setCurrentIndex(1)
        self._status.setText("")
        self.refresh()  # opened → now read; regroup the list behind the reader

    def _message_document(self, msg: dict[str, Any]) -> str:
        """The message wrapped in a scrubbed, CSP-locked HTML document."""
        return mail_content.document(
            msg.get("body_html"),
            msg.get("body_text"),
            allow_remote=self._allow_remote,
        )

    def _load_remote_content(self) -> None:
        """Re-render the current message with its remote images allowed."""
        msg = getattr(self, "_current_msg", None)
        if not msg:
            return
        self._allow_remote = True
        self._remote_btn.hide()
        self._reader.setHtml(self._message_document(msg))

    def _open_in_browser(self) -> None:
        msg = getattr(self, "_current_msg", None)
        if not msg:
            return
        # The system browser runs JavaScript, and a file:// document is a more
        # privileged origin than a web page. The document written here is the
        # scrubbed one carrying the same CSP the in-app reader uses, so a script
        # in the message has nothing to run in either place.
        path = os.path.join(_export_dir(), f"message-{int(time.time() * 1000)}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._message_document(msg))
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_error(self, message: str) -> None:
        self._stop_loading()
        self._status.setText(f"Error: {message}")
        QMessageBox.critical(self, "Error", message)

    # -- dialogs -------------------------------------------------------

    def _compose(self) -> None:
        accounts = self._svc.accounts()
        if not accounts:
            QMessageBox.information(self, "Compose", "Add an account first.")
            return
        ComposeDialog(self, self._svc, self._fonts, accounts).exec()

    def _accounts(self) -> None:
        AccountsDialog(self, self._svc, self._fonts).exec()
        # Force a sync so a just-added account is fetched even in manual mode.
        self.refresh(force=True)


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------


class ComposeDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        service: MailService,
        fonts: dict[str, str],
        accounts: list[dict[str, Any]],
    ) -> None:
        super().__init__(parent)
        self._svc = service
        self.setWindowTitle("Compose")
        self.resize(600, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        form = QFormLayout()
        form.setSpacing(10)

        self._from = QComboBox()
        self._from.addItems([a["name"] for a in accounts])
        self._to = QLineEdit()
        self._cc = QLineEdit()
        self._subject = QLineEdit()
        form.addRow("From", self._from)
        form.addRow("To", self._to)
        form.addRow("Cc", self._cc)
        form.addRow("Subject", self._subject)
        layout.addLayout(form)

        self._body = QTextEdit()
        layout.addWidget(self._body, 1)

        self._send = QPushButton("Send")
        self._send.setObjectName("Primary")
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send.clicked.connect(self._do_send)
        _glow(self._send)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._send)
        layout.addLayout(row)

    def _do_send(self) -> None:
        to = _split(self._to.text())
        if not to:
            QMessageBox.warning(self, "Compose", "Enter at least one recipient.")
            return
        payload = {
            "account": self._from.currentText(),
            "to": to,
            "cc": _split(self._cc.text()),
            "subject": self._subject.text().strip(),
            "body": self._body.toPlainText(),
        }
        self._send.setEnabled(False)
        self._send.setText("Sending…")
        run_bg(self._svc.send, self._sent, self._failed, payload)

    def _sent(self, _result: Any) -> None:
        QMessageBox.information(self, "Compose", "Message sent.")
        self.accept()

    def _failed(self, message: str) -> None:
        self._send.setEnabled(True)
        self._send.setText("Send")
        QMessageBox.critical(self, "Send failed", message)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


class AccountsDialog(QDialog):
    def __init__(
        self, parent: QWidget, service: MailService, fonts: dict[str, str]
    ) -> None:
        super().__init__(parent)
        self._svc = service
        self._fonts = fonts
        self.setWindowTitle("Accounts")
        self.resize(520, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        row = QHBoxLayout()
        add = QPushButton("Add")
        add.setObjectName("Primary")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self._add)
        remove = QPushButton("Remove")
        remove.setObjectName("Ghost")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)

        self._reload()

    def _reload(self) -> None:
        self._accounts = self._svc.accounts()
        self._list.clear()
        for account in self._accounts:
            self._list.addItem(f"{account['name']}  ·  {account['email']}")

    def _add(self) -> None:
        if AddAccountDialog(self, self._svc, self._fonts).exec():
            self._reload()

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        account = self._accounts[row]
        confirm = QMessageBox.question(self, "Remove", f"Remove {account['name']}?")
        if confirm == QMessageBox.StandardButton.Yes:
            self._svc.remove_account(account["name"])
            self._reload()


# ---------------------------------------------------------------------------
# Add account (provider detect + password / OAuth device flow)
# ---------------------------------------------------------------------------


class AddAccountDialog(QDialog):
    def __init__(
        self, parent: QWidget, service: MailService, fonts: dict[str, str]
    ) -> None:
        super().__init__(parent)
        self._svc = service
        self.setWindowTitle("Add account")
        self.resize(460, 560)

        self._auth = "password"
        self._oauth_provider: str | None = None
        self._refresh_token: str | None = None
        self._poll: QTimer | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._build_step1()

    def _clear(self) -> None:
        while self._layout.count():
            child = self._layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_step1(self) -> None:
        self._layout.addWidget(QLabel("Email address (your login)"))
        self._email = QLineEdit()
        self._email.setPlaceholderText("you@example.com")
        self._layout.addWidget(self._email)
        cont = QPushButton("Continue")
        cont.setObjectName("Primary")
        cont.setCursor(Qt.CursorShape.PointingHandCursor)
        cont.clicked.connect(self._detect)
        self._layout.addWidget(cont, 0, Qt.AlignmentFlag.AlignLeft)
        self._layout.addStretch(1)

    def _detect(self) -> None:
        email = self._email.text().strip()
        if "@" not in email:
            QMessageBox.warning(self, "Add account", "Enter a valid email.")
            return
        self._email_value = email
        self._build_form(self._svc.provider(email))

    def _build_form(self, provider: dict[str, Any] | None) -> None:
        self._clear()
        self._auth = provider["auth"] if provider else "password"
        self._oauth_provider = provider["oauth_provider"] if provider else None

        name = provider["name"] if provider else "Custom / manual"
        head = QLabel(f"Provider:  {name}")
        head.setObjectName("Eyebrow")
        self._layout.addWidget(head)
        if provider and provider.get("note"):
            note = QLabel(provider["note"])
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {qt_theme.MUTED};")
            self._layout.addWidget(note)

        # Necessary fields.
        need = QFormLayout()
        need.setSpacing(9)
        self._label = QLineEdit(self._email_value)
        need.addRow("Label", self._label)
        self._layout.addLayout(need)

        if self._auth == "oauth2":
            self._build_oauth(provider)
        else:
            self._layout.addWidget(QLabel("Password / app password"))
            self._layout.addLayout(self._password_row())

        # Advanced (auto-filled from the provider) — hidden behind a toggle.
        self._username = QLineEdit(self._email_value)
        self._imap_host = QLineEdit(provider["imap_host"] if provider else "")
        self._imap_port = QLineEdit(str(provider["imap_port"] if provider else 993))
        self._smtp_host = QLineEdit(provider["smtp_host"] if provider else "")
        self._smtp_port = QLineEdit(str(provider["smtp_port"] if provider else 465))
        adv = QWidget()
        adv_form = QFormLayout(adv)
        adv_form.setContentsMargins(0, 6, 0, 0)
        adv_form.addRow("Login", self._username)
        adv_form.addRow("IMAP host", self._imap_host)
        adv_form.addRow("IMAP port", self._imap_port)
        adv_form.addRow("SMTP host", self._smtp_host)
        adv_form.addRow("SMTP port", self._smtp_port)
        adv.setVisible(False)

        adv_toggle = QPushButton("⚙  Advanced (servers, login)")
        adv_toggle.setObjectName("Ghost")
        adv_toggle.setCheckable(True)
        adv_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        adv_toggle.toggled.connect(adv.setVisible)
        self._layout.addWidget(adv_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self._layout.addWidget(adv)

        self._layout.addStretch(1)
        save = QPushButton("Save")
        save.setObjectName("Primary")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save)
        self._layout.addWidget(save, 0, Qt.AlignmentFlag.AlignRight)

    def _password_row(self) -> QHBoxLayout:
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        eye = QPushButton("👁")
        eye.setObjectName("Ghost")
        eye.setCheckable(True)
        eye.setFixedWidth(40)
        eye.setCursor(Qt.CursorShape.PointingHandCursor)
        eye.toggled.connect(
            lambda shown: self._password.setEchoMode(
                QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
            )
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._password, 1)
        row.addWidget(eye)
        return row

    def _build_oauth(self, provider: dict[str, Any]) -> None:
        self._layout.addWidget(QLabel("Client ID"))
        self._client_id = QLineEdit(provider.get("default_client_id", ""))
        self._layout.addWidget(self._client_id)
        sign_in = QPushButton("Sign in (OAuth)")
        sign_in.setObjectName("Ghost")
        sign_in.setCursor(Qt.CursorShape.PointingHandCursor)
        sign_in.clicked.connect(self._oauth_signin)
        self._layout.addWidget(sign_in, 0, Qt.AlignmentFlag.AlignLeft)
        self._oauth_status = QLabel("Not signed in")
        self._oauth_status.setStyleSheet(f"color: {qt_theme.MUTED};")
        self._layout.addWidget(self._oauth_status)

    def _oauth_signin(self) -> None:
        client_id = self._client_id.text().strip()
        if not client_id:
            QMessageBox.warning(self, "OAuth", "Enter a Client ID.")
            return
        self._oauth_status.setText("Starting sign-in…")
        self._device = DeviceCodeDialog(self)
        run_bg(
            self._svc.oauth_start,
            self._oauth_started,
            self._oauth_failed,
            self._oauth_provider,
            client_id,
        )

    def _oauth_started(self, result: dict[str, Any]) -> None:
        if result.get("status") == "error" or not result.get("uri"):
            self._oauth_failed(result.get("error") or "Could not start sign-in.")
            return
        self._device.show_code(result["uri"], result["code"])
        self._device.show()
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._oauth_check)
        self._poll.start(1500)

    def _oauth_check(self) -> None:
        state = self._svc.oauth_poll()
        status = state.get("status")
        if status == "done":
            self._stop_poll()
            self._refresh_token = self._svc.oauth_refresh_token()
            self._device.accept()
            self._oauth_status.setText("Signed in ✓")
        elif status == "error":
            self._stop_poll()
            self._device.reject()
            self._oauth_failed(state.get("error") or "Sign-in failed.")

    def _stop_poll(self) -> None:
        if self._poll is not None:
            self._poll.stop()
            self._poll = None

    def _oauth_failed(self, message: str) -> None:
        self._stop_poll()
        self._oauth_status.setText("Not signed in")
        QMessageBox.critical(self, "OAuth failed", message)

    def _save(self) -> None:
        if self._auth == "oauth2" and not self._refresh_token:
            QMessageBox.warning(self, "Add account", "Sign in with OAuth first.")
            return
        data = {
            "name": self._label.text(),
            "email": self._email_value,
            "username": self._username.text(),
            "password": "" if self._auth == "oauth2" else self._password.text(),
            "imap_host": self._imap_host.text(),
            "imap_port": self._imap_port.text(),
            "smtp_host": self._smtp_host.text(),
            "smtp_port": self._smtp_port.text(),
            "auth": self._auth,
            "oauth_provider": self._oauth_provider,
            "client_id": self._client_id.text().strip()
            if self._auth == "oauth2"
            else None,
            "refresh_token": self._refresh_token,
        }
        try:
            self._svc.add_account(data)
        except Exception as exc:
            QMessageBox.critical(self, "Add account", str(exc))
            return
        self.accept()


class DeviceCodeDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign in")
        self.resize(440, 220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addWidget(QLabel("A browser will open. Enter this code to sign in:"))
        self._uri = QLineEdit()
        self._uri.setReadOnly(True)
        layout.addWidget(self._uri)
        self._code = QLabel("…")
        self._code.setStyleSheet(
            f"color: {qt_theme.ACCENT}; font-size: 26px; font-weight: 600;"
        )
        layout.addWidget(self._code)
        waiting = QLabel("Waiting for confirmation…")
        waiting.setStyleSheet(f"color: {qt_theme.MUTED};")
        layout.addWidget(waiting)
        layout.addStretch(1)

    def show_code(self, uri: str, code: str) -> None:
        self._uri.setText(uri)
        self._code.setText(code)
        QDesktopServices.openUrl(QUrl(uri))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_APP_ICON = _ICONS_DIR / "app.png"


def _ask_password(title: str, label: str) -> tuple[str, bool]:
    return QInputDialog.getText(
        None, title, label, QLineEdit.EchoMode.Password
    )


# The master password is the only thing standing between a copied accounts.enc
# and every mailbox credential in it. Argon2id makes each guess expensive, but
# a four-character password is still exhausted offline in hours.
_MIN_MASTER_PASSWORD = 12


def _unlock_accounts(repo: Any) -> bool:
    """Prompt for the master password (or create one). False = user cancelled."""
    if repo.is_initialized():
        failures = 0
        while True:
            pw, ok = _ask_password("Unlock", "Master password:")
            if not ok:
                return False
            try:
                repo.unlock(pw)
                repo.purge_plaintext_remnants()
                return True
            except ValueError:
                failures += 1
                # An honest typo is not punished; a script driving the dialog
                # runs into a delay that doubles with every wrong guess.
                delay = min(2 ** (failures - 1), 8) if failures > 1 else 0
                QMessageBox.warning(None, "Unlock", "Wrong master password.")
                if delay:
                    time.sleep(delay)
    else:
        while True:
            pw, ok = _ask_password(
                "Set master password",
                "Create a master password to encrypt your accounts.\n"
                f"At least {_MIN_MASTER_PASSWORD} characters:",
            )
            if not ok:
                return False
            if len(pw) < _MIN_MASTER_PASSWORD:
                QMessageBox.warning(
                    None,
                    "Set password",
                    f"Use at least {_MIN_MASTER_PASSWORD} characters. This one "
                    "password protects every mailbox credential stored here, and "
                    "a short one is brute-forced offline if the file is copied.",
                )
                continue
            pw2, ok2 = _ask_password("Confirm", "Repeat the master password:")
            if not ok2:
                return False
            if pw != pw2:
                QMessageBox.warning(None, "Confirm", "Passwords do not match.")
                continue
            repo.initialize(pw)
            repo.purge_plaintext_remnants()
            return True


def _redirect_data_when_frozen() -> None:
    """In a packaged build, keep the store/history/settings in the user dir."""
    if not getattr(sys, "frozen", False):
        return
    from src.main.paths import data_dir

    d = data_dir()
    for var, name in (
        ("ACCOUNTS_ENC", "accounts.enc"),
        ("ACCOUNTS_FILE", "accounts.json"),
        ("MESSAGES_DB", "messages.db"),
        ("SETTINGS_FILE", "display_settings.json"),
    ):
        os.environ.setdefault(var, str(d / name))


def main() -> None:
    _redirect_data_when_frozen()
    # Windows groups taskbar icons by AppUserModelID — set one so the taskbar
    # shows our own icon rather than the generic Python one.
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "emailaggregator.desktop"
            )
        except Exception:
            pass

    # Required by QtWebEngine when used from a widgets app.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    if _APP_ICON.exists():
        app.setWindowIcon(QIcon(str(_APP_ICON)))
    fonts = qt_theme.load_fonts()
    app.setStyleSheet(qt_theme.stylesheet(fonts["sans"]))
    app.setFont(QFont(fonts["sans"], 10))

    # Unlock (or create) the encrypted account store before anything reads it.
    if not _unlock_accounts(container.account_repository()):
        sys.exit(0)

    window = MainWindow(MailService(container), fonts)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
