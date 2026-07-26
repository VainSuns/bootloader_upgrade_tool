"""Generic C28x word-addressed memory read operation."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.client import ProtocolDecodeError
from ..protocol.constants import Feature
from ..protocol.models import DeviceInfo, join_u32, split_u32
from .context import OperationContext
from .results import (
    OperationCancellationInfo,
    OperationFailure,
    OperationResult,
    ProgressEvent,
    cancelled_result,
    completed_after_cancel_result,
    emit_progress,
    failure_result,
    ok_result,
    operation_cancellation_requested,
    transact,
)


@dataclass(frozen=True, slots=True)
class MemoryReadRequest:
    start_address: int
    word_count: int

    def __post_init__(self) -> None:
        if type(self.start_address) is not int:
            raise TypeError("start_address must be an int")
        if not 0 <= self.start_address <= 0xFFFFFFFF:
            raise ValueError("start_address must fit uint32")
        if type(self.word_count) is not int:
            raise TypeError("word_count must be an int")
        if not 0 < self.word_count <= 0xFFFFFFFF:
            raise ValueError("word_count must be a positive uint32")
        if self.start_address + self.word_count - 1 > 0xFFFFFFFF:
            raise ValueError("memory read exceeds the uint32 address space")


def _cancellation_info(request: MemoryReadRequest, current_words: int) -> OperationCancellationInfo:
    return OperationCancellationInfo(
        "MEMORY_READ",
        current_words,
        request.word_count,
        True,
        False,
        False,
        recovery_action="NONE",
    )


def memory_read(ctx: OperationContext, request: MemoryReadRequest) -> OperationResult:
    operation = "memory_read"
    stage = "MEMORY_READ"
    try:
        client = ctx.session.client
        device_info = client.device_info
        if not isinstance(device_info, DeviceInfo):
            raise OperationFailure(
                "CAPABILITY_UNAVAILABLE",
                "DeviceInfo is not cached",
                stage="MEMORY_READ_PREFLIGHT",
            )
        if not device_info.feature_flags & int(Feature.MEMORY_READ):
            raise OperationFailure(
                "UNSUPPORTED_FEATURE",
                "connected target does not advertise MEMORY_READ",
                stage="MEMORY_READ_PREFLIGHT",
            )
        if ctx.target.command_set.memory_read is None:
            raise OperationFailure(
                "UNSUPPORTED_OPERATION",
                "target profile does not define MEMORY_READ",
                stage="MEMORY_READ_PREFLIGHT",
            )
        max_payload_words = client.effective_max_payload_words
        if max_payload_words < 4:
            raise OperationFailure(
                "INVALID_PAYLOAD_CAPACITY",
                "effective payload capacity must be at least 4 words",
                stage="MEMORY_READ_PREFLIGHT",
                details={"effective_max_payload_words": max_payload_words},
            )
        if operation_cancellation_requested(ctx):
            return cancelled_result(ctx, operation, stage, _cancellation_info(request, 0))

        frame_capacity = min(0xFFFF, max_payload_words - 3)
        frame_count = (request.word_count + frame_capacity - 1) // frame_capacity
        words: list[int] = []
        address = request.start_address
        for frame_index in range(frame_count):
            chunk_word_count = min(frame_capacity, request.word_count - len(words))
            payload = transact(
                ctx,
                "memory_read",
                (*split_u32(address), chunk_word_count, 0),
                stage=stage,
            )
            if len(payload) < 3:
                raise ProtocolDecodeError(
                    f"MEMORY_READ frame {frame_index} response has {len(payload)} payload words; expected at least 3"
                )
            response_address = join_u32(payload[0], payload[1])
            response_word_count = payload[2]
            data = payload[3:]
            if response_address != address:
                raise ProtocolDecodeError(
                    f"MEMORY_READ frame {frame_index} address mismatch: expected 0x{address:08X}, actual 0x{response_address:08X}"
                )
            if response_word_count != chunk_word_count:
                raise ProtocolDecodeError(
                    f"MEMORY_READ frame {frame_index} count mismatch: expected {chunk_word_count}, actual {response_word_count}"
                )
            if len(data) != response_word_count:
                raise ProtocolDecodeError(
                    f"MEMORY_READ frame {frame_index} data length mismatch: expected {response_word_count}, actual payload length {len(data)}"
                )
            if any(type(word) is not int or not 0 <= word <= 0xFFFF for word in data):
                raise ProtocolDecodeError(f"MEMORY_READ frame {frame_index} contains a non-uint16 data word")
            if len(words) + len(data) > request.word_count:
                raise ProtocolDecodeError(
                    f"MEMORY_READ frame {frame_index} exceeds requested count {request.word_count}"
                )
            words.extend(data)
            emit_progress(
                ctx,
                ProgressEvent(
                    operation,
                    ctx.target.name,
                    stage,
                    "Memory read progress",
                    len(words),
                    request.word_count,
                    chunk_word_count,
                    {
                        "frame_index": frame_index,
                        "frame_count": frame_count,
                        "chunk_start_address": address,
                    },
                    True,
                ),
            )
            address += chunk_word_count
            if operation_cancellation_requested(ctx):
                cancellation = _cancellation_info(request, len(words))
                if len(words) < request.word_count:
                    return cancelled_result(ctx, operation, stage, cancellation)
                summary = _summary(request, frame_count)
                return completed_after_cancel_result(
                    ctx,
                    operation,
                    stage,
                    summary,
                    cancellation,
                    details={"words": tuple(words)},
                )

        if len(words) != request.word_count:
            raise ProtocolDecodeError(
                f"MEMORY_READ returned {len(words)} words; expected {request.word_count}"
            )
        return ok_result(
            ctx,
            operation,
            stage,
            _summary(request, frame_count),
            details={"words": tuple(words)},
        )
    except Exception as exc:
        return failure_result(ctx, operation, stage, exc)


def _summary(request: MemoryReadRequest, frame_count: int) -> dict[str, int]:
    return {
        "start_address": request.start_address,
        "end_address": request.start_address + request.word_count - 1,
        "word_count": request.word_count,
        "frame_count": frame_count,
    }
