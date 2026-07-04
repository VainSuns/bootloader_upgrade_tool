from pathlib import Path

import pytest

from bootloader_upgrade_tool.firmware.ti_map import parse_flash_service_symbols_from_map


def write_map(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "flash_service_lib_cpu01.map"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_flash_service_symbols_from_map(tmp_path: Path) -> None:
    symbols = parse_flash_service_symbols_from_map(write_map(
        tmp_path,
        """
        00013000    g_boot_flash_service_descriptor
        00013014    g_boot_flash_service_crc_patch
        00013020    g_boot_flash_service_api
        00014000    unrelated_symbol
        """,
    ))
    assert symbols.descriptor_address == 0x013000
    assert symbols.crc_patch_address == 0x013014
    assert symbols.api_table_address == 0x013020


@pytest.mark.parametrize(
    ("text", "missing"),
    (
        ("00013014 g_boot_flash_service_crc_patch\n00013020 g_boot_flash_service_api", "descriptor"),
        ("00013000 g_boot_flash_service_descriptor\n00013020 g_boot_flash_service_api", "crc_patch"),
        ("00013000 g_boot_flash_service_descriptor\n00013014 g_boot_flash_service_crc_patch", "api"),
    ),
)
def test_parse_flash_service_symbols_rejects_missing_symbols(tmp_path: Path, text: str, missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        parse_flash_service_symbols_from_map(write_map(tmp_path, text))
