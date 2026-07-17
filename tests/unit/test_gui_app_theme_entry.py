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
from bootloader_upgrade_tool.gui.global_settings_binding import GlobalSettingsBinding
from bootloader_upgrade_tool.gui.persistence_stores import GlobalSettingsStore, RuntimeCacheStore
from bootloader_upgrade_tool.gui.session_application_service import SessionApplicationService
from bootloader_upgrade_tool.gui.session_gui_binding import SessionGuiBinding
from bootloader_upgrade_tool.gui.session_gui_binding import DirtySessionDecision
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


def test_runtime_window_constructs_exactly_one_of_each_binding(tmp_path) -> None:
    app = qt_app()
    window = create_main_window(
        runtime_backend=RuntimeBackend(),
        global_settings_store=GlobalSettingsStore(tmp_path / "global.json"),
        session_application_service=SessionApplicationService(
            runtime_cache_store=RuntimeCacheStore(tmp_path / "cache.json")
        ),
    )
    assert isinstance(window.runtime_binding, RuntimeViewBinding)
    assert isinstance(window.advanced_read_binding, AdvancedReadOnlyBinding)
    assert isinstance(window.advanced_ram_binding, AdvancedRamBinding)
    assert isinstance(window.advanced_flash_binding, AdvancedFlashBinding)
    assert isinstance(window.advanced_flash_operation_binding, AdvancedFlashOperationBinding)
    assert isinstance(window.advanced_metadata_operation_binding, AdvancedMetadataOperationBinding)
    assert isinstance(window.flash_service_binding, FlashServiceBinding)
    assert isinstance(window.cpu_program_status_binding, CpuProgramStatusBinding)
    assert isinstance(window.session_binding, SessionGuiBinding)
    assert isinstance(window.global_settings_binding, GlobalSettingsBinding)
    assert window.session_application_service.state.display_name == "Untitled"
    window.close()
    app.processEvents()


def test_layout_preview_constructs_no_runtime_or_persistence_bindings() -> None:
    from bootloader_upgrade_tool.gui.app import GuiLaunchOptions

    window = create_main_window(GuiLaunchOptions(layout_preview=True))
    assert window.runtime_binding is None
    assert window.session_binding is None
    assert not hasattr(window, "global_settings_binding")


class _Dialogs:
    def __init__(self):
        self.errors = []

    def choose_open_session(self, _parent):
        return None

    def choose_save_session(self, _parent, _current):
        return None

    def confirm_dirty_session(self, _parent, _name):
        return DirtySessionDecision.CANCEL

    def show_error(self, _parent, title, message):
        self.errors.append((title, message))

    def show_warning(self, *_args):
        pass

    def show_information(self, *_args):
        pass


def test_runtime_window_survives_recovered_runtime_cache_without_writing(tmp_path) -> None:
    cache_path = tmp_path / "runtime_cache.json"
    payload = b"malformed cache"
    cache_path.write_bytes(payload)
    cache_store = RuntimeCacheStore(cache_path)
    service = SessionApplicationService(runtime_cache_store=cache_store)
    dialogs = _Dialogs()
    window = create_main_window(
        runtime_backend=RuntimeBackend(),
        global_settings_store=GlobalSettingsStore(tmp_path / "global.json"),
        session_application_service=service,
        session_dialog_provider=dialogs,
    )
    assert isinstance(window.session_binding, SessionGuiBinding)
    assert window.session_application_service is service
    assert service.state.display_name == "Untitled" and not service.state.is_dirty
    assert dialogs.errors and dialogs.errors[0][0] == "Runtime Cache"
    assert cache_path.read_bytes() == payload
