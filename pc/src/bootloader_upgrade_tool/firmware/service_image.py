"""Patch externally built RAM service images before SERVICE_ATTACH."""

from __future__ import annotations

from typing import Sequence

from ..protocol.constants import (
    SERVICE_ABI_MAJOR,
    SERVICE_ABI_MINOR,
    SERVICE_DESCRIPTOR_MAGIC,
    SERVICE_DESCRIPTOR_VERSION,
    SERVICE_DESCRIPTOR_WORDS,
    SERVICE_REQUIRED_CAPABILITIES,
)
from ..protocol.models import split_u32
from .crc32 import crc32_words
from .models import FirmwareBlock, FirmwareImage


def patch_words(image: FirmwareImage, address: int, words: Sequence[int]) -> FirmwareImage:
    patch = tuple(words)
    if any(word < 0 or word > 0xFFFF for word in patch):
        raise ValueError("patch words must fit uint16")
    block_index = next(
        (
            index
            for index, block in enumerate(image.blocks)
            if block.address <= address and address + len(patch) <= block.end_exclusive
        ),
        None,
    )
    if block_index is None:
        raise ValueError("patch range must be inside one FirmwareBlock")
    block = image.blocks[block_index]
    offset = address - block.address
    patched_block = FirmwareBlock(
        block.address,
        (*block.words[:offset], *patch, *block.words[offset + len(patch):]),
    )
    blocks = (*image.blocks[:block_index], patched_block, *image.blocks[block_index + 1:])
    return FirmwareImage(
        source_out_file=image.source_out_file,
        generated_hex_file=image.generated_hex_file,
        entry_point=image.entry_point,
        blocks=blocks,
        file_checksum=image.file_checksum,
        format_info=dict(image.format_info),
    )


def _image_crc32(image: FirmwareImage) -> int:
    words: list[int] = []
    for block in sorted(image.blocks, key=lambda item: item.address):
        words.extend(block.words)
    return crc32_words(words)


def _range(image: FirmwareImage) -> tuple[int, int]:
    if not image.blocks:
        raise ValueError("service image must contain data")
    return min(block.address for block in image.blocks), max(block.end_exclusive for block in image.blocks)


def _inside(image: FirmwareImage, address: int, count: int) -> bool:
    return any(block.address <= address and address + count <= block.end_exclusive for block in image.blocks)


def _solve_crc_patch(image: FirmwareImage, patch_address: int, target_crc: int) -> tuple[int, int]:
    base_image = patch_words(image, patch_address, (0, 0))
    base = _image_crc32(base_image)
    columns: list[int] = []
    for bit in range(32):
        trial_words = [0, 0]
        trial_words[bit // 16] = 1 << (bit % 16)
        columns.append(_image_crc32(patch_words(base_image, patch_address, trial_words)) ^ base)

    rows = [[(columns[column] >> row) & 1 for column in range(32)] + [((target_crc ^ base) >> row) & 1] for row in range(32)]
    pivot_row = 0
    pivots: list[int] = []
    for column in range(32):
        row = next((candidate for candidate in range(pivot_row, 32) if rows[candidate][column]), None)
        if row is None:
            continue
        rows[pivot_row], rows[row] = rows[row], rows[pivot_row]
        for candidate in range(32):
            if candidate != pivot_row and rows[candidate][column]:
                rows[candidate] = [left ^ right for left, right in zip(rows[candidate], rows[pivot_row])]
        pivots.append(column)
        pivot_row += 1
    if pivot_row != 32:
        raise ValueError("unable to solve service image CRC patch words")
    value = 0
    for row, column in enumerate(pivots):
        value |= rows[row][32] << column
    return value & 0xFFFF, value >> 16


def patch_flash_service_image(
    image: FirmwareImage,
    *,
    descriptor_address: int,
    api_table_address: int,
    crc_patch_address: int,
    service_major: int = 0,
    service_minor: int = 1,
    capabilities: int = int(SERVICE_REQUIRED_CAPABILITIES),
) -> FirmwareImage:
    image_start, image_end = _range(image)
    if not _inside(image, descriptor_address, SERVICE_DESCRIPTOR_WORDS):
        raise ValueError("descriptor_address must point to 20 words inside one FirmwareBlock")
    if not _inside(image, api_table_address, 1):
        raise ValueError("api_table_address must be inside the service image")
    if not _inside(image, crc_patch_address, 2):
        raise ValueError("crc_patch_address must point to 2 words inside one FirmwareBlock")

    image = patch_words(image, descriptor_address, (0,) * SERVICE_DESCRIPTOR_WORDS)
    image = patch_words(image, crc_patch_address, (0, 0))
    descriptor = [0] * SERVICE_DESCRIPTOR_WORDS
    descriptor[0], descriptor[1] = split_u32(SERVICE_DESCRIPTOR_MAGIC)
    descriptor[2] = SERVICE_DESCRIPTOR_VERSION
    descriptor[3] = SERVICE_DESCRIPTOR_WORDS
    descriptor[4] = SERVICE_ABI_MAJOR
    descriptor[5] = SERVICE_ABI_MINOR
    descriptor[6] = service_major
    descriptor[7] = service_minor
    descriptor[8], descriptor[9] = split_u32(api_table_address)
    descriptor[10], descriptor[11] = split_u32(image_start)
    descriptor[12], descriptor[13] = split_u32(image_end)
    descriptor[16], descriptor[17] = split_u32(capabilities)
    target_crc = _image_crc32(patch_words(image, descriptor_address, descriptor))
    descriptor[14], descriptor[15] = split_u32(target_crc)
    descriptor[18], descriptor[19] = split_u32(crc32_words(descriptor[:18]))
    image = patch_words(image, descriptor_address, descriptor)
    image = patch_words(image, crc_patch_address, _solve_crc_patch(image, crc_patch_address, target_crc))
    if _image_crc32(image) != target_crc:
        raise ValueError("patched service image CRC32 verification failed")
    return image
