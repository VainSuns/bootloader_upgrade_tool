"""Phase 11 PySide6 GUI entry point for static layout review.

The application configures only local GUI presentation. It does not create a
session, open serial/TCP transports, perform autobaud, invoke operations, write
Flash or metadata, transfer execution, reset hardware, or bring up CPU2/W5300.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtCore import QRect
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

from .main_window import BootloaderMainWindow
from .theme import apply_application_font, apply_palette_fallback, load_theme


def configure_application(app: QApplication) -> None:
    """Apply the frozen Fusion/font/palette/QSS chain."""

    if not isinstance(app, QApplication):
        raise TypeError("app must be a QApplication")

    fusion_style = QStyleFactory.create("Fusion")
    if fusion_style is None:
        raise RuntimeError("Qt Fusion style is unavailable")
    # Qt does not guarantee a generated style objectName across platforms.
    # Assign a stable diagnostic name after creating the actual Fusion style.
    fusion_style.setObjectName("fusion")

    app.setApplicationName("Bootloader")
    app.setStyle(fusion_style)
    apply_application_font(app)
    apply_palette_fallback(app)
    load_theme(app)


def center_window_on_screen(window: QWidget, screen: QScreen | None) -> None:
    """Center the first window inside the selected screen's available geometry."""

    if not isinstance(window, QWidget):
        raise TypeError("window must be a QWidget")
    if screen is None:
        return

    available: QRect = screen.availableGeometry()
    width = min(window.width(), available.width())
    height = min(window.height(), available.height())
    window.resize(max(window.minimumWidth(), width), max(window.minimumHeight(), height))

    frame = window.frameGeometry()
    x = (
        available.left() + (available.width() - frame.width()) // 2
        if frame.width() <= available.width()
        else available.left()
    )
    y = (
        available.top() + (available.height() - frame.height()) // 2
        if frame.height() <= available.height()
        else available.top()
    )
    window.move(x, y)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    app = QApplication(arguments)
    configure_application(app)

    window = BootloaderMainWindow()
    center_window_on_screen(window, app.primaryScreen())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
