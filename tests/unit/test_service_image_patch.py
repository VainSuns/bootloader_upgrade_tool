import pytest

from bootloader_upgrade_tool.core.workflow import calculate_ram_image_crc32
from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage, crc32_words
from bootloader_upgrade_tool.firmware.service_image import patch_flash_service_image, patch_words
from bootloader_upgrade_tool.protocol.constants import (
    SERVICE_ABI_MAJOR,
    SERVICE_ABI_MINOR,
    SERVICE_DESCRIPTOR_MAGIC,
    SERVICE_DESCRIPTOR_VERSION,
    SERVICE_DESCRIPTOR_WORDS,
    SERVICE_REQUIRED_CAPABILITIES,
)
from bootloader_upgrade_tool.protocol.models import join_u32


BASE = 0x010000
DESCRIPTOR = BASE
CRC_PATCH = BASE + SERVICE_DESCRIPTOR_WORDS
API = BASE + SERVICE_DESCRIPTOR_WORDS + 2


def image(words=tuple(range(32))) -> FirmwareImage:
    return FirmwareImage(
        source_out_file="service.out",
        generated_hex_file="service.txt",
        entry_point=BASE,
        blocks=(FirmwareBlock(BASE, words),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )


def words_at(firmware: FirmwareImage, address: int, count: int) -> tuple[int, ...]:
    block = next(block for block in firmware.blocks if block.address <= address < block.end_exclusive)
    offset = address - block.address
    return block.words[offset:offset + count]


def test_patch_flash_service_image_descriptor_and_crc_self_consistency() -> None:
    original = image()
    patched = patch_flash_service_image(
        original,
        descriptor_address=DESCRIPTOR,
        api_table_address=API,
        crc_patch_address=CRC_PATCH,
        service_major=2,
        service_minor=4,
    )
    descriptor = words_at(patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS)
    final_crc = calculate_ram_image_crc32(patched, 248)

    assert join_u32(descriptor[0], descriptor[1]) == SERVICE_DESCRIPTOR_MAGIC
    assert descriptor[2] == SERVICE_DESCRIPTOR_VERSION
    assert descriptor[3] == SERVICE_DESCRIPTOR_WORDS
    assert descriptor[4] == SERVICE_ABI_MAJOR
    assert descriptor[5] == SERVICE_ABI_MINOR
    assert descriptor[6] == 2
    assert descriptor[7] == 4
    assert join_u32(descriptor[8], descriptor[9]) == API
    assert join_u32(descriptor[10], descriptor[11]) == BASE
    assert join_u32(descriptor[12], descriptor[13]) == BASE + len(original.blocks[0].words)
    assert join_u32(descriptor[14], descriptor[15]) == final_crc
    assert join_u32(descriptor[16], descriptor[17]) == int(SERVICE_REQUIRED_CAPABILITIES)
    assert join_u32(descriptor[18], descriptor[19]) == crc32_words(descriptor[:18])
    assert words_at(patched, CRC_PATCH, 2) != (0, 0)
    assert words_at(original, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS) == tuple(range(SERVICE_DESCRIPTOR_WORDS))


@pytest.mark.parametrize(
    ("descriptor", "api", "crc_patch", "match"),
    (
        (BASE + 100, API, CRC_PATCH, "descriptor_address"),
        (DESCRIPTOR, BASE + 100, CRC_PATCH, "api_table_address"),
        (DESCRIPTOR, API, BASE + 100, "crc_patch_address"),
    ),
)
def test_patch_flash_service_image_rejects_outside_addresses(descriptor, api, crc_patch, match) -> None:
    with pytest.raises(ValueError, match=match):
        patch_flash_service_image(
            image(),
            descriptor_address=descriptor,
            api_table_address=api,
            crc_patch_address=crc_patch,
        )


def test_patch_words_rejects_cross_block_patch() -> None:
    firmware = FirmwareImage(
        source_out_file="service.out",
        generated_hex_file="service.txt",
        entry_point=BASE,
        blocks=(FirmwareBlock(BASE, (1, 2)), FirmwareBlock(BASE + 2, (3, 4))),
        file_checksum="fixture",
        format_info={},
    )
    with pytest.raises(ValueError, match="one FirmwareBlock"):
        patch_words(firmware, BASE + 1, (9, 9))
