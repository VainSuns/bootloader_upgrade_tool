"""Internal RAM service attach/reuse support."""

from __future__ import annotations

from dataclasses import dataclass

from ..firmware import prepare_service_ram_packets_descriptor_last
from ..protocol.constants import SERVICE_ABI_MAJOR, SERVICE_ABI_MINOR, SERVICE_DESCRIPTOR_WORDS, ServiceState
from ..protocol.models import ServiceStatus, split_u32
from ._ram_protocol import ram_check_crc_protocol, ram_load_begin_protocol, ram_load_data_protocol, ram_load_end_protocol
from .context import FlashOperationContext
from .results import OperationFailure, ProgressEvent, emit_progress, transact


@dataclass(frozen=True)
class ServiceRuntimeSummary:
    reused: bool
    attach_performed: bool
    service_state: int
    service_major: int
    service_minor: int
    capabilities: int
    loaded_image_crc32: int


def _max_data_words(ctx: FlashOperationContext) -> int:
    info = ctx.session.client.device_info
    if info is None:
        raise OperationFailure("PREREQUISITE_MISSING", "device info is unavailable", stage="SERVICE_ATTACH")
    return info.max_data_words


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


def ensure_service_attached(ctx: FlashOperationContext) -> ServiceRuntimeSummary:
    status = _read_status(ctx)
    if not ctx.force_service_attach and _matches(ctx, status):
        return _summary(status, reused=True, attach_performed=False)

    packets = prepare_service_ram_packets_descriptor_last(
        ctx.service.image,
        ctx.service.descriptor_address,
        SERVICE_DESCRIPTOR_WORDS,
        _max_data_words(ctx),
    )
    total_words = sum(len(packet.words) for packet in packets)
    ram_load_begin_protocol(
        ctx,
        packet_count=len(packets),
        total_words=total_words,
        entry_point=ctx.service.image.entry_point,
        image_crc32=ctx.service.expected_crc32,
    )
    sent = 0
    for packet in packets:
        ram_load_data_protocol(ctx, address=packet.address, words=packet.words, packet_index=packet.index)
        sent += len(packet.words)
        emit_progress(
            ctx,
            ProgressEvent(
                "ensure_service_attached",
                ctx.target.name,
                "RAM_LOAD_SERVICE",
                "RAM load service",
                sent,
                total_words,
                len(packet.words),
            ),
        )
    ram_load_end_protocol(
        ctx,
        packet_count=len(packets),
        total_words=total_words,
        image_crc32=ctx.service.expected_crc32,
    )
    ram_check_crc_protocol(
        ctx,
        expected_crc32=ctx.service.expected_crc32,
        expected_total_words=ctx.service.total_words,
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
    status = _read_status(ctx)
    _validate_attached(ctx, status)
    if status.loaded_image_crc32 != ctx.service.expected_crc32 or status.loaded_image_words != ctx.service.total_words:
        raise OperationFailure("SERVICE_ATTACH_FAILED", "attached service image does not match request", stage="SERVICE_ATTACH")
    return _summary(status, reused=False, attach_performed=True)
