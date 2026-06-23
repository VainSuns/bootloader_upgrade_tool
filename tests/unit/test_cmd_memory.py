import json

import pytest

from bootloader_upgrade_tool.firmware.cmd_memory import (
    MemoryParseError,
    build_device_info,
    parse_memory_text,
    write_device_info,
)


LINKER_CMD = """
/* CPU1 example */
MEMORY
{
    PAGE 0:
    BEGIN   : origin = 0x080000, length = 0x000002
    FLASHA  : origin = 0x080002,
              length = 0x001FFE
    FLASHB (RX) : o = 0x082000, l = 0x002000

    PAGE 1:
    RAMM0   : origin = 0x000122, length = 0x0002DE // data RAM
}
SECTIONS { }
"""


def test_parse_memory_preserves_source_order_and_pages() -> None:
    regions = parse_memory_text(LINKER_CMD)

    assert [region.name for region in regions] == ["BEGIN", "FLASHA", "FLASHB", "RAMM0"]
    assert regions[1].origin == 0x080002
    assert regions[1].length == 0x001FFE
    assert regions[1].page == 0
    assert regions[-1].page == 1


def test_build_and_write_device_info(tmp_path) -> None:
    regions = parse_memory_text(LINKER_CMD)
    info = build_device_info(regions, flash_region_names=["FLASHA", "FLASHB"])

    assert info["device"] == "F28377D"
    assert [sector["name"] for sector in info["flash_sectors"]] == ["FLASHA", "FLASHB"]
    assert info["allowed_address_ranges"] == [
        {"name": "APP_FLASH", "start": "0x080002", "end": "0x083FFF"}
    ]
    output = write_device_info(tmp_path / "device_info.json", info)
    assert json.loads(output.read_text(encoding="utf-8")) == info


@pytest.mark.parametrize(
    "text, message",
    [
        ("SECTIONS {}", "no MEMORY"),
        ("MEMORY { FLASHA: origin = SYMBOL, length = 1 }", "literal origin"),
        (
            "MEMORY {\nFLASHA: origin=0, length=1\nflasha: origin=1, length=1\n}",
            "duplicate",
        ),
    ],
)
def test_parse_memory_rejects_unsafe_or_ambiguous_input(text: str, message: str) -> None:
    with pytest.raises(MemoryParseError, match=message):
        parse_memory_text(text)


def test_build_device_info_is_cpu1_only() -> None:
    with pytest.raises(ValueError, match="CPU1"):
        build_device_info(parse_memory_text(LINKER_CMD), cpu="CPU2")

