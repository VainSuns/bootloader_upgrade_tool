"""QSS theme loading for the PySide6 GUI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication


def load_theme(app: QApplication) -> None:
    path = Path(__file__).with_name("resources") / "styles" / "theme.qss"
    image_dir = path.parent.parent / "images"
    qss = path.read_text(encoding="utf-8").replace(
        "@CHEVRON_DOWN@", (image_dir / "chevron-down.svg").as_posix()
    )
    app.setStyleSheet(qss)
