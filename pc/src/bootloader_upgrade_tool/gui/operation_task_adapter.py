"""Pure operation-layer to GUI task-model adapters."""

from __future__ import annotations

from bootloader_upgrade_tool.operations import (
    OperationCancellationInfo,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
    ProgressEvent,
)

from .runtime_models import (
    ErrorDisposition,
    GuiRuntimeError,
    GuiTaskWarning,
    ProgressMode,
    TaskCompletionAction,
    TaskExecutionResult,
    TaskFinalStatus,
    TaskProgressUpdate,
    TaskStepState,
)


_ASK_DISCONNECT_CODES = {
    "PROTOCOL_ERROR",
    "TARGET_MISMATCH",
    "CANCELLATION_CLEANUP_FAILED",
}


def operation_progress_to_task_update(
    task_id: str,
    step_id: str,
    event: ProgressEvent,
) -> TaskProgressUpdate:
    """Convert one operation progress event into one GUI progress update."""
    _non_empty_string(task_id, "task_id")
    _non_empty_string(step_id, "step_id")
    if not isinstance(event, ProgressEvent):
        raise TypeError("event must be ProgressEvent")

    current, total = event.current_words, event.total_words
    if (current is None) != (total is None):
        raise ValueError("current_words and total_words must both be present or absent")
    if current is None:
        mode = ProgressMode.INDETERMINATE
    else:
        _exact_int(current, "current_words")
        _exact_int(total, "total_words")
        if total <= 0 or current < 0 or current > total:
            raise ValueError("progress must satisfy 0 <= current_words <= total_words and total_words > 0")
        mode = ProgressMode.DETERMINATE

    if event.chunk_words is not None:
        _exact_int(event.chunk_words, "chunk_words")
        if event.chunk_words < 0:
            raise ValueError("chunk_words must be non-negative")
    if type(event.cancellation_supported) is not bool:
        raise TypeError("cancellation_supported must be bool")

    return TaskProgressUpdate(
        task_id,
        step_id,
        TaskStepState.PROGRESS,
        event.stage,
        event.message,
        current,
        total,
        mode,
        event,
        {
            "operation": event.operation,
            "target": event.target,
            "chunk_words": event.chunk_words,
            "cancellation_supported": event.cancellation_supported,
            "operation_details": event.details,
        },
    )


def operation_result_to_task_result(
    task_id: str,
    result: OperationResult,
    *,
    success_summary: str | None = None,
    success_message: str | None = None,
    payload: object | None = None,
    completion_action: TaskCompletionAction = TaskCompletionAction.NONE,
) -> TaskExecutionResult:
    """Convert one typed operation result into one immutable GUI task result."""
    _non_empty_string(task_id, "task_id")
    if not isinstance(result, OperationResult):
        raise TypeError("result must be OperationResult")
    if not isinstance(result.completion, OperationCompletion):
        raise TypeError("result.completion must be OperationCompletion")
    if result.cancellation is not None and not isinstance(result.cancellation, OperationCancellationInfo):
        raise TypeError("result.cancellation must be OperationCancellationInfo or None")
    if not isinstance(completion_action, TaskCompletionAction):
        raise TypeError("completion_action must be TaskCompletionAction")
    _optional_string(success_summary, "success_summary")
    _optional_string(success_message, "success_message")

    common = {"step_results": (result,), "payload": payload}
    if result.completion is OperationCompletion.SUCCEEDED:
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.SUCCEEDED,
            result.operation if success_summary is None else success_summary,
            result.stage if success_message is None else success_message,
            completion_action=completion_action,
            **common,
        )

    if result.completion in {
        OperationCompletion.CANCELLED,
        OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
    }:
        cancellation = _require_cancellation(result)
        completed = result.completion is OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST
        summary = (
            "Operation completed after cancellation request"
            if completed
            else "Operation cancelled"
        )
        message = (
            "The current operation completed successfully; no following operation was started."
            if completed
            else f"Cancellation observed during {cancellation.stage}"
        )
        warning = GuiTaskWarning(
            "OPERATION_COMPLETED_AFTER_CANCEL_REQUEST" if completed else "OPERATION_CANCELLED",
            message,
            cancellation.stage,
            _cancellation_details(result, cancellation),
        )
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST if completed else TaskFinalStatus.CANCELLED,
            summary,
            message,
            warning=warning,
            completion_action=completion_action if completed else TaskCompletionAction.NONE,
            cancel_requested=True,
            **common,
        )

    if not isinstance(result.error, OperationErrorInfo):
        raise TypeError("failed OperationResult requires OperationErrorInfo")
    cancellation = result.cancellation
    uncertain = bool(
        cancellation
        and (cancellation.outcome_uncertain or cancellation.connection_recovery_required)
    )
    disposition = (
        ErrorDisposition.ASK_DISCONNECT
        if result.error.code in _ASK_DISCONNECT_CODES or uncertain
        else ErrorDisposition.SHOW_ONLY
    )
    details = dict(result.error.details)
    details.setdefault("operation", result.operation)
    details.setdefault("target", result.target)
    if cancellation is not None:
        if "cancellation" in details:
            raise ValueError("error details already contain cancellation")
        details["cancellation"] = _cancellation_details(result, cancellation)
    error = GuiRuntimeError(
        result.error.code,
        result.error.message,
        result.error.stage,
        disposition,
        task_id,
        result.error.recoverable,
        disposition is ErrorDisposition.ASK_DISCONNECT,
        details,
    )
    return TaskExecutionResult(
        task_id,
        TaskFinalStatus.FAILED,
        "Operation failed",
        result.error.message,
        error=error,
        completion_action=TaskCompletionAction.NONE,
        cancel_requested=cancellation is not None,
        **common,
    )


def _cancellation_details(
    result: OperationResult,
    cancellation: OperationCancellationInfo,
) -> dict[str, object]:
    return {
        "stage": cancellation.stage,
        "current_words": cancellation.current_words,
        "total_words": cancellation.total_words,
        "protocol_state_clean": cancellation.protocol_state_clean,
        "outcome_uncertain": cancellation.outcome_uncertain,
        "connection_recovery_required": cancellation.connection_recovery_required,
        "partial_flash_programmed": cancellation.partial_flash_programmed,
        "erase_before_retry_required": cancellation.erase_before_retry_required,
        "service_attached": cancellation.service_attached,
        "recovery_action": cancellation.recovery_action,
        "operation": result.operation,
        "target": result.target,
    }


def _require_cancellation(result: OperationResult) -> OperationCancellationInfo:
    if not isinstance(result.cancellation, OperationCancellationInfo):
        raise ValueError(f"{result.completion.name} requires OperationCancellationInfo")
    return result.cancellation


def _non_empty_string(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str")
    if not value:
        raise ValueError(f"{name} must be non-empty")


def _optional_string(value: object, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be str or None")


def _exact_int(value: object, name: str) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be int")
