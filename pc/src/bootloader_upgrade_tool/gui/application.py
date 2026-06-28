"""Source-run PySide6 GUI entrypoint."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ..io import SerialIoDevice, SimulatorIoDevice
from .main_window import MainWindow
from .theme import load_theme


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    load_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()
