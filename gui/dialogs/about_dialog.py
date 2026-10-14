"""Non-modal, source-backed identity/citation with explicit safe web actions."""
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QImageReader, QPixmap

from ...services.plugin_info import safe_web_url
from ..widgets import visual_style
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
        body.setSpacing(10)
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(14)
        self.logo_label = QtWidgets.QLabel()
        if plugin_info.logo_path:
            reader = QImageReader(str(plugin_info.logo_path))
            size = reader.size()
            if 0 < size.width() <= 4096 and 0 < size.height() <= 4096 and size.width() * size.height() <= 8_000_000:
                pixmap = QPixmap.fromImage(reader.read())
                if not pixmap.isNull():
                    self.logo_label.setPixmap(pixmap.scaled(120, 48, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                    header.addWidget(self.logo_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.identity_label = self._label(f"{plugin_info.name} · {plugin_info.version}")
        visual_style.set_font(self.identity_label, delta=3, bold=True)
        header.addWidget(self.identity_label, 1)
        body.addLayout(header)
        body.addWidget(self._label(plugin_info.about or plugin_info.description))
        body.addWidget(self._heading("Authors and contact"))
        self.author_label = self._label("Packaged authors / team\n" + (plugin_info.author or "Not recorded in packaged metadata"))
        body.addWidget(self.author_label)
        self.email_label = self._label("Contact: " + (plugin_info.email or "Not recorded"))
        body.addWidget(self.email_label)
        body.addWidget(self._heading("Licensing"))
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
            body.addWidget(self._heading("Links (open in your browser only when clicked)"))
            body.addLayout(link_grid)
        self.citation = QtWidgets.QPlainTextEdit()
        self.citation.setReadOnly(True)
        self.citation.setPlainText(plugin_info.citation or "No citation block was found in the packaged README.")
        self.citation.setMaximumHeight(170)
        body.addWidget(self._heading("Citation from the packaged README"))
        body.addWidget(self.citation)
        self.copy_citation_button = QtWidgets.QPushButton("Copy citation")
        self.copy_citation_button.setEnabled(bool(plugin_info.citation))
        self.copy_citation_button.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(self.citation.toPlainText()))
        body.addWidget(self.copy_citation_button, 0, Qt.AlignmentFlag.AlignLeft)
        if plugin_info.warnings:
            body.addWidget(self._label("Package information diagnostics\n" + "\n".join(plugin_info.warnings)))
        body.addStretch()
        layout.addWidget(scroll, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

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

    def _heading(self, text):
        label = self._label(text)
        visual_style.set_font(label, bold=True)
        return label

    def _open_web(self, url):
        url = safe_web_url(url)
        if not url:
            return False
        return QDesktopServices.openUrl(QUrl(url))
