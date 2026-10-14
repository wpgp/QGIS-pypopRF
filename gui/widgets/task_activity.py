"""Bounded native task history with elapsed time, never an invented ETA."""
import time

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QTimer, Qt


class TaskActivity(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.history = QtWidgets.QTreeWidget(parent)
        self.history.setHeaderLabels(["Elapsed", "Task / stage"])
        self.history.setRootIsDecorated(False)
        self.history.setMaximumHeight(140)
        self.history.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.history.setColumnWidth(0, 75)
        self.active = False
        self.started = None
        self.stopped = None
        self.stage = ""
        self._last = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh)
        self.hide()
        self.history.hide()

    def elapsed(self):
        end = self.stopped if self.stopped is not None else time.monotonic()
        seconds = int(max(0, end - self.started)) if self.started is not None else 0
        return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"

    def begin(self, title):
        if self.active:
            return
        self.started = time.monotonic()
        self.stopped = None
        self.active = True
        self._last = None
        self.history.clear()
        self.timer.start()
        self.record(title)

    def record(self, message):
        message = str(message).strip()
        if not message:
            return
        self.stage = message.splitlines()[-1][:180]
        if message != self._last:
            item = QtWidgets.QTreeWidgetItem([self.elapsed(), message[:2000]])
            self.history.addTopLevelItem(item)
            if self.history.topLevelItemCount() > 80:
                self.history.takeTopLevelItem(0)
            self.history.scrollToItem(item)
            self._last = message
        self.show()
        self.history.show()
        self._refresh()

    def finish(self):
        if not self.active:
            return
        self.active = False
        self.stopped = time.monotonic()
        self._refresh()
        self.timer.stop()

    def _refresh(self):
        self.setText(f"{'Working' if self.active else 'Last task'} · {self.elapsed()} · {self.stage}")
