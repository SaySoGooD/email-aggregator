"""Entry point for the packaged desktop app."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox

from src.infrastructure.gui import qt_theme
from src.infrastructure.gui.mail_service import MailService
from src.infrastructure.gui.qt_gui import _ICONS_DIR, MainWindow
from src.main.dependency_injection import container

_APP_ICON = _ICONS_DIR / "app.png"
_MIN_MASTER_PASSWORD = 12


def _ask_password(title: str, label: str) -> tuple[str, bool]:
    return QInputDialog.getText(
        None, title, label, QLineEdit.EchoMode.Password
    )


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
    from src.infrastructure.gui.paths import data_dir

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
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "emailaggregator.desktop"
            )
        except Exception:
            pass

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    if _APP_ICON.exists():
        app.setWindowIcon(QIcon(str(_APP_ICON)))
    fonts = qt_theme.load_fonts()
    app.setStyleSheet(qt_theme.stylesheet(fonts["sans"]))
    app.setFont(QFont(fonts["sans"], 10))

    if not _unlock_accounts(container.account_repository()):
        sys.exit(0)

    window = MainWindow(MailService(container), fonts)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
