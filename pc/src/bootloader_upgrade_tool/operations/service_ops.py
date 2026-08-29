"""Public Flash Service operations."""

from __future__ import annotations

from dataclasses import asdict

from ..protocol.models import ServiceStatus
from ._service_runtime import ServiceRuntimeCancellation, ServiceRuntimeSummary, ensure_service_attached
from .context import FlashOperationContext, OperationContext
from .results import (
    OperationFailure,
    OperationResult,
    cancelled_result,
    cancellation_cleanup_failure_result,
    failure_result,
    ok_result,
    service_summary_dict,
    transact,
)


def get_service_status(ctx: OperationContext) -> OperationResult:
    operation = "get_service_status"
    try:
        status = ServiceStatus.from_words(
            transact(ctx, "get_service_status", stage="GET_SERVICE_STATUS")
        )
        return ok_result(ctx, operation, "GET_SERVICE_STATUS", asdict(status))
    except Exception as exc:
        return failure_result(ctx, operation, "GET_SERVICE_STATUS", exc)


def _service_cancellation_result(
    ctx: FlashOperationContext,
    operation: str,
    item: ServiceRuntimeCancellation,
) -> OperationResult:
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
    return cancelled_result(
        ctx,
        operation,
        item.cancellation.stage,
        item.cancellation,
        service=service,
    )


def _service_action(service: ServiceRuntimeSummary) -> str:
    if service.reused:
        return "REUSED"
    if service.attach_performed:
        return "LOADED_AND_ATTACHED"
    raise OperationFailure(
        "SERVICE_ATTACH_FAILED",
        "service runtime returned no attach action",
        stage="SERVICE_ATTACH",
    )


def attach_flash_service(ctx: FlashOperationContext) -> OperationResult:
    operation = "attach_flash_service"
    try:
        service = ensure_service_attached(ctx)
        if isinstance(service, ServiceRuntimeCancellation):
            return _service_cancellation_result(ctx, operation, service)
        return ok_result(
            ctx,
            operation,
            "SERVICE_ATTACH",
            {"service_action": _service_action(service)},
            service=service_summary_dict(service),
        )
    except Exception as exc:
        return failure_result(ctx, operation, "SERVICE_ATTACH", exc)
