"""Qt desktop integration kept outside filesystem services."""
from pathlib import Path
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices


def open_folder(folder_path):
    """Ask the desktop to open an existing folder, without launching a shell."""
    if not folder_path or not Path(folder_path).exists():
        raise ValueError("Folder not found")
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(folder_path).resolve()))):
        raise RuntimeError("The system could not open this folder")
