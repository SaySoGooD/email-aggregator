from __future__ import annotations

from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from src.infrastructure.gui.paths import resource_dir

BG = "#111110"
SURFACE_ALT = "#1a1a18"
SURFACE = "#232320"
ACCENT = "#f0b830"
ACCENT_HI = "#fce08a"
ACCENT_DIM = "#d47a0a"
TEXT = "#f0d090"
MUTED = "#a07840"
FAINT = "#604830"
BORDER = "rgba(200, 130, 20, 0.18)"
BORDER_SOFT = "rgba(200, 130, 20, 0.10)"
CARD_BG = "rgba(26, 26, 24, 0.92)"
NAV_BG = "rgba(17, 17, 16, 0.55)"

_FONTS_DIR = resource_dir() / "assets" / "fonts"


def apply_glow(widget: QWidget) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(26)
    effect.setColor(QColor(240, 160, 20, 150))
    effect.setOffset(0, 0)
    widget.setGraphicsEffect(effect)


def load_fonts() -> dict[str, str]:
    """Register the bundled Google fonts and return the resolved families."""
    serif, sans = "Georgia", "Segoe UI"
    for ttf in _FONTS_DIR.glob("*.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(ttf))
        if font_id == -1:
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if "Cormorant" in family:
                serif = family
            elif "Barlow" in family:
                sans = family
    return {"serif": serif, "sans": sans}


def stylesheet(sans: str) -> str:
    """Qt style sheet realising the neural-background look."""
    return f"""
    * {{
        color: {TEXT};
        font-family: "{sans}";
        font-size: 13px;
    }}

    QFrame#Nav {{
        background: {NAV_BG};
        border-bottom: 1px solid {BORDER};
    }}
    QLabel#Logo {{ color: {ACCENT}; }}
    QLabel#Tagline {{ color: {MUTED}; font-size: 11px; }}
    QLabel#Eyebrow {{ color: {ACCENT_DIM}; font-size: 11px; font-weight: 600; }}
    QLabel#Status {{ color: {MUTED}; font-size: 11px; padding: 4px 2px; }}

    QFrame#Card {{
        background: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 16px;
    }}

    QPushButton#Primary {{
        background: {ACCENT};
        color: {BG};
        border: none;
        border-radius: 6px;
        padding: 10px 24px;
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: {ACCENT_HI}; }}
    QPushButton#Primary:disabled {{ background: {FAINT}; color: {SURFACE_ALT}; }}

    QPushButton#Ghost {{
        background: transparent;
        color: {MUTED};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 10px 20px;
    }}
    QPushButton#Ghost:hover {{ color: {ACCENT}; border-color: {ACCENT}; }}

    QTreeWidget, QTreeView {{
        background: transparent;
        border: none;
        outline: 0;
    }}
    QTreeWidget::item {{ padding: 10px 6px; }}
    QTreeWidget::item:selected {{
        background: rgba(240, 184, 48, 0.16);
        color: {ACCENT_HI};
    }}
    QHeaderView::section {{
        background: transparent;
        color: {ACCENT};
        border: none;
        padding: 8px 4px;
        font-size: 11px;
        font-weight: 600;
    }}

    QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 8px;
        color: {TEXT};
        selection-background-color: {ACCENT};
        selection-color: {BG};
    }}
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border-color: {ACCENT};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT};
        selection-color: {BG};
        outline: 0;
    }}

    QListWidget {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 4px;
        outline: 0;
    }}
    QListWidget::item {{ padding: 8px; border-radius: 6px; }}
    QListWidget::item:selected {{ background: rgba(240, 184, 48, 0.16); color: {ACCENT_HI}; }}

    QFrame#Sidebar {{
        background: rgba(26, 26, 24, 0.92);
        border-right: 1px solid {BORDER};
    }}
    QPushButton#Side {{
        background: transparent;
        color: {MUTED};
        border: none;
        border-radius: 8px;
        padding: 11px 16px;
        text-align: left;
    }}
    QPushButton#Side:hover {{ color: {ACCENT}; background: rgba(240, 184, 48, 0.06); }}
    QPushButton#Side:checked {{
        color: {ACCENT_HI};
        background: rgba(240, 184, 48, 0.14);
        font-weight: 600;
    }}
    QPushButton#SubSide {{
        background: transparent;
        color: {MUTED};
        border: none;
        border-radius: 7px;
        padding: 7px 14px 7px 40px;
        text-align: left;
        font-size: 12px;
    }}
    QPushButton#SubSide:hover {{ color: {ACCENT}; background: rgba(240, 184, 48, 0.06); }}
    QPushButton#SubSide:checked {{
        color: {ACCENT_HI};
        background: rgba(240, 184, 48, 0.12);
        font-weight: 600;
    }}

    QFrame#LoadingBox {{
        background: rgba(35, 35, 32, 0.97);
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}
    QLabel#Loading {{ color: {ACCENT}; font-size: 15px; }}

    QTextBrowser {{ background: transparent; border: none; }}
    QLabel#Subject {{ color: {ACCENT_HI}; }}
    QLabel#Meta {{ color: {MUTED}; font-size: 12px; }}

    QCheckBox {{ color: {TEXT}; spacing: 8px; }}
    QCheckBox::indicator, QTreeView::indicator {{
        width: 17px; height: 17px;
        border: 1px solid {BORDER};
        border-radius: 4px;
        background: {SURFACE};
    }}
    QCheckBox::indicator:hover, QTreeView::indicator:hover {{ border-color: {ACCENT}; }}
    QCheckBox::indicator:checked, QTreeView::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QSlider::groove:horizontal {{
        height: 4px; background: {BORDER}; border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{ background: {ACCENT_DIM}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {ACCENT}; width: 16px; margin: -7px 0; border-radius: 8px;
    }}
    QSpinBox {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
        padding: 6px; color: {TEXT};
    }}

    QDialog {{ background: {BG}; }}

    QMenu {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{ padding: 7px 20px; border-radius: 6px; }}
    QMenu::item:selected {{ background: rgba(240, 184, 48, 0.16); color: {ACCENT_HI}; }}
    QMenu::item:disabled {{ color: {FAINT}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {FAINT}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """
