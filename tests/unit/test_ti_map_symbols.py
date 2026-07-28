from pathlib import Path

import pytest

from bootloader_upgrade_tool.firmware.ti_map import parse_flash_service_symbols_from_map


MAP_TEXT = """
MEMORY CONFIGURATION

name                   origin      length
SERVICE_IMMUTABLE      00013082    00002a7e
SERVICE_RUNTIME_STATE  00013022    0000003e

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


def test_parse_coff_prefixed_symbols_and_static_runtime_region(tmp_path: Path) -> None:
    text = MAP_TEXT.replace("00013022 g_service\n", "")
    for name in (
        "g_boot_flash_service_header",
        "g_boot_flash_service_publish_state",
        "g_boot_flash_service_app_export",
        "BootFlashService_BootInit",
        "BootFlashService_BootHandleCommand",
        "BootFlashService_ConfirmCurrentImage",
    ):
        text = text.replace(name, f"_{name}")

    symbols = parse_flash_service_symbols_from_map(write_map(tmp_path, text))

    assert symbols.header_address == 0x013000
    assert symbols.runtime_state_address == 0x013022


@pytest.mark.parametrize(
    ("text", "missing"),
    (
        (
            MAP_TEXT.replace("00013022 g_service\n", "").replace(
                "SERVICE_RUNTIME_STATE", "OTHER_RUNTIME"
            ),
            "SERVICE_RUNTIME_STATE",
        ),
        (MAP_TEXT.replace("SERVICE_IMMUTABLE", "OTHER_MEMORY"), "SERVICE_IMMUTABLE"),
    ),
)
def test_parse_rejects_missing_required_map_data(tmp_path: Path, text: str, missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        parse_flash_service_symbols_from_map(write_map(tmp_path, text))
