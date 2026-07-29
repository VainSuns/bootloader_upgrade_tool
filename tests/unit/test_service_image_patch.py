import pytest

from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage, crc32_words
from bootloader_upgrade_tool.firmware.service_image import patch_flash_service_image, patch_words
from bootloader_upgrade_tool.firmware.ti_map import TiMapSymbols
from bootloader_upgrade_tool.protocol.constants import (
    SERVICE_ABI_MAJOR,
    SERVICE_ABI_MINOR,
    SERVICE_HEADER_MAGIC,
    SERVICE_HEADER_VERSION,
    SERVICE_HEADER_WORDS,
    SERVICE_IMAGE_CRC32_IEEE,
    SERVICE_REQUIRED_CAPABILITIES,
)
from bootloader_upgrade_tool.protocol.models import join_u32


HEADER = 0x013000
PUBLISH = 0x013020
RUNTIME = 0x013022
APP_EXPORT = 0x013080
IMMUTABLE_START = APP_EXPORT
IMMUTABLE_END = 0x013092
BOOT_INIT = IMMUTABLE_START + 2
HANDLE_COMMAND = IMMUTABLE_START + 8
CONFIRM = IMMUTABLE_START + 12


def symbols() -> TiMapSymbols:
    return TiMapSymbols(
        HEADER, PUBLISH, RUNTIME, APP_EXPORT, IMMUTABLE_START, IMMUTABLE_END,
        BOOT_INIT, HANDLE_COMMAND, CONFIRM,
    )


def image() -> FirmwareImage:
    return FirmwareImage(
        source_out_file="service.out",
        generated_hex_file="service.txt",
        entry_point=BOOT_INIT,
        blocks=(
            FirmwareBlock(HEADER, tuple(range(32))),
            FirmwareBlock(APP_EXPORT, (CONFIRM & 0xFFFF, CONFIRM >> 16)),
            FirmwareBlock(APP_EXPORT + 2, (0x1111, 0x2222, 0x3333)),
            FirmwareBlock(IMMUTABLE_END - 2, (0xAAAA, 0xBBBB)),
        ),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )


def words_at(firmware: FirmwareImage, address: int, count: int) -> tuple[int, ...]:
    block = next(block for block in firmware.blocks if block.address <= address < block.end_exclusive)
    offset = address - block.address
    return block.words[offset : offset + count]


def test_patch_header_v2_dense_immutable_publish_and_app_export() -> None:
    original = image()
    patched = patch_flash_service_image(original, symbols=symbols())
    header = words_at(patched, HEADER, SERVICE_HEADER_WORDS)
    immutable = words_at(patched, IMMUTABLE_START, IMMUTABLE_END - IMMUTABLE_START)

    assert join_u32(header[0], header[1]) == SERVICE_HEADER_MAGIC
    assert header[2:6] == (
        SERVICE_HEADER_VERSION, SERVICE_HEADER_WORDS, SERVICE_ABI_MAJOR, SERVICE_ABI_MINOR
    )
    assert join_u32(header[6], header[7]) == IMMUTABLE_START
    assert join_u32(header[8], header[9]) == IMMUTABLE_END
    assert join_u32(header[10], header[11]) == PUBLISH
    assert join_u32(header[12], header[13]) == RUNTIME
    assert join_u32(header[14], header[15]) == APP_EXPORT
    assert join_u32(header[16], header[17]) == BOOT_INIT
    assert join_u32(header[18], header[19]) == HANDLE_COMMAND
    assert join_u32(header[20], header[21]) == int(SERVICE_REQUIRED_CAPABILITIES)
    assert header[22:24] == (SERVICE_IMAGE_CRC32_IEEE, 0)
    assert immutable == (
        CONFIRM & 0xFFFF,
        CONFIRM >> 16,
        0x1111,
        0x2222,
        0x3333,
        *((0xFFFF,) * 11),
        0xAAAA,
        0xBBBB,
    )
    assert join_u32(header[24], header[25]) == crc32_words(immutable)
    assert join_u32(header[26], header[27]) == crc32_words(header[:26])
    assert words_at(patched, PUBLISH, 2) == (0, 0)
    assert words_at(patched, APP_EXPORT, 2) == words_at(original, APP_EXPORT, 2)
    assert words_at(original, HEADER, SERVICE_HEADER_WORDS) == tuple(range(SERVICE_HEADER_WORDS))


@pytest.mark.parametrize("word_offset", (0, 1))
def test_app_export_words_are_covered_by_immutable_crc(word_offset: int) -> None:
    original = image()
    patched = patch_flash_service_image(original, symbols=symbols())
    changed = patch_words(
        original,
        APP_EXPORT + word_offset,
        (words_at(original, APP_EXPORT + word_offset, 1)[0] ^ 1,),
    )
    changed_patched = patch_flash_service_image(changed, symbols=symbols())

    crc = join_u32(*words_at(patched, HEADER + 24, 2))
    changed_crc = join_u32(*words_at(changed_patched, HEADER + 24, 2))
    assert changed_crc != crc


def test_patch_rejects_entry_points_outside_immutable() -> None:
    bad = TiMapSymbols(
        HEADER, PUBLISH, RUNTIME, APP_EXPORT, IMMUTABLE_START, IMMUTABLE_END,
        HEADER, HANDLE_COMMAND, CONFIRM,
    )
    with pytest.raises(ValueError, match="entry points"):
        patch_flash_service_image(image(), symbols=bad)


def test_patch_words_rejects_cross_block_patch() -> None:
    firmware = FirmwareImage(
        source_out_file="service.out", generated_hex_file="service.txt", entry_point=HEADER,
        blocks=(FirmwareBlock(HEADER, (1, 2)), FirmwareBlock(HEADER + 2, (3, 4))),
        file_checksum="fixture", format_info={},
    )
    with pytest.raises(ValueError, match="one FirmwareBlock"):
        patch_words(firmware, HEADER + 1, (9, 9))
