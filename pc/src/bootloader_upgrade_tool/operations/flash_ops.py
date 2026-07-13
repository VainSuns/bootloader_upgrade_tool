"""Flash erase/program/verify operations."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.workflow import _prepare_packets
from ..images.models import PreparedFlashImage
from ._flash_protocol import (
    erase_protocol,
    program_begin_protocol,
    program_data_protocol,
    program_end_protocol,
    verify_begin_protocol,
    verify_data_protocol,
    verify_end_protocol,
)
from ._service_runtime import ServiceRuntimeCancellation, ensure_service_attached
from .context import FlashOperationContext
from .results import (
    OperationCancellationInfo,
    OperationFailure,
    cancelled_result,
    cancellation_cleanup_failure_result,
    completed_after_cancel_result,
    failure_result,
    ok_result,
    operation_cancellation_requested,
    run_cancellable_transfer,
    service_summary_dict,
)


@dataclass(frozen=True)
class EraseFlashImageAreaRequest:
    image: PreparedFlashImage


@dataclass(frozen=True)
class EraseSectorMaskRequest:
    sector_mask: int


@dataclass(frozen=True)
class ProgramFlashImageRequest:
    image: PreparedFlashImage


@dataclass(frozen=True)
class VerifyFlashImageRequest:
    image: PreparedFlashImage


def _check_sector_mask(ctx: FlashOperationContext, sector_mask: int) -> None:
    flash = ctx.target.memory_map.flash
    if sector_mask == 0:
        raise OperationFailure("FORBIDDEN_SECTOR", "sector mask must be nonzero", stage="ERASE")
    if flash is not None and (sector_mask & flash.forbidden_erase_mask):
        raise OperationFailure("FORBIDDEN_SECTOR", "sector mask includes forbidden sectors", stage="ERASE")
    if flash is not None and (sector_mask & ~flash.allowed_erase_mask):
        raise OperationFailure("FORBIDDEN_SECTOR", "sector mask includes sectors outside allowed erase mask", stage="ERASE")


def _cancellation_info(
    stage: str,
    *,
    service_attached: bool | None,
    recovery_action: str,
    current_words: int = 0,
    total_words: int = 0,
) -> OperationCancellationInfo:
    return OperationCancellationInfo(
        stage,
        current_words,
        total_words,
        True,
        False,
        False,
        service_attached=service_attached,
        recovery_action=recovery_action,
    )


def _service_cancellation_result(
    ctx,
    operation: str,
    item: ServiceRuntimeCancellation,
    *,
    recovery_action: str | None = None,
):
    service = None if item.service is None else service_summary_dict(item.service)
    cancellation = item.cancellation
    if recovery_action is not None and cancellation.service_attached is True:
        cancellation = replace(cancellation, recovery_action=recovery_action)
    if item.cleanup_error is not None:
        return cancellation_cleanup_failure_result(
            ctx,
            operation,
            cancellation.stage,
            cancellation,
            item.cleanup_error,
            service=service,
        )
    return cancelled_result(ctx, operation, cancellation.stage, cancellation, service=service)


def erase_flash_image_area(ctx: FlashOperationContext, request: EraseFlashImageAreaRequest):
    operation = "erase_flash_image_area"
    try:
        if operation_cancellation_requested(ctx):
            return cancelled_result(ctx, operation, "GET_SERVICE_STATUS", _cancellation_info("GET_SERVICE_STATUS", service_attached=None, recovery_action="NONE"))
        service = ensure_service_attached(ctx)
        if isinstance(service, ServiceRuntimeCancellation):
            return _service_cancellation_result(ctx, operation, service)
        flash = ctx.target.memory_map.flash
        metadata_mask = 0 if flash is None else flash.metadata_sector_mask
        effective = request.image.sector_mask | metadata_mask
        _check_sector_mask(ctx, effective)
        service_dict = service_summary_dict(service)
        if operation_cancellation_requested(ctx):
            return cancelled_result(ctx, operation, "ERASE", _cancellation_info("ERASE", service_attached=True, recovery_action="NONE"), service=service_dict)
        erased: list[int] = []
        if metadata_mask:
            erase_protocol(ctx, sector_mask=metadata_mask)
            erased.append(metadata_mask)
        rest = effective & ~metadata_mask
        if rest:
            erase_protocol(ctx, sector_mask=rest)
            erased.append(rest)
        summary = {"erased_masks": erased}
        details = {"effective_mask": effective}
        if operation_cancellation_requested(ctx):
            return completed_after_cancel_result(
                ctx,
                operation,
                "ERASE",
                summary,
                _cancellation_info("ERASE", service_attached=True, recovery_action="NONE"),
                details=details,
                service=service_dict,
            )
        return ok_result(
            ctx,
            operation,
            "ERASE",
            summary,
            details=details,
            service=service_dict,
        )
    except Exception as exc:
        return failure_result(ctx, operation, "ERASE", exc)


def erase_sector_mask(ctx: FlashOperationContext, request: EraseSectorMaskRequest):
    operation = "erase_sector_mask"
    try:
        if operation_cancellation_requested(ctx):
            return cancelled_result(ctx, operation, "GET_SERVICE_STATUS", _cancellation_info("GET_SERVICE_STATUS", service_attached=None, recovery_action="NONE"))
        service = ensure_service_attached(ctx)
        if isinstance(service, ServiceRuntimeCancellation):
            return _service_cancellation_result(ctx, operation, service)
        _check_sector_mask(ctx, request.sector_mask)
        service_dict = service_summary_dict(service)
        if operation_cancellation_requested(ctx):
            return cancelled_result(ctx, operation, "ERASE", _cancellation_info("ERASE", service_attached=True, recovery_action="NONE"), service=service_dict)
        erase_protocol(ctx, sector_mask=request.sector_mask)
        summary = {"erased_masks": [request.sector_mask]}
        if operation_cancellation_requested(ctx):
            return completed_after_cancel_result(
                ctx,
                operation,
                "ERASE",
                summary,
                _cancellation_info("ERASE", service_attached=True, recovery_action="NONE"),
                service=service_dict,
            )
        return ok_result(
            ctx,
            operation,
            "ERASE",
            summary,
            service=service_dict,
        )
    except Exception as exc:
        return failure_result(ctx, operation, "ERASE", exc)


def _transfer(
    ctx: FlashOperationContext,
    request_image: PreparedFlashImage,
    *,
    operation: str,
    verify: bool,
    max_data_words: int,
):
    packets = _prepare_packets(request_image.image, max_data_words)
    total_words = sum(len(packet.words) for packet in packets)
    begin = verify_begin_protocol if verify else program_begin_protocol
    data = verify_data_protocol if verify else program_data_protocol
    end = verify_end_protocol if verify else program_end_protocol
    stage = "VERIFY_DATA" if verify else "PROGRAM_DATA"
    return run_cancellable_transfer(
        ctx,
        operation=operation,
        packets=packets,
        total_words=total_words,
        begin_stage="VERIFY_BEGIN" if verify else "PROGRAM_BEGIN",
        data_stage=stage,
        end_stage="VERIFY_END" if verify else "PROGRAM_END",
        progress_message=stage,
        send_begin=lambda: begin(
            ctx,
            packet_count=len(packets),
            total_words=total_words,
            entry_point=request_image.identity.entry_point,
        ),
        send_data=lambda packet: data(
            ctx,
            address=packet.address,
            words=packet.words,
            packet_index=packet.index,
        ),
        send_end=lambda: end(ctx, packet_count=len(packets), total_words=total_words),
        recovery_action=(lambda _sent: "RESTART_VERIFY") if verify else (
            lambda sent: "ERASE_AND_RESTART_PROGRAM" if sent else "RESTART_PROGRAM"
        ),
        reconnect_recovery_action=(lambda _sent: "RECONNECT_AND_RESTART_VERIFY") if verify else (
            lambda sent: "RECONNECT_ERASE_AND_RESTART_PROGRAM" if sent else "RECONNECT_AND_RESTART_PROGRAM"
        ),
        partial_flash_programmed=(lambda sent: bool(sent)) if not verify else (lambda _sent: False),
        service_attached=True,
    )


def program_flash_image(ctx: FlashOperationContext, request: ProgramFlashImageRequest):
    operation = "program_flash_image"
    try:
        if operation_cancellation_requested(ctx):
            return cancelled_result(ctx, operation, "GET_SERVICE_STATUS", _cancellation_info("GET_SERVICE_STATUS", service_attached=None, recovery_action="RESTART_PROGRAM"))
        max_data_words = ctx.session.client.effective_max_write_data_words
        service = ensure_service_attached(ctx)
        if isinstance(service, ServiceRuntimeCancellation):
            return _service_cancellation_result(ctx, operation, service, recovery_action="RESTART_PROGRAM")
        service_dict = service_summary_dict(service)
        outcome = _transfer(ctx, request.image, operation=operation, verify=False, max_data_words=max_data_words)
        if outcome.cleanup_error is not None:
            return cancellation_cleanup_failure_result(ctx, operation, outcome.cancellation.stage, outcome.cancellation, outcome.cleanup_error, service=service_dict)
        if outcome.cancellation is not None:
            if outcome.completed_after_cancel:
                return completed_after_cancel_result(ctx, operation, "PROGRAM_END", outcome.summary, outcome.cancellation, service=service_dict)
            return cancelled_result(ctx, operation, outcome.cancellation.stage, outcome.cancellation, service=service_dict)
        return ok_result(ctx, operation, "PROGRAM_END", outcome.summary, service=service_dict)
    except Exception as exc:
        return failure_result(ctx, operation, "PROGRAM", exc)


def verify_flash_image(ctx: FlashOperationContext, request: VerifyFlashImageRequest):
    operation = "verify_flash_image"
    try:
        if operation_cancellation_requested(ctx):
            return cancelled_result(ctx, operation, "GET_SERVICE_STATUS", _cancellation_info("GET_SERVICE_STATUS", service_attached=None, recovery_action="RESTART_VERIFY"))
        max_data_words = ctx.session.client.effective_max_write_data_words
        service = ensure_service_attached(ctx)
        if isinstance(service, ServiceRuntimeCancellation):
            return _service_cancellation_result(ctx, operation, service, recovery_action="RESTART_VERIFY")
        service_dict = service_summary_dict(service)
        outcome = _transfer(ctx, request.image, operation=operation, verify=True, max_data_words=max_data_words)
        if outcome.cleanup_error is not None:
            return cancellation_cleanup_failure_result(ctx, operation, outcome.cancellation.stage, outcome.cancellation, outcome.cleanup_error, service=service_dict)
        if outcome.cancellation is not None:
            if outcome.completed_after_cancel:
                return completed_after_cancel_result(ctx, operation, "VERIFY_END", outcome.summary, outcome.cancellation, service=service_dict)
            return cancelled_result(ctx, operation, outcome.cancellation.stage, outcome.cancellation, service=service_dict)
        return ok_result(ctx, operation, "VERIFY_END", outcome.summary, service=service_dict)
    except Exception as exc:
        return failure_result(ctx, operation, "VERIFY", exc)
