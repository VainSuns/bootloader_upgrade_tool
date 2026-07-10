import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.app import configure_application
from bootloader_upgrade_tool.gui.theme_tokens import (
    APPLICATION_FONT_FAMILY,
    APPLICATION_FONT_POINT_SIZE,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_application_uses_fusion_font_palette_and_tokenized_qss() -> None:
    app = qt_app()
    configure_application(app)

    assert app.style().objectName().lower() == "fusion"
    assert app.font().family() == APPLICATION_FONT_FAMILY
    assert app.font().pointSize() == APPLICATION_FONT_POINT_SIZE
    assert app.styleSheet()
    assert "@WINDOW_BG@" not in app.styleSheet()


def test_legacy_styles_module_has_no_runtime_qss_source() -> None:
    from bootloader_upgrade_tool.gui import styles

    assert not hasattr(styles, "APP_QSS")
