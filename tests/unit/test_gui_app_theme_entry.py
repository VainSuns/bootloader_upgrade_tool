import importlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_read_binding import AdvancedReadOnlyBinding
from bootloader_upgrade_tool.gui.advanced_ram_binding import AdvancedRamBinding
from bootloader_upgrade_tool.gui.advanced_flash_binding import AdvancedFlashBinding
from bootloader_upgrade_tool.gui.advanced_flash_operation_binding import AdvancedFlashOperationBinding
from bootloader_upgrade_tool.gui.advanced_metadata_binding import AdvancedMetadataOperationBinding
from bootloader_upgrade_tool.gui.flash_service_binding import FlashServiceBinding
from bootloader_upgrade_tool.gui.app import configure_application, create_fusion_style, create_main_window
from bootloader_upgrade_tool.gui.cpu_program_status_binding import CpuProgramStatusBinding
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_binding import RuntimeViewBinding
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


def test_runtime_window_constructs_exactly_one_of_each_binding() -> None:
    app = qt_app()
    window = create_main_window(runtime_backend=RuntimeBackend())
    assert isinstance(window.runtime_binding, RuntimeViewBinding)
    assert isinstance(window.advanced_read_binding, AdvancedReadOnlyBinding)
    assert isinstance(window.advanced_ram_binding, AdvancedRamBinding)
    assert isinstance(window.advanced_flash_binding, AdvancedFlashBinding)
    assert isinstance(window.advanced_flash_operation_binding, AdvancedFlashOperationBinding)
    assert isinstance(window.advanced_metadata_operation_binding, AdvancedMetadataOperationBinding)
    assert isinstance(window.flash_service_binding, FlashServiceBinding)
    assert isinstance(window.cpu_program_status_binding, CpuProgramStatusBinding)
    window.close()
    app.processEvents()
