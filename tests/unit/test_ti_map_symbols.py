from pathlib import Path

import pytest

from bootloader_upgrade_tool.firmware.ti_map import parse_flash_service_symbols_from_map


MAP_TEXT = """
MEMORY CONFIGURATION

name                   origin      length
SERVICE_IMMUTABLE      00013082    00002a7e

00013000 g_boot_flash_service_header
00013020 g_boot_flash_service_publish_state
00013022 g_service
00013080 g_boot_flash_service_app_export
00013100 BootFlashService_BootInit
00013200 BootFlashService_BootHandleCommand
00013300 BootFlashService_ConfirmCurrentImage
"""


def write_map(tmp_path: Path, text: str = MAP_TEXT) -> Path:
    path = tmp_path / "flash_service_lib_cpu01.map"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_flash_service_header_symbols_and_immutable_region(tmp_path: Path) -> None:
    symbols = parse_flash_service_symbols_from_map(write_map(tmp_path))

    assert symbols.header_address == 0x013000
    assert symbols.publish_state_address == 0x013020
    assert symbols.runtime_state_address == 0x013022
    assert symbols.app_export_address == 0x013080
    assert symbols.immutable_start == 0x013082
    assert symbols.immutable_end_exclusive == 0x015B00
    assert symbols.boot_init_address == 0x013100
    assert symbols.boot_handle_command_address == 0x013200
    assert symbols.confirm_current_image_address == 0x013300


def test_header_symbol_override(tmp_path: Path) -> None:
    symbols = parse_flash_service_symbols_from_map(
        write_map(tmp_path, MAP_TEXT.replace("g_boot_flash_service_header", "custom_header")),
        header_symbol="custom_header",
    )
    assert symbols.header_address == 0x013000


@pytest.mark.parametrize(
    ("text", "missing"),
    (
        (MAP_TEXT.replace("g_service", "missing_runtime"), "g_service"),
        (MAP_TEXT.replace("SERVICE_IMMUTABLE", "OTHER_MEMORY"), "SERVICE_IMMUTABLE"),
    ),
)
def test_parse_rejects_missing_required_map_data(tmp_path: Path, text: str, missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        parse_flash_service_symbols_from_map(write_map(tmp_path, text))
