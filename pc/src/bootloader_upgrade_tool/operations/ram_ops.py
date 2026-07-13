"""RAM image operations."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.workflow import _prepare_ram_packets
from ..images.models import PreparedRamImage
from ._ram_protocol import (
    ram_check_crc_protocol,
    ram_load_begin_protocol,
    ram_load_data_protocol,
    ram_load_end_protocol,
)
from .context import OperationContext
from .results import ProgressEvent, emit_progress, failure_result, ok_result


@dataclass(frozen=True)
class LoadRamImageRequest:
    image: PreparedRamImage


@dataclass(frozen=True)
class CheckRamCrcRequest:
    image: PreparedRamImage


def load_ram_image(ctx: OperationContext, request: LoadRamImageRequest):
    operation = "load_ram_image"
    try:
        max_data_words = ctx.session.client.effective_max_data_words
        packets = _prepare_ram_packets(request.image.image, max_data_words)
        total_words = sum(len(packet.words) for packet in packets)
        ram_load_begin_protocol(
            ctx,
            packet_count=len(packets),
            total_words=total_words,
            entry_point=request.image.entry_point,
            image_crc32=request.image.image_crc32,
        )
        sent = 0
        for packet in packets:
            ram_load_data_protocol(ctx, address=packet.address, words=packet.words, packet_index=packet.index)
            sent += len(packet.words)
            emit_progress(
                ctx,
                ProgressEvent(
                    operation,
                    ctx.target.name,
                    "RAM_LOAD_DATA",
                    "RAM load data",
                    sent,
                    total_words,
                    len(packet.words),
                ),
            )
        ram_load_end_protocol(
            ctx,
            packet_count=len(packets),
            total_words=total_words,
            image_crc32=request.image.image_crc32,
        )
        return ok_result(ctx, operation, "RAM_LOAD_END", {"total_words": total_words, "packets": len(packets)})
    except Exception as exc:
        return failure_result(ctx, operation, "RAM_LOAD", exc)


def check_ram_crc(ctx: OperationContext, request: CheckRamCrcRequest):
    operation = "check_ram_crc"
    try:
        ram_check_crc_protocol(
            ctx,
            expected_crc32=request.image.image_crc32,
            expected_total_words=request.image.total_words,
        )
        return ok_result(
            ctx,
            operation,
            "RAM_CHECK_CRC",
            {"image_crc32": request.image.image_crc32, "total_words": request.image.total_words},
        )
    except Exception as exc:
        return failure_result(ctx, operation, "RAM_CHECK_CRC", exc)
