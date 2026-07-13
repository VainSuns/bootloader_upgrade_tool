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
from .results import (
    cancelled_result,
    cancellation_cleanup_failure_result,
    completed_after_cancel_result,
    failure_result,
    ok_result,
    run_cancellable_transfer,
)


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
        outcome = run_cancellable_transfer(
            ctx,
            operation=operation,
            packets=packets,
            total_words=total_words,
            begin_stage="RAM_LOAD_BEGIN",
            data_stage="RAM_LOAD_DATA",
            end_stage="RAM_LOAD_END",
            progress_message="RAM load data",
            send_begin=lambda: ram_load_begin_protocol(
                ctx,
                packet_count=len(packets),
                total_words=total_words,
                entry_point=request.image.entry_point,
                image_crc32=request.image.image_crc32,
            ),
            send_data=lambda packet: ram_load_data_protocol(
                ctx,
                address=packet.address,
                words=packet.words,
                packet_index=packet.index,
            ),
            send_end=lambda: ram_load_end_protocol(
                ctx,
                packet_count=len(packets),
                total_words=total_words,
                image_crc32=request.image.image_crc32,
            ),
            recovery_action=lambda _sent: "RESTART_RAM_LOAD",
            reconnect_recovery_action=lambda _sent: "RECONNECT_AND_RESTART_RAM_LOAD",
        )
        if outcome.cleanup_error is not None:
            return cancellation_cleanup_failure_result(
                ctx,
                operation,
                outcome.cancellation.stage,
                outcome.cancellation,
                outcome.cleanup_error,
            )
        if outcome.cancellation is not None:
            if outcome.completed_after_cancel:
                return completed_after_cancel_result(
                    ctx,
                    operation,
                    "RAM_LOAD_END",
                    outcome.summary,
                    outcome.cancellation,
                )
            return cancelled_result(ctx, operation, outcome.cancellation.stage, outcome.cancellation)
        return ok_result(ctx, operation, "RAM_LOAD_END", outcome.summary)
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
