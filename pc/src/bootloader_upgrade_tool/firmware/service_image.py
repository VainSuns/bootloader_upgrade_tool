"""Patch externally built RAM service images before SERVICE_ATTACH."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..protocol.constants import (
    SERVICE_ABI_MAJOR,
    SERVICE_ABI_MINOR,
    SERVICE_HEADER_MAGIC,
    SERVICE_HEADER_VERSION,
    SERVICE_HEADER_WORDS,
    SERVICE_IMAGE_CRC32_IEEE,
    SERVICE_PUBLISH_INVALID,
    SERVICE_REQUIRED_CAPABILITIES,
)
from ..protocol.models import split_u32
from .crc32 import crc32_words
from .models import FirmwareBlock, FirmwareImage
from .ti_map import TiMapSymbols


@dataclass(frozen=True, slots=True)
class ServiceRamPacket:
    address: int
    words: tuple[int, ...]
    index: int


def _copy_image(image: FirmwareImage, blocks: Sequence[FirmwareBlock]) -> FirmwareImage:
    return FirmwareImage(
        source_out_file=image.source_out_file,
        generated_hex_file=image.generated_hex_file,
        entry_point=image.entry_point,
        blocks=tuple(sorted(blocks, key=lambda block: block.address)),
        file_checksum=image.file_checksum,
        format_info=dict(image.format_info),
    )


def _replace_words(image: FirmwareImage, address: int, words: Sequence[int]) -> FirmwareImage:
    patch = tuple(words)
    if not patch or any(word < 0 or word > 0xFFFF for word in patch):
        raise ValueError("patch words must be non-empty uint16 values")
    end = address + len(patch)
    blocks: list[FirmwareBlock] = []
    for block in image.blocks:
        if block.end_exclusive <= address or block.address >= end:
            blocks.append(block)
            continue
        if block.address < address:
            blocks.append(FirmwareBlock(block.address, block.words[: address - block.address]))
        if block.end_exclusive > end:
            blocks.append(FirmwareBlock(end, block.words[end - block.address :]))
    blocks.append(FirmwareBlock(address, patch))
    return _copy_image(image, blocks)


def patch_words(image: FirmwareImage, address: int, words: Sequence[int]) -> FirmwareImage:
    patch = tuple(words)
    if not any(
        block.address <= address and address + len(patch) <= block.end_exclusive
        for block in image.blocks
    ):
        raise ValueError("patch range must be inside one FirmwareBlock")
    return _replace_words(image, address, patch)


def _dense_immutable(image: FirmwareImage, start: int, end_exclusive: int) -> FirmwareBlock:
    if start < 0 or end_exclusive <= start or end_exclusive > 0x1_0000_0000:
        raise ValueError("invalid immutable range")
    words = [0xFFFF] * (end_exclusive - start)
    for block in image.blocks:
        copy_start = max(start, block.address)
        copy_end = min(end_exclusive, block.end_exclusive)
        if copy_start < copy_end:
            words[copy_start - start : copy_end - start] = block.words[
                copy_start - block.address : copy_end - block.address
            ]
    return FirmwareBlock(start, words)


def prepare_service_ram_packets(
    image: FirmwareImage, max_data_words: int
) -> tuple[ServiceRamPacket, ...]:
    if max_data_words <= 0:
        raise ValueError("max_data_words must be positive")
    packets: list[ServiceRamPacket] = []
    for block in sorted(image.blocks, key=lambda item: item.address):
        for offset in range(0, len(block.words), max_data_words):
            packets.append(
                ServiceRamPacket(
                    block.address + offset,
                    tuple(block.words[offset : offset + max_data_words]),
                    len(packets),
                )
            )
    if len(packets) > 0xFFFF:
        raise ValueError("service image requires more than 65535 protocol packets")
    return tuple(packets)


def calculate_service_ram_load_crc32(image: FirmwareImage, max_data_words: int) -> int:
    return crc32_words(
        tuple(
            word
            for packet in prepare_service_ram_packets(image, max_data_words)
            for word in packet.words
        )
    )


def patch_flash_service_image(
    image: FirmwareImage,
    *,
    symbols: TiMapSymbols,
    capabilities: int = int(SERVICE_REQUIRED_CAPABILITIES),
) -> FirmwareImage:
    if not any(
        block.address <= symbols.header_address
        and symbols.header_address + SERVICE_HEADER_WORDS <= block.end_exclusive
        for block in image.blocks
    ):
        raise ValueError("header_address must point to 28 words inside one FirmwareBlock")
    if not all(
        symbols.immutable_start <= address < symbols.immutable_end_exclusive
        for address in (
            symbols.boot_init_address,
            symbols.boot_handle_command_address,
            symbols.confirm_current_image_address,
        )
    ):
        raise ValueError("service entry points must be inside the immutable range")
    mutable_ranges = sorted(
        (
            (symbols.header_address, symbols.header_address + SERVICE_HEADER_WORDS),
            (symbols.publish_state_address, symbols.publish_state_address + 2),
            (symbols.runtime_state_address, symbols.runtime_state_address + 1),
        )
    )
    if (
        any(left[1] > right[0] for left, right in zip(mutable_ranges, mutable_ranges[1:]))
        or any(
            start < symbols.immutable_end_exclusive and end > symbols.immutable_start
            for start, end in mutable_ranges
        )
    ):
        raise ValueError("mutable service ranges must be disjoint from each other and immutable data")

    immutable = _dense_immutable(
        image, symbols.immutable_start, symbols.immutable_end_exclusive
    )
    patched = _replace_words(image, immutable.address, immutable.words)
    patched = _replace_words(
        patched,
        symbols.publish_state_address,
        (SERVICE_PUBLISH_INVALID, SERVICE_PUBLISH_INVALID),
    )
    header = [0] * SERVICE_HEADER_WORDS
    header[0], header[1] = split_u32(SERVICE_HEADER_MAGIC)
    header[2] = SERVICE_HEADER_VERSION
    header[3] = SERVICE_HEADER_WORDS
    header[4] = SERVICE_ABI_MAJOR
    header[5] = SERVICE_ABI_MINOR
    header[6], header[7] = split_u32(symbols.immutable_start)
    header[8], header[9] = split_u32(symbols.immutable_end_exclusive)
    header[10], header[11] = split_u32(symbols.publish_state_address)
    header[12], header[13] = split_u32(symbols.runtime_state_address)
    header[14], header[15] = split_u32(symbols.app_export_address)
    header[16], header[17] = split_u32(symbols.boot_init_address)
    header[18], header[19] = split_u32(symbols.boot_handle_command_address)
    header[20], header[21] = split_u32(capabilities)
    header[22] = SERVICE_IMAGE_CRC32_IEEE
    header[23] = 0
    header[24], header[25] = split_u32(crc32_words(immutable.words))
    header[26], header[27] = split_u32(crc32_words(header[:26]))
    return patch_words(patched, symbols.header_address, header)
