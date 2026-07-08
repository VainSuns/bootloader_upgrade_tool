"""Low-level Flash protocol primitives for operations."""

from __future__ import annotations

from typing import Sequence

from ..protocol.constants import Target
from ..protocol.models import split_u32
from .context import FlashOperationContext
from .results import transact


def erase_protocol(ctx: FlashOperationContext, *, sector_mask: int) -> tuple[int, ...]:
    return transact(ctx, "erase", (*split_u32(sector_mask), 0), stage="ERASE")


def program_begin_protocol(
    ctx: FlashOperationContext,
    *,
    packet_count: int,
    total_words: int,
    entry_point: int,
    image_crc32: int = 0,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "program_begin",
        (int(Target.FLASH_APP), packet_count, *split_u32(total_words), *split_u32(entry_point),
         *split_u32(image_crc32), 0),
        stage="PROGRAM_BEGIN",
    )


def program_data_protocol(
    ctx: FlashOperationContext,
    *,
    address: int,
    words: Sequence[int],
    packet_index: int,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "program_data",
        (*split_u32(address), len(words), *split_u32(packet_index), *words),
        stage="PROGRAM_DATA",
    )


def program_end_protocol(
    ctx: FlashOperationContext,
    *,
    packet_count: int,
    total_words: int,
    image_crc32: int = 0,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "program_end",
        (*split_u32(packet_count), *split_u32(total_words), *split_u32(image_crc32)),
        stage="PROGRAM_END",
    )


def verify_begin_protocol(
    ctx: FlashOperationContext,
    *,
    packet_count: int,
    total_words: int,
    entry_point: int,
    image_crc32: int = 0,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "verify_begin",
        (int(Target.FLASH_APP), packet_count, *split_u32(total_words), *split_u32(entry_point),
         *split_u32(image_crc32), 0),
        stage="VERIFY_BEGIN",
    )


def verify_data_protocol(
    ctx: FlashOperationContext,
    *,
    address: int,
    words: Sequence[int],
    packet_index: int,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "verify_data",
        (*split_u32(address), len(words), *split_u32(packet_index), *words),
        stage="VERIFY_DATA",
    )


def verify_end_protocol(
    ctx: FlashOperationContext,
    *,
    packet_count: int,
    total_words: int,
    image_crc32: int = 0,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "verify_end",
        (*split_u32(packet_count), *split_u32(total_words), *split_u32(image_crc32)),
        stage="VERIFY_END",
    )
