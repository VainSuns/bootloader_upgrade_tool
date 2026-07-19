import importlib
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.app_resources import (
    AppResourceConfigurationError,
    DevelopmentResourceProvider,
    FlashServiceResources,
)
from bootloader_upgrade_tool.gui.advanced_read_binding import AdvancedReadOnlyBinding
from bootloader_upgrade_tool.gui.advanced_ram_binding import AdvancedRamBinding
from bootloader_upgrade_tool.gui.advanced_flash_binding import AdvancedFlashBinding
from bootloader_upgrade_tool.gui.program_image_binding import ProgramImageBinding
from bootloader_upgrade_tool.gui.runtime_v2_models import RuntimeCpuId
from bootloader_upgrade_tool.gui.advanced_flash_operation_binding import AdvancedFlashOperationBinding
from bootloader_upgrade_tool.gui.flash_write_confirmation import FlashWriteConfirmationCoordinator
from bootloader_upgrade_tool.gui.advanced_metadata_binding import AdvancedMetadataOperationBinding
from bootloader_upgrade_tool.gui.flash_service_binding import FlashServiceBinding
from bootloader_upgrade_tool.gui.app import GuiLaunchOptions, configure_application, create_fusion_style, create_main_window
from bootloader_upgrade_tool.gui.global_settings_binding import GlobalSettingsBinding
from bootloader_upgrade_tool.gui.navigation import PageId
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


def resource_provider(tmp_path):
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image", encoding="utf-8")
    map_file.write_text("map", encoding="utf-8")
    return DevelopmentResourceProvider(FlashServiceResources(image, map_file))


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
        app_resource_provider=resource_provider(tmp_path),
        global_settings_store=GlobalSettingsStore(tmp_path / "global.json"),
        session_application_service=SessionApplicationService(
            runtime_cache_store=RuntimeCacheStore(tmp_path / "cache.json")
        ),
    )
    assert isinstance(window.runtime_binding, RuntimeViewBinding)
    assert isinstance(window.advanced_read_binding, AdvancedReadOnlyBinding)
    assert isinstance(window.advanced_ram_binding, AdvancedRamBinding)
    assert isinstance(window.advanced_flash_binding, AdvancedFlashBinding)
    assert set(window.program_image_bindings) == set(RuntimeCpuId)
    assert all(isinstance(binding, ProgramImageBinding) for binding in window.program_image_bindings.values())
    assert window.program_image_binding is window.program_image_bindings[RuntimeCpuId.CPU1]
    assert window.session_binding.program_bindings is window.program_image_bindings
    assert isinstance(window.advanced_flash_operation_binding, AdvancedFlashOperationBinding)
    assert isinstance(window.advanced_metadata_operation_binding, AdvancedMetadataOperationBinding)
    assert isinstance(window.flash_write_confirmation_coordinator, FlashWriteConfirmationCoordinator)
    assert window.advanced_flash_operation_binding.confirmation_coordinator is window.flash_write_confirmation_coordinator
    assert window.advanced_metadata_operation_binding.confirmation_coordinator is window.flash_write_confirmation_coordinator
    assert isinstance(window.flash_service_binding, FlashServiceBinding)
    assert isinstance(window.cpu_program_status_binding, CpuProgramStatusBinding)
    assert window.cpu_program_status_binding.backend is window.runtime_backend
    assert isinstance(window.session_binding, SessionGuiBinding)
    assert isinstance(window.global_settings_binding, GlobalSettingsBinding)
    assert window.runtime_backend.app_resource_provider is window.app_resource_provider
    assert not hasattr(window.flash_service_binding, "app_resource_provider")
    assert window.session_application_service.state.display_name == "Untitled"
    window.close()
    app.processEvents()


@pytest.mark.parametrize(
    ("button_name", "page_id", "page_name"),
    (
        ("cpu1_flash_browse_button", PageId.PROGRAM_CPU1, "program_cpu1_page"),
        ("cpu2_flash_browse_button", PageId.PROGRAM_CPU2, "program_cpu2_page"),
    ),
)
def test_advanced_flash_button_only_navigates_and_focuses_program_path(
    tmp_path, monkeypatch, button_name, page_id, page_name
) -> None:
    app = qt_app()
    window = create_main_window(
        runtime_backend=RuntimeBackend(),
        app_resource_provider=resource_provider(tmp_path),
        global_settings_store=GlobalSettingsStore(tmp_path / "global.json"),
        session_application_service=SessionApplicationService(
            runtime_cache_store=RuntimeCacheStore(tmp_path / "cache.json")
        ),
    )
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.app.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: pytest.fail("navigation must not open a file dialog"),
    )
    page = getattr(window, page_name)
    path_edit = page.image_path_row.path_edit
    before = path_edit.text()
    window.show()
    window.navigate_to(PageId.ADVANCED)
    getattr(window.advanced_page, button_name).click()
    app.processEvents()
    assert window.router.current_page is page_id
    assert path_edit.hasFocus()
    assert path_edit.text() == before
    assert window.runtime_controller.snapshot.active_task_id is None
    window.close()


def test_layout_preview_constructs_no_runtime_or_persistence_bindings() -> None:
    from bootloader_upgrade_tool.gui.app import GuiLaunchOptions

    window = create_main_window(GuiLaunchOptions(layout_preview=True))
    assert window.runtime_binding is None
    assert window.session_binding is None
    assert not hasattr(window, "global_settings_binding")
    assert not hasattr(window, "flash_write_confirmation_coordinator")


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
        app_resource_provider=resource_provider(tmp_path),
        global_settings_store=GlobalSettingsStore(tmp_path / "global.json"),
        session_application_service=service,
        session_dialog_provider=dialogs,
    )
    assert isinstance(window.session_binding, SessionGuiBinding)
    assert window.session_application_service is service
    assert service.state.display_name == "Untitled" and not service.state.is_dirty
    assert dialogs.errors and dialogs.errors[0][0] == "Runtime Cache"
    assert cache_path.read_bytes() == payload


def test_composition_exposes_provider_and_lazy_workspace_root(tmp_path) -> None:
    provider = resource_provider(tmp_path)
    workspace_root = tmp_path / "sci8-root"
    window = create_main_window(
        runtime_backend=RuntimeBackend(),
        app_resource_provider=provider,
        sci8_workspace_root=workspace_root,
        global_settings_store=GlobalSettingsStore(tmp_path / "global.json"),
        session_application_service=SessionApplicationService(
            runtime_cache_store=RuntimeCacheStore(tmp_path / "cache.json")
        ),
    )
    assert window.app_resource_provider is provider
    assert window.sci8_workspace_root == workspace_root
    assert window.runtime_backend.sci8_temp_dir == str(workspace_root)
    assert not workspace_root.exists()


def test_default_source_composition_loads_explicit_development_config(tmp_path) -> None:
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image", encoding="utf-8")
    map_file.write_text("map", encoding="utf-8")
    config = tmp_path / "resources.json"
    config.write_text(json.dumps({
        "flash_service_image_path": str(image),
        "flash_service_map_path": str(map_file),
    }), encoding="utf-8")
    window = create_main_window(
        development_resource_config_path=config,
        sci8_workspace_root=tmp_path / "sci8",
        global_settings_store=GlobalSettingsStore(tmp_path / "global.json"),
        session_application_service=SessionApplicationService(
            runtime_cache_store=RuntimeCacheStore(tmp_path / "cache.json")
        ),
    )
    assert isinstance(window.app_resource_provider, DevelopmentResourceProvider)


def test_missing_development_config_fails_and_preview_skips_it(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(AppResourceConfigurationError, match="Copy.*example"):
        create_main_window(development_resource_config_path=missing)
    preview = create_main_window(
        GuiLaunchOptions(layout_preview=True),
        development_resource_config_path=missing,
        sci8_workspace_root=tmp_path / "never-created",
    )
    assert not hasattr(preview, "app_resource_provider")
    assert not (tmp_path / "never-created").exists()


def test_composition_root_no_longer_imports_legacy_settings_loader() -> None:
    app_module = importlib.import_module("bootloader_upgrade_tool.gui.app")
    assert not hasattr(app_module, "load_global_settings")
