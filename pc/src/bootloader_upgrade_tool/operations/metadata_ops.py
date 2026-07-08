"""Metadata append operations."""

from __future__ import annotations

from dataclasses import dataclass

from ..images.identity import compare_image_identity_with_metadata
from ..images.models import ImageIdentity, PreparedFlashImage
from ..protocol.constants import BootSlot, MetadataRecordType
from ..protocol.models import split_u32
from ._service_runtime import ensure_service_attached
from .context import FlashOperationContext
from .results import failure_result, ok_result, service_summary_dict, transact
from .status_ops import _read_metadata_summary


@dataclass(frozen=True)
class AppendImageValidRequest:
    image: PreparedFlashImage


@dataclass(frozen=True)
class AppendBootAttemptRequest:
    image_identity: ImageIdentity


@dataclass(frozen=True)
class AppendAppConfirmedRequest:
    image_identity: ImageIdentity


def _append(ctx: FlashOperationContext, record_type: MetadataRecordType, identity: ImageIdentity) -> None:
    transact(
        ctx,
        "metadata_append_record",
        (
            int(record_type),
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


def _metadata_summary(written: bool, already_exists: bool, reason: str | None) -> dict[str, object]:
    return {"written": written, "already_exists": already_exists, "reason": reason}


def append_image_valid(ctx: FlashOperationContext, request: AppendImageValidRequest):
    operation = "append_image_valid"
    try:
        service = ensure_service_attached(ctx)
        current = _read_metadata_summary(ctx)
        if compare_image_identity_with_metadata(request.image.identity, current).same_image:
            return ok_result(
                ctx,
                operation,
                "READ_METADATA_SUMMARY",
                _metadata_summary(False, True, "IMAGE_VALID_ALREADY_EXISTS"),
                service=service_summary_dict(service),
            )
        _append(ctx, MetadataRecordType.IMAGE_VALID, request.image.identity)
        return ok_result(
            ctx,
            operation,
            "METADATA_APPEND_RECORD",
            _metadata_summary(True, False, None),
            service=service_summary_dict(service),
        )
    except Exception as exc:
        return failure_result(ctx, operation, "METADATA_APPEND_RECORD", exc)


def append_boot_attempt(ctx: FlashOperationContext, request: AppendBootAttemptRequest):
    operation = "append_boot_attempt"
    try:
        service = ensure_service_attached(ctx)
        current = _read_metadata_summary(ctx)
        if not compare_image_identity_with_metadata(request.image_identity, current).same_image:
            return ok_result(
                ctx,
                operation,
                "READ_METADATA_SUMMARY",
                _metadata_summary(False, False, "IMAGE_VALID_REQUIRED"),
                service=service_summary_dict(service),
            )
        if current.boot_attempt_count > 0:
            return ok_result(
                ctx,
                operation,
                "READ_METADATA_SUMMARY",
                _metadata_summary(False, True, "BOOT_ATTEMPT_ALREADY_EXISTS"),
                service=service_summary_dict(service),
            )
        _append(ctx, MetadataRecordType.BOOT_ATTEMPT, request.image_identity)
        return ok_result(ctx, operation, "METADATA_APPEND_RECORD", _metadata_summary(True, False, None), service=service_summary_dict(service))
    except Exception as exc:
        return failure_result(ctx, operation, "METADATA_APPEND_RECORD", exc)


def append_app_confirmed(ctx: FlashOperationContext, request: AppendAppConfirmedRequest):
    operation = "append_app_confirmed"
    try:
        service = ensure_service_attached(ctx)
        current = _read_metadata_summary(ctx)
        if not compare_image_identity_with_metadata(request.image_identity, current).same_image:
            return ok_result(
                ctx,
                operation,
                "READ_METADATA_SUMMARY",
                _metadata_summary(False, False, "IMAGE_VALID_REQUIRED"),
                service=service_summary_dict(service),
            )
        if current.boot_attempt_count == 0:
            return ok_result(
                ctx,
                operation,
                "READ_METADATA_SUMMARY",
                _metadata_summary(False, False, "BOOT_ATTEMPT_REQUIRED"),
                service=service_summary_dict(service),
            )
        if current.app_confirmed:
            return ok_result(
                ctx,
                operation,
                "READ_METADATA_SUMMARY",
                _metadata_summary(False, True, "APP_CONFIRMED_ALREADY_EXISTS"),
                service=service_summary_dict(service),
            )
        _append(ctx, MetadataRecordType.APP_CONFIRMED, request.image_identity)
        return ok_result(ctx, operation, "METADATA_APPEND_RECORD", _metadata_summary(True, False, None), service=service_summary_dict(service))
    except Exception as exc:
        return failure_result(ctx, operation, "METADATA_APPEND_RECORD", exc)
