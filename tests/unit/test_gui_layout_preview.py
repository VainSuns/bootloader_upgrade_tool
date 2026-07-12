import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import argparse

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
from bootloader_upgrade_tool.gui.global_settings import GuiGlobalSettings, Hex2000Settings
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


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
    assert window.advanced_page.cpu2_flash_target_value.text() == "CPU2 / TMS320F28377D"
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


def test_normal_startup_injects_global_hex2000_path(monkeypatch) -> None:
    app = qt_app()
    import bootloader_upgrade_tool.gui.app as app_module

    monkeypatch.setattr(
        app_module,
        "load_global_settings",
        lambda: GuiGlobalSettings(hex2000=Hex2000Settings("C:/tools/hex2000.exe")),
    )
    window = create_main_window()

    assert window.runtime_backend.hex2000_executable_path == "C:/tools/hex2000.exe"
    assert window.settings_page.hex2000_path.path_edit.text() == "C:/tools/hex2000.exe"
    assert window.settings_page.output_directory.path_edit.text()
    assert hasattr(window, "program_image_binding")
    window.close()
    app.processEvents()


def test_tools_paths_update_runtime_backend(tmp_path) -> None:
    app = qt_app()
    backend = RuntimeBackend()
    window = create_main_window(runtime_backend=backend)

    window.settings_page.hex2000_path.path_edit.setText(" C:/tools/hex2000.exe ")
    window.settings_page.output_directory.path_edit.setText(f" {tmp_path} ")
    window.settings_page.output_directory.path_edit.editingFinished.emit()

    assert backend.hex2000_executable_path == "C:/tools/hex2000.exe"
    assert backend.sci8_temp_dir == str(tmp_path)
    window.close()
    app.processEvents()


def test_injected_backend_skips_global_settings_loading(monkeypatch) -> None:
    app = qt_app()
    import bootloader_upgrade_tool.gui.app as app_module

    monkeypatch.setattr(
        app_module,
        "load_global_settings",
        lambda: (_ for _ in ()).throw(AssertionError("settings loaded")),
    )
    backend = RuntimeBackend()
    window = create_main_window(runtime_backend=backend)

    assert window.runtime_backend is backend
    window.close()
    app.processEvents()


def test_normal_startup_does_not_hide_programming_errors(monkeypatch) -> None:
    qt_app()
    import bootloader_upgrade_tool.gui.app as app_module

    monkeypatch.setattr(
        app_module,
        "load_global_settings",
        lambda: (_ for _ in ()).throw(RuntimeError("loader bug")),
    )
    with pytest.raises(RuntimeError, match="loader bug"):
        create_main_window()


def test_normal_startup_injects_global_settings_value_error(monkeypatch) -> None:
    app = qt_app()
    import bootloader_upgrade_tool.gui.app as app_module

    monkeypatch.setattr(app_module, "load_global_settings", lambda: (_ for _ in ()).throw(ValueError("bad settings")))
    window = create_main_window()
    assert window.runtime_backend._global_settings_error == "bad settings"
    window.close()
    app.processEvents()


def test_layout_preview_skips_settings_and_program_binding(monkeypatch) -> None:
    app = qt_app()
    import bootloader_upgrade_tool.gui.app as app_module

    monkeypatch.setattr(
        app_module,
        "load_global_settings",
        lambda: (_ for _ in ()).throw(AssertionError("settings loaded")),
    )
    window = create_main_window(GuiLaunchOptions(layout_preview=True))

    assert not hasattr(window, "program_image_binding")
    window.close()
    app.processEvents()
