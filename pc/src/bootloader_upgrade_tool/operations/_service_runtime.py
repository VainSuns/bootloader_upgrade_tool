"""Internal RAM service attach/reuse support."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..firmware import crc32_words, prepare_service_ram_packets_descriptor_last
from ..protocol.constants import SERVICE_ABI_MAJOR, SERVICE_ABI_MINOR, SERVICE_DESCRIPTOR_WORDS, ServiceState
from ..protocol.models import ServiceStatus, split_u32
from ._ram_protocol import ram_check_crc_protocol, ram_load_begin_protocol, ram_load_data_protocol, ram_load_end_protocol
from .context import FlashOperationContext
from .results import (
    OperationCancellationInfo,
    OperationFailure,
    operation_cancellation_requested,
    run_cancellable_transfer,
    transact,
)


@dataclass(frozen=True)
class ServiceRuntimeSummary:
    reused: bool
    attach_performed: bool
    service_state: int
    service_major: int
    service_minor: int
    capabilities: int
    loaded_image_crc32: int


@dataclass(frozen=True)
class ServiceRuntimeCancellation:
    cancellation: OperationCancellationInfo
    service: ServiceRuntimeSummary | None = None
    cleanup_error: Exception | None = None


def _summary(status: ServiceStatus, *, reused: bool, attach_performed: bool) -> ServiceRuntimeSummary:
    return ServiceRuntimeSummary(
        reused,
        attach_performed,
        status.service_state,
        status.service_major,
        status.service_minor,
        status.capabilities,
        status.loaded_image_crc32,
    )


def _read_status(ctx: FlashOperationContext) -> ServiceStatus:
    return ServiceStatus.from_words(transact(ctx, "get_service_status", stage="GET_SERVICE_STATUS"))


def _validate_attached(ctx: FlashOperationContext, status: ServiceStatus) -> None:
    if status.service_state != int(ServiceState.ATTACHED):
        raise OperationFailure("SERVICE_ATTACH_FAILED", "service is not attached", stage="SERVICE_ATTACH")
    if status.abi_major != SERVICE_ABI_MAJOR or status.abi_minor != SERVICE_ABI_MINOR:
        raise OperationFailure(
            "SERVICE_ABI_MISMATCH",
            "attached service ABI does not match host expectation",
            stage="SERVICE_ATTACH",
            details={"abi_major": status.abi_major, "abi_minor": status.abi_minor},
        )
    if (status.capabilities & ctx.service.required_capabilities) != ctx.service.required_capabilities:
        raise OperationFailure(
            "SERVICE_CAPABILITY_MISMATCH",
            "attached service does not provide required capabilities",
            stage="SERVICE_ATTACH",
            details={
                "capabilities": status.capabilities,
                "required_capabilities": ctx.service.required_capabilities,
            },
        )


def _matches(ctx: FlashOperationContext, status: ServiceStatus) -> bool:
    return (
        status.service_state == int(ServiceState.ATTACHED)
        and status.abi_major == SERVICE_ABI_MAJOR
        and status.abi_minor == SERVICE_ABI_MINOR
        and status.loaded_image_crc32 == ctx.service.expected_crc32
        and status.loaded_image_words == ctx.service.total_words
        and (status.capabilities & ctx.service.required_capabilities) == ctx.service.required_capabilities
    )


def _invalidate_service_descriptor_magic(ctx: FlashOperationContext) -> None:
    words = (0, 0)
    image_crc32 = crc32_words(words)
    ram_load_begin_protocol(
        ctx,
        packet_count=1,
        total_words=len(words),
        entry_point=ctx.service.descriptor_address,
        image_crc32=image_crc32,
    )
    ram_load_data_protocol(ctx, address=ctx.service.descriptor_address, words=words, packet_index=0)
    ram_load_end_protocol(ctx, packet_count=1, total_words=len(words), image_crc32=image_crc32)


def _cancelled(
    ctx: FlashOperationContext,
    stage: str,
    current_words: int,
    *,
    service_attached: bool | None,
    recovery_action: str,
    service: ServiceRuntimeSummary | None = None,
) -> ServiceRuntimeCancellation:
    return ServiceRuntimeCancellation(
        OperationCancellationInfo(
            stage,
            current_words,
            ctx.service.total_words,
            True,
            False,
            False,
            service_attached=service_attached,
            recovery_action=recovery_action,
        ),
        service,
    )


def ensure_service_attached(ctx: FlashOperationContext) -> ServiceRuntimeSummary | ServiceRuntimeCancellation:
    if operation_cancellation_requested(ctx):
        return _cancelled(
            ctx,
            "GET_SERVICE_STATUS",
            0,
            service_attached=None,
            recovery_action="RESTART_SERVICE_LOAD",
        )
    status = _read_status(ctx)
    matches = not ctx.force_service_attach and _matches(ctx, status)
    reusable = _summary(status, reused=True, attach_performed=False) if matches else None
    if operation_cancellation_requested(ctx):
        return _cancelled(
            ctx,
            "GET_SERVICE_STATUS",
            0,
            service_attached=matches,
            recovery_action="NONE" if matches else "RESTART_SERVICE_LOAD",
            service=reusable,
        )
    if reusable is not None:
        return reusable

    max_data_words = ctx.session.client.effective_max_data_words
    if max_data_words < 2:
        raise OperationFailure(
            "PREREQUISITE_MISSING",
            "effective RAM DATA capacity cannot hold descriptor invalidation",
            stage="SERVICE_ATTACH",
        )
    packets = prepare_service_ram_packets_descriptor_last(
        ctx.service.image,
        ctx.service.descriptor_address,
        SERVICE_DESCRIPTOR_WORDS,
        max_data_words,
    )
    total_words = sum(len(packet.words) for packet in packets)
    if operation_cancellation_requested(ctx):
        return _cancelled(
            ctx,
            "SERVICE_DESCRIPTOR_INVALIDATION",
            0,
            service_attached=False,
            recovery_action="RESTART_SERVICE_LOAD",
        )
    _invalidate_service_descriptor_magic(ctx)
    if operation_cancellation_requested(ctx):
        return _cancelled(
            ctx,
            "SERVICE_DESCRIPTOR_INVALIDATION",
            0,
            service_attached=False,
            recovery_action="RESTART_SERVICE_LOAD",
        )
    outcome = run_cancellable_transfer(
        ctx,
        operation="ensure_service_attached",
        packets=packets,
        total_words=total_words,
        begin_stage="RAM_LOAD_BEGIN",
        data_stage="RAM_LOAD_SERVICE",
        end_stage="RAM_LOAD_END",
        progress_message="RAM load service",
        send_begin=lambda: ram_load_begin_protocol(
            ctx,
            packet_count=len(packets),
            total_words=total_words,
            entry_point=ctx.service.image.entry_point,
            image_crc32=ctx.service.expected_crc32,
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
            image_crc32=ctx.service.expected_crc32,
        ),
        recovery_action=lambda _sent: "RESTART_SERVICE_LOAD",
        reconnect_recovery_action=lambda _sent: "RECONNECT_AND_RESTART_SERVICE_LOAD",
        service_attached=False,
    )
    if outcome.cancellation is not None:
        cancellation = outcome.cancellation
        if outcome.completed_after_cancel:
            cancellation = replace(cancellation, service_attached=False, recovery_action="RESTART_SERVICE_LOAD")
        return ServiceRuntimeCancellation(cancellation, cleanup_error=outcome.cleanup_error)
    if operation_cancellation_requested(ctx):
        return _cancelled(
            ctx,
            "RAM_CHECK_CRC",
            total_words,
            service_attached=False,
            recovery_action="RESTART_SERVICE_LOAD",
        )
    ram_check_crc_protocol(
        ctx,
        expected_crc32=ctx.service.expected_crc32,
        expected_total_words=ctx.service.total_words,
    )
    if operation_cancellation_requested(ctx):
        return _cancelled(
            ctx,
            "SERVICE_ATTACH",
            total_words,
            service_attached=False,
            recovery_action="RESTART_SERVICE_LOAD",
        )
    transact(
        ctx,
        "service_attach",
        (
            *split_u32(ctx.service.descriptor_address),
            *split_u32(ctx.service.expected_crc32),
            *split_u32(ctx.service.total_words),
            0,
        ),
        stage="SERVICE_ATTACH",
    )
    if operation_cancellation_requested(ctx):
        return _cancelled(
            ctx,
            "GET_SERVICE_STATUS",
            total_words,
            service_attached=True,
            recovery_action="NONE",
        )
    status = _read_status(ctx)
    _validate_attached(ctx, status)
    if status.loaded_image_crc32 != ctx.service.expected_crc32 or status.loaded_image_words != ctx.service.total_words:
        raise OperationFailure("SERVICE_ATTACH_FAILED", "attached service image does not match request", stage="SERVICE_ATTACH")
    return _summary(status, reused=False, attach_performed=True)
