from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage, crc32_words
from bootloader_upgrade_tool.firmware.service_image import (
    calculate_service_ram_load_crc32_descriptor_last,
    patch_flash_service_image,
    prepare_service_ram_packets_descriptor_last,
)
from bootloader_upgrade_tool.protocol.constants import (
    SERVICE_DESCRIPTOR_MAGIC,
    SERVICE_DESCRIPTOR_WORDS,
)
from bootloader_upgrade_tool.protocol.models import join_u32


BASE = 0x010000
DESCRIPTOR = BASE
CRC_PATCH = BASE + SERVICE_DESCRIPTOR_WORDS
API = BASE + SERVICE_DESCRIPTOR_WORDS + 2


def image() -> FirmwareImage:
    return FirmwareImage(
        source_out_file="service.out",
        generated_hex_file="service.txt",
        entry_point=BASE,
        blocks=(FirmwareBlock(BASE, tuple(range(96))),),
        file_checksum="fixture",
        format_info={},
    )


def words_at(firmware: FirmwareImage, address: int, count: int) -> tuple[int, ...]:
    block = next(block for block in firmware.blocks if block.address <= address < block.end_exclusive)
    offset = address - block.address
    return block.words[offset : offset + count]


def test_descriptor_packets_are_sent_last() -> None:
    patched = patch_flash_service_image(
        image(),
        descriptor_address=DESCRIPTOR,
        api_table_address=API,
        crc_patch_address=CRC_PATCH,
        load_order="descriptor_last",
        max_data_words=8,
    )
    packets = prepare_service_ram_packets_descriptor_last(
        patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS, max_data_words=8
    )

    descriptor_packets = [
        packet
        for packet in packets
        if packet.address < DESCRIPTOR + SERVICE_DESCRIPTOR_WORDS
        and packet.address + len(packet.words) > DESCRIPTOR
    ]

    assert descriptor_packets
    assert packets[-len(descriptor_packets) :] == tuple(descriptor_packets)
    assert all(
        packet.address >= DESCRIPTOR + SERVICE_DESCRIPTOR_WORDS
        or packet.address + len(packet.words) <= DESCRIPTOR
        for packet in packets[: -len(descriptor_packets)]
    )
    assert sum(len(packet.words) for packet in packets) == patched.total_words


def test_descriptor_last_crc_matches_descriptor_and_patch_words() -> None:
    patched = patch_flash_service_image(
        image(),
        descriptor_address=DESCRIPTOR,
        api_table_address=API,
        crc_patch_address=CRC_PATCH,
        load_order="descriptor_last",
        max_data_words=8,
    )
    descriptor = words_at(patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS)
    final_crc = calculate_service_ram_load_crc32_descriptor_last(
        patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS, max_data_words=8
    )

    assert join_u32(descriptor[0], descriptor[1]) == SERVICE_DESCRIPTOR_MAGIC
    assert join_u32(descriptor[14], descriptor[15]) == final_crc
    assert join_u32(descriptor[18], descriptor[19]) == crc32_words(descriptor[:18])
    assert words_at(patched, CRC_PATCH, 2) != (0, 0)


def test_address_order_patch_remains_available() -> None:
    patched = patch_flash_service_image(
        image(),
        descriptor_address=DESCRIPTOR,
        api_table_address=API,
        crc_patch_address=CRC_PATCH,
    )
    descriptor = words_at(patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS)
    assert join_u32(descriptor[0], descriptor[1]) == SERVICE_DESCRIPTOR_MAGIC
