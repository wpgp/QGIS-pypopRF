"""Scoped appearance derived from the native palette.

No application stylesheet, font or environment is changed. Styles are set on
individual widgets, computed from the owning window's QPalette and re-applied
by the owner on palette changes, so light, dark and QGIS themes stay coherent.
"""
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QPalette

Role = QPalette.ColorRole
Group = QPalette.ColorGroup

# (light palette, dark palette) semantic accents, used only for edges/strips;
# text always stays in palette colors.
_SEMANTIC = {"success": ("#2e7d32", "#81c784"), "warning": ("#9a5b00", "#ffb74d"),
             "critical": ("#b3261e", "#f28b82"), "info": (None, None)}


def mix(first, second, amount):
    """Linear blend; ``amount`` is the share of ``second``."""
    a, b = QColor(first), QColor(second)
    t = max(0.0, min(1.0, float(amount)))
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def _luminance(color):
    def channel(value):
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    color = QColor(color)
    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def contrast(first, second):
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def window_palette(widget):
    """Palette of the owning window; widget stylesheets can alter a widget's own palette."""
    return widget.window().palette()


def is_dark(palette):
    return _luminance(palette.color(Group.Active, Role.Window)) < 0.25


def semantic(palette, kind):
    light, dark = _SEMANTIC.get(kind, (None, None))
    if light is None:
        return palette.color(Group.Active, Role.Highlight)
    return QColor(dark if is_dark(palette) else light)


def readable_on(background, *candidates):
    return max(candidates, key=lambda color: contrast(background, color))


def _css(color):
    return QColor(color).name()


def wrap_label(label, selectable=False):
    """Plain wrapped text that reports height-for-width (prevents clipped labels)."""
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                   QtWidgets.QSizePolicy.Policy.Preferred)
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def set_font(widget, delta=0.0, bold=None):
    """Relative font change, so user/QGIS font size and DPI scaling are respected.

    Call once per widget at construction; it is relative to the inherited font.
    """
    font = widget.font()
    if delta:
        size = font.pointSizeF()
        if size > 0:
            font.setPointSizeF(size + delta)
    if bold is not None:
        font.setBold(bold)
    widget.setFont(font)


_MUTED = "pypoprfMutedText"


def muted(label):
    """Secondary text: palette text blended towards the window color (stays legible)."""
    base = window_palette(label)
    palette = QPalette(label.palette())
    for group in (Group.Active, Group.Inactive):
        palette.setColor(group, Role.WindowText,
                         mix(base.color(group, Role.WindowText), base.color(group, Role.Window), 0.3))
    label.setPalette(palette)
    label.setProperty(_MUTED, True)  # card() keeps it secondary when re-asserting foregrounds


def host_foreground(widget):
    """Give ``widget`` the owning window's text color explicitly.

    Polishing a widget stylesheet freezes the palette of the styled widget and
    its descendants as it was at that moment (typically the application palette),
    so a later host-window palette (dark QGIS theme) no longer reaches their
    text. Re-assert it after every stylesheet change; scoped to this widget only.
    """
    base = window_palette(widget)
    palette = QPalette(widget.palette())
    for group in (Group.Active, Group.Inactive, Group.Disabled):
        palette.setColor(group, Role.WindowText, base.color(group, Role.WindowText))
    widget.setPalette(palette)


def card(frame, accent=None):
    """Subtle panel with an optional semantic strip; ``frame`` needs an objectName."""
    base = window_palette(frame)
    window, text = base.color(Group.Active, Role.Window), base.color(Group.Active, Role.WindowText)
    background = mix(window, base.color(Group.Active, Role.Base), 0.5)
    border = mix(window, text, 0.18)
    strip = semantic(base, accent) if accent else border
    frame.setStyleSheet(
        f"QFrame#{frame.objectName()} {{ background-color: {_css(background)}; "
        f"border: 1px solid {_css(border)}; border-left: 4px solid {_css(strip)}; border-radius: 6px; }}")
    # Text drawn on the card follows the host window, not the frozen polish-time palette.
    for label in frame.findChildren(QtWidgets.QLabel):
        if label.property(_MUTED):
            muted(label)
        else:
            host_foreground(label)


def message(label, kind="critical"):
    """Inline diagnostic box; text remains the host window's palette text color."""
    base = window_palette(label)
    window = base.color(Group.Active, Role.Window)
    edge = semantic(base, kind)
    label.setStyleSheet(
        f"QLabel#{label.objectName()} {{ background-color: {_css(mix(window, edge, 0.12))}; "
        f"border-left: 3px solid {_css(edge)}; border-radius: 3px; padding: 6px 8px; }}")
    host_foreground(label)


def action_button(button, role="normal"):
    """Primary / stop / stopping push-button presentation; ``normal`` restores native.

    Only appearance changes; enabled state and text are owned by the callers.
    """
    if role == "normal":
        button.setStyleSheet("")
        return
    base = window_palette(button)
    window = base.color(Group.Active, Role.Window)
    text = base.color(Group.Active, Role.WindowText)
    face = base.color(Group.Active, Role.Button)
    face_text = base.color(Group.Active, Role.ButtonText)
    critical = semantic(base, "critical")
    disabled_text = base.color(Group.Disabled, Role.ButtonText)
    if contrast(mix(window, face, 0.5), disabled_text) < 2.0:
        disabled_text = mix(text, window, 0.45)
    padding = "7px 20px"
    focus_padding = "6px 19px"
    if role == "primary":
        accent = base.color(Group.Active, Role.Highlight)
        label = readable_on(accent, base.color(Group.Active, Role.HighlightedText),
                            base.color(Group.Active, Role.Base), text)
        hover = accent.lighter(112) if is_dark(base) else accent.darker(108)
        pressed = accent.darker(118)
        normal = (f"background-color: {_css(accent)}; color: {_css(label)}; "
                  f"border: 1px solid {_css(accent.darker(115))};")
        disabled = (f"background-color: {_css(mix(window, face, 0.5))}; color: {_css(disabled_text)}; "
                    f"border: 1px solid {_css(mix(window, text, 0.2))};")
    else:
        hover = mix(face, critical, 0.18)
        pressed = mix(face, critical, 0.3)
        normal = (f"background-color: {_css(face)}; color: {_css(face_text)}; "
                  f"border: 2px solid {_css(critical)};")
        if role == "stopping":
            disabled = (f"background-color: {_css(mix(window, critical, 0.08))}; "
                        f"color: {_css(mix(text, window, 0.3))}; border: 2px dashed {_css(critical)};")
        else:
            disabled = (f"background-color: {_css(mix(window, face, 0.5))}; color: {_css(disabled_text)}; "
                        f"border: 2px solid {_css(mix(window, critical, 0.4))};")
        padding, focus_padding = "6px 19px", "6px 19px"
    focus_border = "2px solid " + _css(text)
    button.setStyleSheet(
        f"QPushButton {{ {normal} border-radius: 4px; padding: {padding}; }}"
        f"QPushButton:hover {{ background-color: {_css(hover)}; }}"
        f"QPushButton:pressed {{ background-color: {_css(pressed)}; }}"
        f"QPushButton:focus {{ border: {focus_border}; padding: {focus_padding}; }}"
        f"QPushButton:disabled {{ {disabled} }}")
