"""Operation result models and small internal failure helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from collections.abc import Mapping
from enum import Enum
from typing import Any, Callable, Sequence

from ..cancellation import cancellation_requested
from ..core.client import ProtocolDecodeError, ProtocolStatusError
from ..protocol.constants import Status
from ..protocol.command_timeouts import DEFAULT_COMMAND_TIMEOUT_MS
from ..targets import UnsupportedOperationError, require_command
from ..transport.base import TransportError


@dataclass(frozen=True)
class OperationErrorInfo:
    code: str
    message: str
    stage: str
    recoverable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class OperationCompletion(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED_AFTER_CANCEL_REQUEST = "completed_after_cancel_request"


_RECOVERY_ACTIONS = {
    "NONE",
    "RESTART_RAM_LOAD",
    "RESTART_SERVICE_LOAD",
    "RESTART_PROGRAM",
    "ERASE_AND_RESTART_PROGRAM",
    "RESTART_VERIFY",
    "RECONNECT_AND_RESTART_RAM_LOAD",
    "RECONNECT_AND_RESTART_SERVICE_LOAD",
    "RECONNECT_AND_RESTART_PROGRAM",
    "RECONNECT_ERASE_AND_RESTART_PROGRAM",
    "RECONNECT_AND_RESTART_VERIFY",
}


@dataclass(frozen=True)
class OperationCancellationInfo:
    stage: str
    current_words: int
    total_words: int
    protocol_state_clean: bool
    outcome_uncertain: bool
    connection_recovery_required: bool
    partial_flash_programmed: bool = False
    erase_before_retry_required: bool = False
    service_attached: bool | None = None
    recovery_action: str = "NONE"

    def __post_init__(self) -> None:
        if not self.stage:
            raise ValueError("stage must be non-empty")
        if self.current_words < 0 or self.total_words < 0 or self.current_words > self.total_words:
            raise ValueError("word counts must satisfy 0 <= current_words <= total_words")
        if self.recovery_action not in _RECOVERY_ACTIONS:
            raise ValueError("invalid recovery_action")
        if self.erase_before_retry_required and not self.partial_flash_programmed:
            raise ValueError("erase before retry requires partial Flash programming")
        if self.outcome_uncertain and not self.connection_recovery_required:
            raise ValueError("uncertain outcome requires connection recovery")
        if self.protocol_state_clean and (self.outcome_uncertain or self.connection_recovery_required):
            raise ValueError("clean protocol state cannot require recovery or have an uncertain outcome")


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    operation: str
    target: str
    stage: str
    summary: dict[str, Any]
    details: dict[str, Any] = field(default_factory=dict)
    service: dict[str, Any] | None = None
    warning: dict[str, Any] | None = None
    error: OperationErrorInfo | None = None
    completion: OperationCompletion | None = None
    cancellation: OperationCancellationInfo | None = None

    def __post_init__(self) -> None:
        completion = self.completion
        if completion is None:
            completion = OperationCompletion.SUCCEEDED if self.ok else OperationCompletion.FAILED
            object.__setattr__(self, "completion", completion)
        if completion is OperationCompletion.FAILED and self.error is None:
            raise RuntimeError("failed OperationResult requires error details")
        valid = {
            OperationCompletion.SUCCEEDED: self.ok and self.error is None and self.cancellation is None,
            OperationCompletion.FAILED: not self.ok and self.error is not None,
            OperationCompletion.CANCELLED: not self.ok and self.error is None and self.cancellation is not None,
            OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST: (
                self.ok and self.error is None and self.cancellation is not None
            ),
        }
        if not valid[completion]:
            raise ValueError(f"invalid OperationResult for completion {completion.value}")


@dataclass(frozen=True)
class ProgressEvent:
    operation: str
    target: str
    stage: str
    message: str
    current_words: int | None = None
    total_words: int | None = None
    chunk_words: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    cancellation_supported: bool = False


class OperationFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str,
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.info = OperationErrorInfo(
            code,
            message,
            stage,
            recoverable,
            {} if details is None else details,
        )


def operation_result_to_dict(result: OperationResult) -> dict[str, Any]:
    data = _to_plain(result)
    if result.error is None:
        data["error"] = None
    return data


def _to_plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value,type):
        return {item.name:_to_plain(getattr(value,item.name)) for item in fields(value)}
    if isinstance(value,Mapping):return {key:_to_plain(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):return [_to_plain(item) for item in value]
    return value


def emit_progress(ctx: Any, event: ProgressEvent) -> None:
    if ctx.progress is not None:
        ctx.progress(event)


def operation_cancellation_requested(ctx: object) -> bool:
    return cancellation_requested(getattr(ctx, "cancellation", None))


def cancelled_result(
    ctx: Any,
    operation: str,
    stage: str,
    cancellation: OperationCancellationInfo,
    *,
    service: dict[str, object] | None = None,
) -> OperationResult:
    return OperationResult(
        False,
        operation,
        ctx.target.name,
        stage,
        {},
        service=service,
        completion=OperationCompletion.CANCELLED,
        cancellation=cancellation,
    )


def completed_after_cancel_result(
    ctx: Any,
    operation: str,
    stage: str,
    summary: dict[str, object],
    cancellation: OperationCancellationInfo,
    *,
    details: dict[str, object] | None = None,
    service: dict[str, object] | None = None,
) -> OperationResult:
    return OperationResult(
        True,
        operation,
        ctx.target.name,
        stage,
        summary,
        {} if details is None else details,
        service,
        completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        cancellation=cancellation,
    )


def cancellation_cleanup_failure_result(
    ctx: Any,
    operation: str,
    stage: str,
    cancellation: OperationCancellationInfo,
    exc: Exception,
    *,
    service: dict[str, object] | None = None,
) -> OperationResult:
    cancellation = replace(
        cancellation,
        protocol_state_clean=False,
        outcome_uncertain=True,
        connection_recovery_required=True,
    )
    error = OperationErrorInfo(
        "CANCELLATION_CLEANUP_FAILED",
        str(exc),
        stage,
        recoverable=True,
        details={
            "cleanup_stage": stage,
            "exception_type": type(exc).__name__,
            "protocol_state_clean": False,
            "outcome_uncertain": True,
            "connection_recovery_required": True,
            "recovery_action": cancellation.recovery_action,
        },
    )
    return OperationResult(
        False,
        operation,
        ctx.target.name,
        stage,
        {},
        service=service,
        error=error,
        completion=OperationCompletion.FAILED,
        cancellation=cancellation,
    )


def cancellation_cleanup_succeeded(exc: Exception, *, partial: bool) -> bool:
    return (
        partial
        and isinstance(exc, ProtocolStatusError)
        and exc.status == int(Status.TOTAL_COUNT_MISMATCH)
    )


@dataclass(frozen=True)
class CancellableTransferOutcome:
    summary: dict[str, int]
    cancellation: OperationCancellationInfo | None = None
    cleanup_error: Exception | None = None
    completed_after_cancel: bool = False


def run_cancellable_transfer(
    ctx: Any,
    *,
    operation: str,
    packets: Sequence[Any],
    total_words: int,
    begin_stage: str,
    data_stage: str,
    end_stage: str,
    progress_message: str,
    send_begin: Callable[[], object],
    send_data: Callable[[Any], object],
    send_end: Callable[[], object],
    recovery_action: Callable[[int], str],
    reconnect_recovery_action: Callable[[int], str],
    partial_flash_programmed: Callable[[int], bool] = lambda _sent: False,
    service_attached: bool | None = None,
) -> CancellableTransferOutcome:
    packet_count = len(packets)

    def info(stage: str, current_words: int, *, reconnect: bool = False, none: bool = False):
        partial_flash = partial_flash_programmed(current_words)
        return OperationCancellationInfo(
            stage,
            current_words,
            total_words,
            not reconnect,
            reconnect,
            reconnect,
            partial_flash,
            partial_flash,
            service_attached,
            "NONE" if none else (
                reconnect_recovery_action(current_words) if reconnect else recovery_action(current_words)
            ),
        )

    if operation_cancellation_requested(ctx):
        return CancellableTransferOutcome({}, info(begin_stage, 0))

    send_begin()
    sent_words = 0
    sent_packets = 0
    cancel_observed = operation_cancellation_requested(ctx)

    for packet in packets:
        if cancel_observed:
            break
        send_data(packet)
        sent_packets += 1
        sent_words += len(packet.words)
        emit_progress(
            ctx,
            ProgressEvent(
                operation,
                ctx.target.name,
                data_stage,
                progress_message,
                sent_words,
                total_words,
                len(packet.words),
                cancellation_supported=True,
            ),
        )
        cancel_observed = operation_cancellation_requested(ctx)

    partial = sent_packets < packet_count or sent_words < total_words
    if cancel_observed and partial:
        try:
            send_end()
        except Exception as exc:
            if not cancellation_cleanup_succeeded(exc, partial=True):
                return CancellableTransferOutcome(
                    {},
                    info(end_stage, sent_words, reconnect=True),
                    cleanup_error=exc,
                )
        return CancellableTransferOutcome({}, info(end_stage, sent_words))

    send_end()
    summary = {"total_words": total_words, "packets": packet_count}
    if cancel_observed or operation_cancellation_requested(ctx):
        return CancellableTransferOutcome(
            summary,
            info(end_stage, total_words, none=True),
            completed_after_cancel=True,
        )
    return CancellableTransferOutcome(summary)


def transact(ctx: Any, field_name: str, payload: Sequence[int] = (), *, stage: str) -> tuple[int, ...]:
    command_id = require_command(ctx.target.command_set, field_name)
    return ctx.session.client.transact(
        command_id,
        payload,
        timeout_ms=DEFAULT_COMMAND_TIMEOUT_MS.get(command_id),
    )


def ok_result(
    ctx: Any,
    operation: str,
    stage: str,
    summary: dict[str, Any],
    *,
    details: dict[str, Any] | None = None,
    service: dict[str, Any] | None = None,
    warning: dict[str, Any] | None = None,
) -> OperationResult:
    return OperationResult(
        True,
        operation,
        ctx.target.name,
        stage,
        summary,
        {} if details is None else details,
        service,
        warning,
    )


def failure_result(ctx: Any, operation: str, stage: str, exc: Exception) -> OperationResult:
    if isinstance(exc, OperationFailure):
        error = exc.info
    elif isinstance(exc, UnsupportedOperationError):
        error = OperationErrorInfo("UNSUPPORTED_OPERATION", str(exc), stage)
    elif isinstance(exc, ProtocolStatusError):
        error = OperationErrorInfo(
            "DSP_STATUS_ERROR",
            str(exc),
            stage,
            details={"command": exc.command, "status": exc.status},
        )
    elif isinstance(exc, (ProtocolDecodeError, TransportError)):
        error = OperationErrorInfo("PROTOCOL_ERROR", str(exc), stage)
    else:
        raise exc
    return OperationResult(False, operation, ctx.target.name, error.stage, {}, error=error)


def service_summary_dict(summary: Any) -> dict[str, Any]:
    return _to_plain(summary)
