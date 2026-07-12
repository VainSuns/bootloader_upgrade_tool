"""Read-only bootloader status operations."""

from __future__ import annotations

from dataclasses import asdict, replace

from ..core.client import ProtocolDecodeError
from ..protocol.boot_protocol_client import ProtocolInfo
from ..protocol.models import DeviceInfo, ErrorDetail, MetadataSummary
from .context import OperationContext
from .results import failure_result, ok_result, transact


def _model_summary(model: object) -> dict[str, object]:
    return asdict(model)


def _read_metadata_summary(ctx: OperationContext) -> MetadataSummary:
    return MetadataSummary.from_words(
        transact(ctx, "get_metadata_summary", stage="GET_METADATA_SUMMARY")
    )


def get_device_info(ctx: OperationContext):
    operation = "get_device_info"
    try:
        words = transact(ctx, "get_device_info", stage="GET_DEVICE_INFO")
    except Exception as exc:
        return _device_info_failure(ctx, operation, exc)
    try:
        info = DeviceInfo.from_words(words)
    except ValueError as exc:
        return _device_info_failure(ctx, operation, ProtocolDecodeError(str(exc)))
    try:
        ctx.session.client.device_info = info
        return ok_result(ctx, operation, "GET_DEVICE_INFO", _model_summary(info))
    except Exception as exc:
        return failure_result(ctx, operation, "GET_DEVICE_INFO", exc)


def _device_info_failure(ctx: OperationContext, operation: str, exc: Exception):
    result = failure_result(ctx, operation, "GET_DEVICE_INFO", exc)
    if result.error and result.error.code == "PROTOCOL_ERROR":
        return replace(result, error=replace(result.error, recoverable=True))
    return result


def get_protocol_info(ctx: OperationContext):
    operation = "get_protocol_info"
    try:
        info = ProtocolInfo.from_words(transact(ctx, "get_protocol_info", stage="GET_PROTOCOL_INFO"))
        return ok_result(ctx, operation, "GET_PROTOCOL_INFO", _model_summary(info))
    except Exception as exc:
        return failure_result(ctx, operation, "GET_PROTOCOL_INFO", exc)


def get_last_error(ctx: OperationContext):
    operation = "get_last_error"
    try:
        detail = ErrorDetail.from_words(transact(ctx, "get_last_error", stage="GET_LAST_ERROR"))
        return ok_result(ctx, operation, "GET_LAST_ERROR", _model_summary(detail))
    except Exception as exc:
        return failure_result(ctx, operation, "GET_LAST_ERROR", exc)


def get_metadata_summary(ctx: OperationContext):
    operation = "get_metadata_summary"
    try:
        summary = _read_metadata_summary(ctx)
        return ok_result(ctx, operation, "GET_METADATA_SUMMARY", _model_summary(summary))
    except Exception as exc:
        return failure_result(ctx, operation, "GET_METADATA_SUMMARY", exc)
