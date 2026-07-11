import importlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.app import configure_application, create_fusion_style
from bootloader_upgrade_tool.gui.theme_tokens import (
    APPLICATION_FONT_FAMILY,
    APPLICATION_FONT_POINT_SIZE,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_application_uses_fusion_font_palette_and_tokenized_qss() -> None:
    app = qt_app()

    fusion_style = create_fusion_style()
    try:
        style_class_name = fusion_style.metaObject().className().lower()
        assert "fusion" in style_class_name
    finally:
        fusion_style.deleteLater()
        app.processEvents()

    configure_application(app)

    assert app.font().family() == APPLICATION_FONT_FAMILY
    assert app.font().pointSize() == APPLICATION_FONT_POINT_SIZE
    assert app.styleSheet()
    assert "@WINDOW_BG@" not in app.styleSheet()


def test_legacy_styles_module_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bootloader_upgrade_tool.gui.styles")
