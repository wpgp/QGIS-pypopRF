"""Bounded native task history with elapsed time, never an invented ETA."""
import time

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QTimer

from .fitted_label import FittedLabel


class TaskActivity(FittedLabel):
    def __init__(self, parent=None):
        # Footer line: long stages are fitted to two rendered lines; history keeps them whole.
        super().__init__(parent, max_lines=2)
        self.setObjectName("taskActivityLabel")
        # Wrapped footer text must report its real height, or long stages are clipped.
        policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                       QtWidgets.QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.history = QtWidgets.QTreeWidget(parent)
        self.history.setObjectName("taskHistory")
        self.history.setHeaderLabels(["Elapsed", "Task / stage"])
        self.history.setAlternatingRowColors(True)
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
