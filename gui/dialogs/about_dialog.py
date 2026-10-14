"""Non-modal, source-backed identity/citation with explicit safe web actions."""
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices

from ...services.plugin_info import safe_web_url
from ..widgets.workflow_status import plain_tooltip


class AboutDialog(QtWidgets.QDialog):
    def __init__(self, plugin_info, parent=None):
        super().__init__(parent)
        self.plugin_info = plugin_info
        self.setWindowTitle(f"About {plugin_info.name}")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(720, 580)
        self.setMinimumSize(520, 360)
        layout = QtWidgets.QVBoxLayout(self)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget()
        scroll.setWidget(content)
        body = QtWidgets.QVBoxLayout(content)
        self.identity_label = self._label(f"{plugin_info.name} · {plugin_info.version}")
        font = self.identity_label.font()
        font.setBold(True)
        self.identity_label.setFont(font)
        body.addWidget(self.identity_label)
        self.author_label = self._label("Packaged authors / team\n" + (plugin_info.author or "Not recorded in packaged metadata"))
        body.addWidget(self.author_label)
        self.email_label = self._label("Contact: " + (plugin_info.email or "Not recorded"))
        body.addWidget(self.email_label)
        body.addWidget(self._label(plugin_info.about or plugin_info.description))
        self.license_label = self._label("Licensing\n" + plugin_info.license_notice)
        body.addWidget(self.license_label)
        self.link_buttons = []
        link_grid = QtWidgets.QGridLayout()
        for link in plugin_info.links:
            url = safe_web_url(link.url)
            if not url:
                continue
            button = QtWidgets.QPushButton(link.label)
            button.setToolTip(plain_tooltip(url))
            button.clicked.connect(lambda checked=False, destination=url: self._open_web(destination))
            self.link_buttons.append(button)
            index = len(self.link_buttons) - 1
            link_grid.addWidget(button, index // 2, index % 2)
        # Separate rows keep links reachable on small/dense native displays.
        if self.link_buttons:
            body.addLayout(link_grid)
        self.citation = QtWidgets.QPlainTextEdit()
        self.citation.setReadOnly(True)
        self.citation.setPlainText(plugin_info.citation or "No citation block was found in the packaged README.")
        self.citation.setMaximumHeight(170)
        body.addWidget(self._label("Citation from the packaged README"))
        body.addWidget(self.citation)
        if plugin_info.warnings:
            body.addWidget(self._label("Package information diagnostics\n" + "\n".join(plugin_info.warnings)))
        body.addStretch()
        layout.addWidget(scroll, 1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    @staticmethod
    def _label(text):
        label = QtWidgets.QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                      QtWidgets.QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        label.setSizePolicy(policy)
        return label

    def _open_web(self, url):
        url = safe_web_url(url)
        if not url:
            return False
        return QDesktopServices.openUrl(QUrl(url))
