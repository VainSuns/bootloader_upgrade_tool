import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import argparse
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.app import (
    GuiLaunchOptions,
    configure_application,
    create_main_window,
    parse_gui_options,
    parse_window_size,
)
from bootloader_upgrade_tool.gui.layout_metrics import WINDOW_MINIMUM_SIZE
from bootloader_upgrade_tool.gui.layout_preview import apply_layout_preview
from bootloader_upgrade_tool.gui.navigation import PageId
from bootloader_upgrade_tool.app_resources import (
    AppResourceConfigurationError,
    DevelopmentResourceProvider,
    FlashServiceResources,
)
from bootloader_upgrade_tool.gui.persistence_models import GlobalSettingsDocument
from bootloader_upgrade_tool.gui.persistence_stores import GlobalSettingsStore, RuntimeCacheStore
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.session_application_service import SessionApplicationService


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _resource_provider(tmp_path: Path) -> DevelopmentResourceProvider:
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image", encoding="utf-8")
    map_file.write_text("map", encoding="utf-8")
    return DevelopmentResourceProvider(FlashServiceResources(image, map_file))


def _runtime_window(tmp_path: Path, **kwargs):
    kwargs.setdefault("app_resource_provider", _resource_provider(tmp_path))
    kwargs.setdefault("sci8_workspace_root", tmp_path / "sci8")
    kwargs.setdefault("global_settings_store", GlobalSettingsStore(tmp_path / "global.json"))
    kwargs.setdefault(
        "session_application_service",
        SessionApplicationService(
            runtime_cache_store=RuntimeCacheStore(tmp_path / "runtime-cache.json")
        ),
    )
    return create_main_window(**kwargs)


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("1280x760", (1280, 760)),
        ("1440X900", (1440, 900)),
        (" 1920 x 1080 ", (1920, 1080)),
    ),
)
def test_parse_window_size_accepts_validation_matrix(
    text: str, expected: tuple[int, int]
) -> None:
    assert parse_window_size(text) == expected


@pytest.mark.parametrize("text", ("", "1440", "x900", "1024x640", "abcx900"))
def test_parse_window_size_rejects_invalid_or_too_small_values(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_window_size(text)


def test_gui_options_preserve_unknown_qt_arguments() -> None:
    options, qt_arguments = parse_gui_options(
        ["--layout-preview", "--window-size", "1440x900", "-platform", "offscreen"]
    )
    assert options == GuiLaunchOptions(True, (1440, 900))
    assert qt_arguments == ["-platform", "offscreen"]


def test_layout_preview_populates_static_views_without_enabling_targets() -> None:
    app = qt_app()
    configure_application(app)
    window = create_main_window(GuiLaunchOptions(True, (1280, 760)))
    window.show()
    app.processEvents()

    assert (window.width(), window.height()) == (1280, 760)
    assert window.property("layoutPreviewMode") is True
    assert window.windowTitle().endswith(" — Layout Preview")
    assert "[Preview]" in window.program_cpu1_page.image_path_row.path_edit.text()
    assert not window.program_cpu2_page.interactions_enabled
    assert not window.memory_cpu2_page.interactions_enabled
    assert "????" in window.memory_cpu2_page.memory_table.item(0, 1).text()
    assert window.logs_page.logs_table.rowCount() >= 4
    assert "LAYOUT PREVIEW MODE" in window.bottom_dock.output.toPlainText()
    assert not window.advanced_page.erase_button.isEnabled()
    assert not window.advanced_page.program_only_button.isEnabled()
    assert not window.advanced_page.verify_only_button.isEnabled()
    assert "cpu1_flash_app" in window.advanced_page.cpu1_flash_image_edit.text()
    assert "cpu2_flash_app" in window.advanced_page.cpu2_flash_image_edit.text()
    assert window.advanced_page.cpu1_flash_entry_point_value.text() == "0x082400 [Preview]"
    assert window.advanced_page.cpu1_flash_image_size_value.text() == "96 KiB [Preview]"
    assert window.advanced_page.cpu1_flash_crc32_value.text() == "0x7A4C2D91 [Preview]"
    assert window.advanced_page.cpu1_flash_app_end_value.text() == "0x09A000 [Preview]"
    assert window.advanced_page.cpu1_flash_parse_status_value.text() == "Ready [Preview]"
    assert window.advanced_page.cpu2_flash_parse_status_value.text() == "Not parsed [Preview]"
    assert tuple(sector.sector_id for sector in window.advanced_page.custom_sector_selector.sectors) == tuple("ABCDEFGHIJKLMN")
    assert window.advanced_page.cpu2_flash_entry_point_value.text() == "Not prepared [Preview]"
    assert window.advanced_page.cpu2_flash_image_size_value.text() == "Not prepared [Preview]"
    assert window.advanced_page.cpu2_flash_crc32_value.text() == "Not prepared [Preview]"
    assert "cpu1_ram_image" in window.advanced_page.cpu1_ram_image_edit.text()
    assert "cpu2_ram_image" in window.advanced_page.cpu2_ram_image_edit.text()
    assert window.advanced_page.cpu1_ram_entry_point_value.text() == "RAM CPU1 entry [Preview]"
    assert window.advanced_page.cpu1_ram_image_size_value.text() == "24 KiB [Preview]"
    assert window.advanced_page.cpu1_ram_crc32_value.text() == "0x19A4E2C7 [Preview]"
    assert window.advanced_page.cpu2_ram_target_value.text() == "CPU2 / TMS320F28377D"
    assert window.advanced_page.cpu2_ram_entry_point_value.text() == "Not prepared [Preview]"
    assert window.advanced_page.cpu2_ram_image_size_value.text() == "Not prepared [Preview]"
    assert window.advanced_page.cpu2_ram_crc32_value.text() == "Not prepared [Preview]"
    assert not window.advanced_page.ram_load_button.isEnabled()
    assert not window.advanced_page.ram_crc_button.isEnabled()
    assert not window.advanced_page.ram_run_button.isEnabled()
    assert window.advanced_page.custom_sector_selector.selected_sector_ids() == (
        "B",
        "C",
        "D",
        "E",
        "F",
        "G",
        "H",
        "I",
        "J",
        "K",
        "L",
        "M",
    )
    assert window.advanced_page.custom_sector_selector.selected_mask() == 0x00001FFE

    for page_id in PageId:
        window.navigate_to(page_id)
        assert window.router.current_page is page_id

    before = window.bottom_dock.output.blockCount()
    apply_layout_preview(window)
    assert window.bottom_dock.output.blockCount() == before

    window.close()
    app.processEvents()


def test_default_launch_options_keep_frozen_minimum_contract() -> None:
    assert WINDOW_MINIMUM_SIZE == (1180, 680)
    assert GuiLaunchOptions() == GuiLaunchOptions(False, None)


def test_normal_startup_uses_injected_provider_without_legacy_loader(tmp_path) -> None:
    app = qt_app()
    import bootloader_upgrade_tool.gui.app as app_module

    provider = _resource_provider(tmp_path)
    window = _runtime_window(tmp_path, app_resource_provider=provider)

    assert window.app_resource_provider is provider
    assert not hasattr(app_module, "load_global_settings")
    assert not hasattr(window.settings_page, "output_directory")
    assert hasattr(window, "program_image_binding")
    window.close()
    app.processEvents()


def test_injected_workspace_root_is_exposed_applied_and_lazy(tmp_path) -> None:
    app = qt_app()
    backend = RuntimeBackend()
    root = tmp_path / "injected-sci8"
    window = _runtime_window(
        tmp_path, runtime_backend=backend, sci8_workspace_root=root
    )

    assert window.sci8_workspace_root == root
    assert backend.sci8_temp_dir == str(root)
    assert not root.exists()
    window.close()
    app.processEvents()


def test_global_settings_store_supplies_normal_startup_hex2000(tmp_path) -> None:
    app = qt_app()
    store = GlobalSettingsStore(tmp_path / "global.json")
    store.save(GlobalSettingsDocument(hex2000_executable_path="C:/tools/hex2000.exe"))
    window = _runtime_window(tmp_path, global_settings_store=store)

    assert window.runtime_backend.hex2000_executable_path == "C:/tools/hex2000.exe"
    assert window.settings_page.hex2000_path.path_edit.text() == "C:/tools/hex2000.exe"
    window.close()
    app.processEvents()


def test_injected_backend_still_uses_explicit_resource_provider(tmp_path) -> None:
    app = qt_app()
    backend, provider = RuntimeBackend(), _resource_provider(tmp_path)
    window = _runtime_window(
        tmp_path, runtime_backend=backend, app_resource_provider=provider
    )

    assert window.runtime_backend is backend
    assert window.app_resource_provider is provider
    window.close()
    app.processEvents()


def test_missing_explicit_development_resource_config_fails(tmp_path) -> None:
    qt_app()
    with pytest.raises(AppResourceConfigurationError, match="Copy.*example"):
        create_main_window(development_resource_config_path=tmp_path / "missing.json")


def test_layout_preview_skips_provider_config_workspace_and_bindings(tmp_path) -> None:
    app = qt_app()
    root = tmp_path / "never-created"
    window = create_main_window(
        GuiLaunchOptions(layout_preview=True),
        development_resource_config_path=tmp_path / "missing.json",
        sci8_workspace_root=root,
    )

    assert not hasattr(window, "program_image_binding")
    assert not hasattr(window, "app_resource_provider")
    assert window.runtime_binding is None
    assert window.session_binding is None
    assert not hasattr(window, "global_settings_binding")
    assert not root.exists()
    window.close()
    app.processEvents()
