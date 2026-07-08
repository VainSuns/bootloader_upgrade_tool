"""Low-level RAM protocol primitives for operations."""

from __future__ import annotations

from typing import Sequence

from ..protocol.constants import Target
from ..protocol.models import split_u32
from .context import OperationContext
from .results import transact


def ram_load_begin_protocol(
    ctx: OperationContext,
    *,
    packet_count: int,
    total_words: int,
    entry_point: int,
    image_crc32: int,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "ram_load_begin",
        (int(Target.RAM_APP), packet_count, *split_u32(total_words), *split_u32(entry_point),
         *split_u32(image_crc32), 0),
        stage="RAM_LOAD_BEGIN",
    )


def ram_load_data_protocol(
    ctx: OperationContext,
    *,
    address: int,
    words: Sequence[int],
    packet_index: int,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "ram_load_data",
        (*split_u32(address), len(words), *split_u32(packet_index), *words),
        stage="RAM_LOAD_DATA",
    )


def ram_load_end_protocol(
    ctx: OperationContext,
    *,
    packet_count: int,
    total_words: int,
    image_crc32: int,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "ram_load_end",
        (*split_u32(packet_count), *split_u32(total_words), *split_u32(image_crc32)),
        stage="RAM_LOAD_END",
    )


def ram_check_crc_protocol(
    ctx: OperationContext,
    *,
    expected_crc32: int,
    expected_total_words: int,
) -> tuple[int, ...]:
    return transact(
        ctx,
        "ram_check_crc",
        (*split_u32(expected_crc32), *split_u32(expected_total_words), 0),
        stage="RAM_CHECK_CRC",
    )
