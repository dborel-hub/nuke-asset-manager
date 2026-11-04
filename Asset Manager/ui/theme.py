"""
Theme - "dark modern" palette and stylesheet for the Asset Manager
All colours live here so the look can be tweaked in one place.
"""

# Palette
BG_WINDOW = "#121417"   # main background / grid
BG_PANEL = "#171a1f"    # sidebar, top bar, info bar
BG_FIELD = "#1d2127"    # inputs, cards, hover
BORDER = "#252a32"
TEXT = "#d7dce2"
TEXT_DIM = "#8a93a0"
TEXT_FAINT = "#5c6470"
ACCENT = "#3fb7d9"      # soft cyan
ACCENT_BG = "rgba(63, 183, 217, 0.14)"
DANGER = "#e06c75"

FONT_SIZE = 12


def stylesheet():
    return f"""
    QWidget {{
        color: {TEXT};
        font-size: {FONT_SIZE}px;
    }}
    QWidget#amRoot {{ background: {BG_WINDOW}; }}

    /* ---- bars ---- */
    QWidget#amTopBar {{
        background: {BG_PANEL};
        border-bottom: 1px solid {BORDER};
    }}
    QWidget#amSidebar {{
        background: {BG_PANEL};
        border-right: 1px solid {BORDER};
    }}
    QWidget#amInfoBar {{
        background: {BG_PANEL};
        border-top: 1px solid {BORDER};
    }}
    QLabel#amTitle {{
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
    }}
    QLabel#amDim {{ color: {TEXT_DIM}; }}
    QLabel#amInfoName {{ color: {TEXT}; font-weight: 600; }}
    QLabel#amInfoMeta {{ color: {TEXT_DIM}; }}
    QLabel#amSection {{
        color: {TEXT_FAINT};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1px;
        padding: 14px 14px 4px 14px;
    }}

    /* ---- inputs ---- */
    QLineEdit {{
        background: {BG_FIELD};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 10px;
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus {{ border-color: {ACCENT}; }}

    QPushButton, QToolButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 5px 10px;
        color: {TEXT_DIM};
    }}
    QPushButton:hover, QToolButton:hover {{
        background: {BG_FIELD};
        color: {TEXT};
    }}
    QToolButton:checked {{
        background: {ACCENT_BG};
        color: {ACCENT};
    }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    QPushButton#amAddButton {{
        background: {ACCENT_BG};
        color: {ACCENT};
        font-weight: 600;
        text-align: left;
        padding: 7px 12px;
    }}
    QPushButton#amAddButton:hover {{ background: rgba(63, 183, 217, 0.22); }}
    QPushButton#amAddButton::menu-indicator {{ image: none; width: 0; }}

    QSlider#amSizeSlider::groove:horizontal {{
        height: 3px;
        background: {BORDER};
        border-radius: 1px;
    }}
    QSlider#amSizeSlider::sub-page:horizontal {{
        background: {TEXT_FAINT};
        border-radius: 1px;
    }}
    QSlider#amSizeSlider::handle:horizontal {{
        background: {TEXT_DIM};
        width: 12px;
        height: 12px;
        margin: -5px 0;
        border-radius: 6px;
    }}
    QSlider#amSizeSlider::handle:horizontal:hover {{ background: {ACCENT}; }}
    QSlider#amSizeSlider:disabled {{ opacity: 0.4; }}

    QProgressBar#amWorkBar {{
        background: {BORDER};
        border: none;
        border-radius: 2px;
    }}
    QProgressBar#amWorkBar::chunk {{
        background: {ACCENT};
        border-radius: 2px;
    }}

    /* ---- sidebar lists ---- */
    QListWidget#amNavList {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QListWidget#amNavList::item {{
        padding: 6px 12px;
        margin: 1px 6px;
        border-radius: 6px;
        color: {TEXT_DIM};
    }}
    QListWidget#amNavList::item:hover {{
        background: {BG_FIELD};
        color: {TEXT};
    }}
    QListWidget#amNavList::item:selected {{
        background: {ACCENT_BG};
        color: {ACCENT};
    }}

    QTreeWidget#amNavTree {{
        background: transparent;
        border: none;
        outline: none;
        show-decoration-selected: 0;
    }}
    QTreeWidget#amNavTree::item {{
        padding: 5px 6px;
        margin: 1px 6px;
        border-radius: 6px;
        color: {TEXT_DIM};
    }}
    QTreeWidget#amNavTree::item:hover {{ background: {BG_FIELD}; color: {TEXT}; }}
    QTreeWidget#amNavTree::item:selected {{ background: {ACCENT_BG}; color: {ACCENT}; }}
    QTreeWidget#amNavTree::branch {{ background: transparent; image: none; border: none; }}
    QTreeWidget#amNavTree::branch:selected, QTreeWidget#amNavTree::branch:hover {{ background: transparent; }}

    /* ---- grid ---- */
    QListWidget#assetList {{
        background: {BG_WINDOW};
        border: none;
        outline: none;
    }}

    /* ---- menus, tooltips, scrollbars ---- */
    QMenu {{
        background: {BG_FIELD};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {ACCENT_BG}; color: {ACCENT}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
    QToolTip {{
        background: {BG_FIELD};
        color: {TEXT};
        border: 1px solid {BORDER};
        padding: 4px 6px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER};
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; height: 0; width: 0;
    }}
    QScrollBar:horizontal {{ height: 0; }}

    QMessageBox, QProgressDialog, QInputDialog {{ background: {BG_PANEL}; }}
    """


# Backwards compatibility with old imports (ModernTheme.get_stylesheet())
class ModernTheme(object):
    @staticmethod
    def get_stylesheet():
        return stylesheet()
