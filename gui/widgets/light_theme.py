"""One plugin-owned light color scheme, scoped to its windows and descendants.

Never changes QApplication's palette, stylesheet, style, font or settings.
Native operating-system file dialogs remain operating-system controlled.
"""
from pathlib import Path

from qgis.PyQt.QtCore import QEvent, QObject
from qgis.PyQt.QtGui import QColor, QIcon, QPalette

WINDOW = "#ffffff"
TEXT = "#0f172a"
MUTED = "#475569"
ACCENT = "#1d4ed8"
DISABLED = "#64748b"
SURFACE = "#f8fafc"
BORDER = "#cbd5e1"


def palette():
    """A fresh complete palette; no colors are borrowed from the host theme."""
    result = QPalette()
    roles = QPalette.ColorRole
    values = {"Window": WINDOW, "WindowText": TEXT, "Base": WINDOW,
              "AlternateBase": SURFACE, "Text": TEXT, "Button": SURFACE,
              "ButtonText": TEXT, "BrightText": WINDOW, "Highlight": ACCENT,
              "HighlightedText": WINDOW, "ToolTipBase": WINDOW, "ToolTipText": TEXT,
              "Light": WINDOW, "Midlight": SURFACE, "Mid": BORDER, "Dark": DISABLED,
              "Shadow": MUTED, "Link": ACCENT, "LinkVisited": "#6d28d9",
              "PlaceholderText": DISABLED, "Accent": ACCENT}
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for name, color in values.items():
            if hasattr(roles, name):
                result.setColor(group, getattr(roles, name), QColor(color))
    for name in ("WindowText", "Text", "ButtonText", "HighlightedText"):
        result.setColor(QPalette.ColorGroup.Disabled, getattr(roles, name), QColor(DISABLED))
    result.setColor(QPalette.ColorGroup.Disabled, roles.Highlight, QColor("#e2e8f0"))
    return result


def _icon(name):
    # Quoted absolute Qt URLs work with plugin paths containing spaces on Windows.
    path = (Path(__file__).resolve().parents[1] / "icons" / name).as_posix()
    return 'url("' + path.replace('"', '%22') + '")'


def action_icon(role):
    """Packaged run/stop glyphs, including an explicit disabled color."""
    root = Path(__file__).resolve().parents[1] / "icons"
    name = "play" if role == "run" else "stop"
    result = QIcon()
    result.addFile(str(root / (name + ".svg")), mode=QIcon.Mode.Normal)
    result.addFile(str(root / (name + "-disabled.svg")), mode=QIcon.Mode.Disabled)
    return result


def stylesheet():
    """Window-local rules override inherited host QSS, not just its palette."""
    check, partial, down, up, dot = (_icon(name) for name in
                                   ("check.svg", "partial.svg", "down.svg", "up.svg", "radio.svg"))
    return f"""
QWidget {{ background-color: {WINDOW}; color: {TEXT};
           selection-background-color: {ACCENT}; selection-color: {WINDOW}; }}
QFrame {{ border: none; }}
QFrame#runFooterLine {{ border-top: 1px solid #e2e8f0; min-height: 1px; max-height: 1px; }}
QLabel, QCheckBox, QRadioButton {{ background-color: transparent; }}
QWidget:disabled {{ color: {DISABLED}; }}
QToolTip {{ background-color: {WINDOW}; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 5px; margin-top: 10px; padding-top: 7px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 9px; padding: 0 4px; color: {TEXT}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; background: {WINDOW}; }}
QTabBar::tab {{ background: {SURFACE}; color: {MUTED}; border: 1px solid {BORDER};
               padding: 5px 9px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {WINDOW}; color: {ACCENT}; border-bottom-color: {WINDOW}; }}
QTabBar::tab:hover:!selected {{ background: #eff6ff; color: {TEXT}; }}
QPushButton, QToolButton {{ background-color: {SURFACE}; color: {TEXT};
                         border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 9px; }}
QPushButton:hover, QToolButton:hover {{ background-color: #eff6ff; border-color: #93c5fd; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: #dbeafe; }}
QPushButton:focus, QToolButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled, QToolButton:disabled {{ background-color: {SURFACE}; color: {DISABLED}; }}
QToolButton[pypoprfReadiness="true"] {{ background-color: transparent; border: none; padding: 3px 4px; }}
QToolButton[pypoprfReadiness="true"]:hover {{ background-color: #eff6ff; }}
QToolButton[pypoprfReadiness="true"]:focus {{ background-color: #dbeafe; }}
QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{ background-color: {WINDOW};
    color: {TEXT}; border: 1px solid {BORDER}; border-radius: 3px; padding: 3px 5px; }}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled, QTextEdit:disabled,
QPlainTextEdit:disabled {{ background-color: {SURFACE}; color: {DISABLED}; }}
QComboBox {{ padding-right: 24px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right;
                      width: 22px; border: none; background: transparent; }}
QComboBox::down-arrow {{ image: {down}; width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background-color: {WINDOW}; color: {TEXT};
    selection-background-color: {ACCENT}; selection-color: {WINDOW}; border: 1px solid {BORDER}; }}
QAbstractSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border;
    subcontrol-position: top right; width: 20px; border: none; background: {SURFACE}; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border;
    subcontrol-position: bottom right; width: 20px; border: none; background: {SURFACE}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: {up}; width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: {down}; width: 10px; height: 10px; }}
QAbstractItemView {{ background-color: {WINDOW}; alternate-background-color: {SURFACE};
    color: {TEXT}; selection-background-color: {ACCENT}; selection-color: {WINDOW};
    border: 1px solid {BORDER}; gridline-color: #e2e8f0; }}
QAbstractItemView::item:selected {{ background-color: {ACCENT}; color: {WINDOW}; }}
QAbstractItemView::item:selected:!active {{ background-color: {ACCENT}; color: {WINDOW}; }}
QHeaderView::section {{ background-color: {SURFACE}; color: {MUTED};
    border: none; border-right: 1px solid {BORDER}; border-bottom: 1px solid {BORDER}; padding: 4px; }}
QTableCornerButton::section {{ background-color: {SURFACE}; border: 1px solid {BORDER}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px;
    background-color: {WINDOW}; border: 1px solid #94a3b8; border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked {{ background-color: {ACCENT}; border-color: {ACCENT}; image: {check}; }}
QCheckBox::indicator:indeterminate {{ background-color: {ACCENT}; border-color: {ACCENT}; image: {partial}; }}
QRadioButton::indicator:checked {{ background-color: {ACCENT}; border-color: {ACCENT}; image: {dot}; }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: {BORDER}; }}
QCheckBox::indicator:checked:disabled, QCheckBox::indicator:indeterminate:disabled,
QRadioButton::indicator:checked:disabled {{ background-color: #94a3b8; border-color: #94a3b8; }}
QProgressBar {{ background-color: #eff6ff; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 3px; text-align: center; }}
QProgressBar::chunk {{ background-color: #93c5fd; border-radius: 2px; }}
QScrollBar:vertical {{ background: {SURFACE}; width: 13px; margin: 0; }}
QScrollBar:horizontal {{ background: {SURFACE}; height: 13px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #94a3b8; min-height: 26px; border-radius: 5px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #94a3b8; min-width: 26px; border-radius: 5px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {DISABLED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{ background-color: {WINDOW}; color: {TEXT}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background-color: {ACCENT}; color: {WINDOW}; }}
"""


class _ThemeGuard(QObject):
    """Keep owned windows light when the application's theme changes while open."""
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._updating = False

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange,
                            QEvent.Type.StyleChange):
            self.ensure_palette()
        return False

    def ensure_palette(self):
        if self._updating:
            return
        wanted = palette()
        current = self.window.palette()
        roles = QPalette.ColorRole
        if all(current.color(group, role) == wanted.color(group, role)
               for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                             QPalette.ColorGroup.Disabled)
               for role in (roles.Window, roles.WindowText, roles.Base, roles.Text,
                            roles.Highlight, roles.HighlightedText)):
            return
        self._updating = True
        try:
            self.window.setPalette(wanted)
        finally:
            self._updating = False


def apply_light_theme(window):
    """Apply once to each plugin-owned window; safe to call again, no global writes."""
    guard = getattr(window, "_pypoprf_light_theme", None)
    if guard is None:
        guard = _ThemeGuard(window)
        window._pypoprf_light_theme = guard  # retain the Python event-filter wrapper
        window.setPalette(palette())
        window.setStyleSheet(stylesheet())
        window.installEventFilter(guard)
    guard.ensure_palette()
