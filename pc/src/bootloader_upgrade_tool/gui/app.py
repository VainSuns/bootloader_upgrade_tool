"""Phase 11 PySide6 GUI entry point for static layout review.

This is a layout-only application.  It does not open serial ports, perform
autobaud, erase/program Flash, write metadata, or call any real hardware path.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import BootloaderMainWindow
from .styles import APP_QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Bootloader")
    app.setStyleSheet(APP_QSS)

    window = BootloaderMainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
