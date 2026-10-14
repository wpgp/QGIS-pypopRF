"""Plain-text label limited to a number of rendered lines, for compact footers."""
import math

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QEvent, QRect, QSize, Qt
from qgis.PyQt.QtGui import QPainter, QTextLayout, QTextOption

from .workflow_status import plain_tooltip

# Events after which the same text can render with different metrics.
_METRIC_EVENTS = {getattr(QEvent.Type, name) for name in
                  ("FontChange", "ApplicationFontChange", "StyleChange", "ScreenChangeInternal",
                   "DevicePixelRatioChange") if hasattr(QEvent.Type, name)}


def _flags(value):
    """Qt5 QFlags and Qt6 enum flags as a plain int."""
    return value.value if hasattr(value, "value") else int(value)


class FittedLabel(QtWidgets.QLabel):
    """Wraps plain text into at most ``max_lines`` lines of the current width and font.

    ``text()`` keeps the complete (caller-bounded) message; only the painted
    presentation is fitted and ends with "…" when it does not fit. Fitting is
    recomputed from the current width, font and DPI, never from earlier output,
    so a wider label shows more again. Unbroken runs such as paths wrap anywhere
    instead of demanding width. The full text stays in the escaped tooltip and
    in the label's own accessible text.
    """

    MIN_CHARS = 16
    HINT_CHARS = 60

    def __init__(self, parent=None, max_lines=2):
        super().__init__(parent)
        self._max_lines = max(1, int(max_lines))
        self._fits = {}
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        # The painted lines differ from text(); a mouse selection would select hidden text.
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def setText(self, text):
        text = str(text)
        super().setText(text)
        self.setToolTip(plain_tooltip(text) if text.strip() else "")

    def displayed_lines(self, width=None):
        """Lines painted at ``width`` (default: the current width), for tests and diagnostics."""
        return self._fit(self._text_width(self.width() if width is None else width))[0]

    def _extra(self):
        margins = self.contentsMargins()
        spare = 2 * (self.margin() + self.frameWidth())
        return (margins.left() + margins.right() + spare + max(0, self.indent()),
                margins.top() + margins.bottom() + spare)

    def _text_width(self, width):
        return max(1, int(width) - self._extra()[0])

    def _fit(self, width):
        """(lines, line heights) for ``width``; a small bounded cache per text/font/DPI."""
        text = self.text()
        key = (width, text, self.font().key(), self.logicalDpiY(), self.devicePixelRatioF())
        fit = self._fits.get(key)
        if fit is not None:
            return fit
        metrics = self.fontMetrics()
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        lines, heights, cut, following = [], [], False, []
        paragraphs = [part for part in text.split("\n") if part.strip()]
        for index, paragraph in enumerate(paragraphs):
            if len(lines) == self._max_lines:
                cut, following = True, paragraphs[index:]
                break
            # QTextLine offsets count UTF-16 units, not Python characters.
            units = paragraph.encode("utf-16-le")
            layout = QTextLayout(paragraph, self.font(), self)
            layout.setTextOption(option)
            layout.beginLayout()
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(width)
                if len(lines) == self._max_lines:
                    cut, following = True, paragraphs[index + 1:]
                    break
                start = 2 * line.textStart()
                end = start + 2 * line.textLength()
                lines.append((units[start:], units[start:end].decode("utf-16-le", "replace").rstrip()))
                heights.append(max(metrics.height(), math.ceil(line.height())))
            layout.endLayout()
            if cut:
                break
        if cut and lines:
            # The last line carries the rest of its paragraph and what follows, elided to fit.
            rest = lines[-1][0].decode("utf-16-le", "replace").strip()
            tail = " ".join([rest] + [part.strip() for part in following])
            lines[-1] = (b"", metrics.elidedText(tail, Qt.TextElideMode.ElideRight, width))
        fit = (tuple(line[1] for line in lines), tuple(heights))
        if len(self._fits) >= 16:
            self._fits.clear()
        self._fits[key] = fit
        return fit

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        heights = self._fit(self._text_width(width))[1]
        return (sum(heights) if heights else self.fontMetrics().height()) + self._extra()[1]

    def minimumSizeHint(self):
        # Wrapping is greedy, so the narrowest width needs the most lines: this
        # height covers every wider allocation even when the layout is squeezed.
        width = self.fontMetrics().averageCharWidth() * self.MIN_CHARS + self._extra()[0]
        return QSize(width, self.heightForWidth(width))

    def sizeHint(self):
        metrics = self.fontMetrics()
        longest = max((metrics.horizontalAdvance(part) for part in self.text().split("\n")), default=0)
        width = max(metrics.averageCharWidth() * self.MIN_CHARS,
                    min(longest, metrics.averageCharWidth() * self.HINT_CHARS)) + self._extra()[0]
        return QSize(width, self.heightForWidth(width))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in _METRIC_EVENTS:
            self._fits.clear()
            self.updateGeometry()

    def paintEvent(self, event):
        lines, heights = self._fit(self._text_width(self.width()))
        if not lines:
            return
        rect = self.contentsRect().adjusted(self.margin(), self.margin(), -self.margin(), -self.margin())
        if self.indent() > 0:
            rect.setLeft(rect.left() + self.indent())
        option = QtWidgets.QStyleOption()
        option.initFrom(self)
        align = _flags(QtWidgets.QStyle.visualAlignment(self.layoutDirection(), self.alignment()))
        total = sum(heights)
        top = rect.top()
        if align & _flags(Qt.AlignmentFlag.AlignBottom):
            top = rect.bottom() + 1 - total
        elif not align & _flags(Qt.AlignmentFlag.AlignTop):
            top = rect.top() + (rect.height() - total) // 2
        top = max(rect.top(), top)
        flags = (align & _flags(Qt.AlignmentFlag.AlignHorizontal_Mask)) | _flags(Qt.AlignmentFlag.AlignVCenter)
        painter = QPainter(self)
        try:
            for text, height in zip(lines, heights):
                self.style().drawItemText(painter, QRect(rect.left(), top, rect.width(), height), flags,
                                          option.palette, self.isEnabled(), text, self.foregroundRole())
                top += height
        finally:
            painter.end()
