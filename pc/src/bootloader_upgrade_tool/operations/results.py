"""Operation result models and small internal failure helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from ..core.client import ProtocolDecodeError, ProtocolStatusError
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
    data = asdict(result)
    if result.error is None:
        data["error"] = None
    return data


def emit_progress(ctx: Any, event: ProgressEvent) -> None:
    if ctx.progress is not None:
        ctx.progress(event)


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
    return asdict(summary)
