"""Generic advanced MEMORY_READ operation."""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol.constants import Feature
from ..protocol.models import join_u32, split_u32
from .context import OperationContext
from .results import (
    OperationFailure,
    ProgressEvent,
    emit_progress,
    failure_result,
    ok_result,
    transact,
)


@dataclass(frozen=True, slots=True)
class MemoryReadRequest:
    start_address: int
    word_count: int


def _validate_request(request: MemoryReadRequest) -> None:
    if type(request.start_address) is not int or not 0 <= request.start_address <= 0xFFFFFFFF:
        raise OperationFailure(
            "BAD_ADDRESS",
            "start_address must fit a 32-bit C28x word address",
            stage="MEMORY_READ_VALIDATE",
        )
    if type(request.word_count) is not int or request.word_count <= 0:
        raise OperationFailure(
            "BAD_WORD_COUNT",
            "word_count must be positive",
            stage="MEMORY_READ_VALIDATE",
        )
    if request.start_address + request.word_count > 0x100000000:
        raise OperationFailure(
            "BAD_ADDRESS",
            "requested word-address interval exceeds uint32",
            stage="MEMORY_READ_VALIDATE",
        )


def memory_read(ctx: OperationContext, request: MemoryReadRequest):
    operation = "MEMORY_READ"
    stage = "MEMORY_READ"
    try:
        _validate_request(request)
        client = ctx.session.client
        device_info = getattr(client, "device_info", None)
        if device_info is None:
            raise OperationFailure(
                "DEVICE_INFO_REQUIRED",
                "MEMORY_READ requires cached DeviceInfo",
                stage="MEMORY_READ_CAPABILITY",
            )
        if not (int(device_info.feature_flags) & int(Feature.MEMORY_READ)):
            raise OperationFailure(
                "UNSUPPORTED_OPERATION",
                "The connected target does not advertise MEMORY_READ",
                stage="MEMORY_READ_CAPABILITY",
            )
        max_payload_words = int(getattr(client, "effective_max_payload_words"))
        max_chunk_words = max_payload_words - 3
        if max_chunk_words <= 0:
            raise OperationFailure(
                "BAD_PAYLOAD_CAPACITY",
                "MEMORY_READ response payload has no data capacity",
                stage="MEMORY_READ_CAPABILITY",
            )

        words: list[int] = []
        frame_count = 0
        while len(words) < request.word_count:
            chunk_address = request.start_address + len(words)
            chunk_words = min(max_chunk_words, request.word_count - len(words))
            low, high = split_u32(chunk_address)
            payload = transact(
                ctx,
                "memory_read",
                (low, high, chunk_words, 0),
                stage=stage,
            )
            if len(payload) < 3:
                raise OperationFailure(
                    "PROTOCOL_DECODE_ERROR",
                    "MEMORY_READ response is too short",
                    stage=stage,
                )
            response_address = join_u32(payload[0], payload[1])
            response_words = int(payload[2])
            data = tuple(int(word) for word in payload[3:])
            if response_address != chunk_address:
                raise OperationFailure(
                    "RESPONSE_ADDRESS_MISMATCH",
                    "MEMORY_READ response start address does not match the request",
                    stage=stage,
                    details={"expected": chunk_address, "actual": response_address},
                )
            if response_words != chunk_words or len(data) != chunk_words:
                raise OperationFailure(
                    "RESPONSE_WORD_COUNT_MISMATCH",
                    "MEMORY_READ response word count does not match the request",
                    stage=stage,
                    details={
                        "expected": chunk_words,
                        "reported": response_words,
                        "received": len(data),
                    },
                )
            words.extend(data)
            frame_count += 1
            emit_progress(
                ctx,
                ProgressEvent(
                    operation,
                    ctx.target.name,
                    stage,
                    f"Read {len(words)} of {request.word_count} words",
                    len(words),
                    request.word_count,
                    chunk_words,
                    {"address": chunk_address},
                ),
            )

        return ok_result(
            ctx,
            operation,
            "MEMORY_READ_COMPLETE",
            {
                "start_address": request.start_address,
                "word_count": request.word_count,
                "frame_count": frame_count,
            },
            details={"words": tuple(words)},
        )
    except Exception as exc:
        return failure_result(ctx, operation, stage, exc)
