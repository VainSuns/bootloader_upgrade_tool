"""Metadata append operations."""

from __future__ import annotations

from dataclasses import dataclass

from ..images.models import ImageIdentity, PreparedFlashImage
from ..protocol.constants import BootSlot, MetadataRecordType
from ..protocol.models import split_u32
from ._service_runtime import ServiceRuntimeCancellation, ensure_service_attached
from .context import FlashOperationContext
from .results import (
    OperationCancellationInfo,
    cancelled_result,
    cancellation_cleanup_failure_result,
    completed_after_cancel_result,
    failure_result,
    ok_result,
    operation_cancellation_requested,
    service_summary_dict,
    transact,
)
from .status_ops import _read_metadata_summary


@dataclass(frozen=True)
class AppendImageValidRequest:
    image: PreparedFlashImage


@dataclass(frozen=True)
class AppendBootAttemptRequest:
    pass


@dataclass(frozen=True)
class AppendAppConfirmedRequest:
    pass


def _append_image_valid(ctx: FlashOperationContext, identity: ImageIdentity) -> None:
    transact(
        ctx,
        "metadata_append_record",
        (
            int(MetadataRecordType.IMAGE_VALID),
            int(BootSlot.SLOT_A),
            *split_u32(identity.entry_point),
            *split_u32(identity.image_size_words),
            *split_u32(identity.image_crc32),
            0,
            0,
            0,
            0,
            0,
            *split_u32(identity.app_end),
            0,
        ),
        stage="METADATA_APPEND_RECORD",
    )


def _append_current_image(ctx: FlashOperationContext, record_type: MetadataRecordType, current) -> None:
    transact(
        ctx,
        "metadata_append_record",
        (
            int(record_type),
            int(BootSlot.SLOT_A),
            *split_u32(current.entry_point),
            *split_u32(current.image_size_words),
            *split_u32(current.image_crc32),
            0, 0, 0, 0, 0, 0, 0, 0,
        ),
        stage="METADATA_APPEND_RECORD",
    )


def _metadata_state(current) -> str:
    if (
        current.state == 0
        and not current.metadata_valid
        and current.valid_record_count == 0
        and current.invalid_record_count == 0
    ):
        return "EMPTY"
    if current.state == 1 and current.metadata_valid:
        return "VALID"
    return "INVALID"


def _metadata_summary(written: bool, already_exists: bool, reason: str | None) -> dict[str, object]:
    return {"written": written, "already_exists": already_exists, "reason": reason}


def _cancellation_info(stage: str, *, service_attached: bool | None) -> OperationCancellationInfo:
    return OperationCancellationInfo(
        stage,
        0,
        0,
        True,
        False,
        False,
        service_attached=service_attached,
        recovery_action="NONE",
    )


def _service_cancellation_result(ctx, operation: str, item: ServiceRuntimeCancellation):
    service = None if item.service is None else service_summary_dict(item.service)
    if item.cleanup_error is not None:
        return cancellation_cleanup_failure_result(
            ctx,
            operation,
            item.cancellation.stage,
            item.cancellation,
            item.cleanup_error,
            service=service,
        )
    return cancelled_result(ctx, operation, item.cancellation.stage, item.cancellation, service=service)


def _cancelled_before_service(ctx, operation: str):
    return cancelled_result(
        ctx,
        operation,
        "GET_SERVICE_STATUS",
        _cancellation_info("GET_SERVICE_STATUS", service_attached=None),
    )


def _cancelled_after_service(ctx, operation: str, stage: str, service: dict[str, object]):
    return cancelled_result(
        ctx,
        operation,
        stage,
        _cancellation_info(stage, service_attached=True),
        service=service,
    )


def _business_result(ctx, operation: str, summary: dict[str, object], service: dict[str, object]):
    if operation_cancellation_requested(ctx):
        return completed_after_cancel_result(
            ctx,
            operation,
            "READ_METADATA_SUMMARY",
            summary,
            _cancellation_info("READ_METADATA_SUMMARY", service_attached=True),
            service=service,
        )
    return ok_result(ctx, operation, "READ_METADATA_SUMMARY", summary, service=service)


def _written_result(ctx, operation: str, service: dict[str, object]):
    summary = _metadata_summary(True, False, None)
    if operation_cancellation_requested(ctx):
        return completed_after_cancel_result(
            ctx,
            operation,
            "METADATA_APPEND_RECORD",
            summary,
            _cancellation_info("METADATA_APPEND_RECORD", service_attached=True),
            service=service,
        )
    return ok_result(ctx, operation, "METADATA_APPEND_RECORD", summary, service=service)


def append_image_valid(ctx: FlashOperationContext, request: AppendImageValidRequest):
    operation = "append_image_valid"
    try:
        if operation_cancellation_requested(ctx):
            return _cancelled_before_service(ctx, operation)
        service = ensure_service_attached(ctx)
        if isinstance(service, ServiceRuntimeCancellation):
            return _service_cancellation_result(ctx, operation, service)
        service_dict = service_summary_dict(service)
        if operation_cancellation_requested(ctx):
            return _cancelled_after_service(ctx, operation, "READ_METADATA_SUMMARY", service_dict)
        current = _read_metadata_summary(ctx)
        state = _metadata_state(current)
        if state == "VALID":
            return _business_result(
                ctx, operation, _metadata_summary(False, True, "IMAGE_VALID_ALREADY_EXISTS"), service_dict
            )
        if state != "EMPTY":
            return _business_result(
                ctx, operation, _metadata_summary(False, False, "METADATA_INVALID"), service_dict
            )
        if operation_cancellation_requested(ctx):
            return _cancelled_after_service(ctx, operation, "METADATA_APPEND_RECORD", service_dict)
        _append_image_valid(ctx, request.image.identity)
        return _written_result(ctx, operation, service_dict)
    except Exception as exc:
        return failure_result(ctx, operation, "METADATA_APPEND_RECORD", exc)


def append_boot_attempt(ctx: FlashOperationContext, request: AppendBootAttemptRequest):
    operation = "append_boot_attempt"
    try:
        if operation_cancellation_requested(ctx):
            return _cancelled_before_service(ctx, operation)
        service = ensure_service_attached(ctx)
        if isinstance(service, ServiceRuntimeCancellation):
            return _service_cancellation_result(ctx, operation, service)
        service_dict = service_summary_dict(service)
        if operation_cancellation_requested(ctx):
            return _cancelled_after_service(ctx, operation, "READ_METADATA_SUMMARY", service_dict)
        current = _read_metadata_summary(ctx)
        state = _metadata_state(current)
        if state == "INVALID":
            return _business_result(ctx, operation, _metadata_summary(False, False, "METADATA_INVALID"), service_dict)
        if state == "EMPTY":
            return _business_result(ctx, operation, _metadata_summary(False, False, "IMAGE_VALID_REQUIRED"), service_dict)
        if current.boot_attempt_limit <= 0 or current.boot_attempt_limit > 3:
            return _business_result(ctx, operation, _metadata_summary(False, False, "METADATA_INVALID"), service_dict)
        if current.app_confirmed:
            return _business_result(ctx, operation, _metadata_summary(False, True, "APP_CONFIRMED_ALREADY_EXISTS"), service_dict)
        if current.boot_attempt_count >= current.boot_attempt_limit or current.boot_attempt_count >= 3:
            return _business_result(ctx, operation, _metadata_summary(False, False, "BOOT_ATTEMPT_LIMIT_REACHED"), service_dict)
        if operation_cancellation_requested(ctx):
            return _cancelled_after_service(ctx, operation, "METADATA_APPEND_RECORD", service_dict)
        _append_current_image(ctx, MetadataRecordType.BOOT_ATTEMPT, current)
        return _written_result(ctx, operation, service_dict)
    except Exception as exc:
        return failure_result(ctx, operation, "METADATA_APPEND_RECORD", exc)


def append_app_confirmed(ctx: FlashOperationContext, request: AppendAppConfirmedRequest):
    operation = "append_app_confirmed"
    try:
        if operation_cancellation_requested(ctx):
            return _cancelled_before_service(ctx, operation)
        service = ensure_service_attached(ctx)
        if isinstance(service, ServiceRuntimeCancellation):
            return _service_cancellation_result(ctx, operation, service)
        service_dict = service_summary_dict(service)
        if operation_cancellation_requested(ctx):
            return _cancelled_after_service(ctx, operation, "READ_METADATA_SUMMARY", service_dict)
        current = _read_metadata_summary(ctx)
        state = _metadata_state(current)
        if state == "INVALID":
            return _business_result(ctx, operation, _metadata_summary(False, False, "METADATA_INVALID"), service_dict)
        if state == "EMPTY":
            return _business_result(ctx, operation, _metadata_summary(False, False, "IMAGE_VALID_REQUIRED"), service_dict)
        if current.app_confirmed:
            return _business_result(ctx, operation, _metadata_summary(False, True, "APP_CONFIRMED_ALREADY_EXISTS"), service_dict)
        if current.boot_attempt_count == 0:
            return _business_result(ctx, operation, _metadata_summary(False, False, "BOOT_ATTEMPT_REQUIRED"), service_dict)
        if operation_cancellation_requested(ctx):
            return _cancelled_after_service(ctx, operation, "METADATA_APPEND_RECORD", service_dict)
        _append_current_image(ctx, MetadataRecordType.APP_CONFIRMED, current)
        return _written_result(ctx, operation, service_dict)
    except Exception as exc:
        return failure_result(ctx, operation, "METADATA_APPEND_RECORD", exc)
