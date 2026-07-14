from types import MappingProxyType

import pytest

from bootloader_upgrade_tool.gui.operation_task_adapter import (
    operation_progress_to_task_update,
    operation_result_to_task_result,
)
from bootloader_upgrade_tool.gui.runtime_models import (
    ErrorDisposition,
    ProgressMode,
    TaskCompletionAction,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.operations import (
    OperationCancellationInfo,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
    ProgressEvent,
)


def cancellation(**overrides):
    values = dict(
        stage="PROGRAM_END",
        current_words=8,
        total_words=16,
        protocol_state_clean=True,
        outcome_uncertain=False,
        connection_recovery_required=False,
        partial_flash_programmed=True,
        erase_before_retry_required=True,
        service_attached=True,
        recovery_action="ERASE_AND_RESTART_PROGRAM",
    )
    values.update(overrides)
    return OperationCancellationInfo(**values)


def operation(completion=OperationCompletion.SUCCEEDED, *, cancellation_info=None, code="DSP_STATUS_ERROR"):
    failed = completion is OperationCompletion.FAILED
    return OperationResult(
        not failed and completion is not OperationCompletion.CANCELLED,
        "program_flash_image",
        "CPU1",
        "PROGRAM_END",
        {"written": 8},
        details={"blocks": [{"words": 8}]},
        service={"attached": True},
        warning={"code": "slow"},
        error=OperationErrorInfo(code, "operation failed", "PROGRAM_DATA", True, {"status": 7}) if failed else None,
        completion=completion,
        cancellation=cancellation_info,
    )


def test_determinate_progress_preserves_all_operation_evidence() -> None:
    details = {"packet": {"index": 2}}
    event = ProgressEvent("program", "CPU1", "PROGRAM_DATA", "Writing", 8, 16, 8, details, True)
    update = operation_progress_to_task_update("task", "program", event)
    details["packet"]["index"] = 9
    assert update.progress_mode is ProgressMode.DETERMINATE
    assert (update.current, update.total) == (8, 16)
    assert update.details["chunk_words"] == 8
    assert update.details["cancellation_supported"] is True
    assert update.details["operation_details"]["packet"]["index"] == 2
    assert isinstance(update.raw_event, ProgressEvent)
    with pytest.raises(TypeError):
        update.raw_event.details["new"] = 1


def test_indeterminate_progress_maps_none_counts() -> None:
    update = operation_progress_to_task_update(
        "task", "step", ProgressEvent("erase", "CPU1", "ERASE", "Erasing")
    )
    assert update.progress_mode is ProgressMode.INDETERMINATE
    assert update.current is update.total is None


@pytest.mark.parametrize(
    "event",
    [
        ProgressEvent("op", "CPU1", "s", "m", 1, None),
        ProgressEvent("op", "CPU1", "s", "m", None, 1),
        ProgressEvent("op", "CPU1", "s", "m", 0, 0),
        ProgressEvent("op", "CPU1", "s", "m", 2, 1),
        ProgressEvent("op", "CPU1", "s", "m", -1, 1),
        ProgressEvent("op", "CPU1", "s", "m", True, 1),
        ProgressEvent("op", "CPU1", "s", "m", 0, True),
        ProgressEvent("op", "CPU1", "s", "m", chunk_words=-1),
        ProgressEvent("op", "CPU1", "s", "m", chunk_words=True),
        ProgressEvent("op", "CPU1", "s", "m", cancellation_supported=1),
    ],
)
def test_invalid_progress_contract_is_rejected(event) -> None:
    with pytest.raises((TypeError, ValueError)):
        operation_progress_to_task_update("task", "step", event)


@pytest.mark.parametrize(
    ("task_id", "step_id", "event"),
    [("", "step", ProgressEvent("o", "t", "s", "m")), ("task", "", ProgressEvent("o", "t", "s", "m")), ("task", "step", {})],
)
def test_invalid_progress_inputs_are_rejected(task_id, step_id, event) -> None:
    with pytest.raises((TypeError, ValueError)):
        operation_progress_to_task_update(task_id, step_id, event)


def test_success_mapping_defaults_overrides_action_and_payload() -> None:
    result = operation()
    mapped = operation_result_to_task_result(
        "task", result, payload={"image": {"words": [1]}}, completion_action=TaskCompletionAction.RELEASE_CONNECTION
    )
    assert mapped.status is TaskFinalStatus.SUCCEEDED
    assert (mapped.summary, mapped.message) == (result.operation, result.stage)
    assert mapped.warning is mapped.error is None and not mapped.cancel_requested
    assert mapped.completion_action is TaskCompletionAction.RELEASE_CONNECTION
    assert mapped.step_results[0].summary["written"] == 8
    assert mapped.payload["image"]["words"] == (1,)
    overridden = operation_result_to_task_result("task", result, success_summary="Done", success_message="Finished")
    assert (overridden.summary, overridden.message) == ("Done", "Finished")


def test_clean_cancelled_mapping_preserves_complete_evidence() -> None:
    mapped = operation_result_to_task_result(
        "task", operation(OperationCompletion.CANCELLED, cancellation_info=cancellation()), completion_action=TaskCompletionAction.RELEASE_CONNECTION
    )
    assert mapped.status is TaskFinalStatus.CANCELLED and mapped.cancel_requested
    assert mapped.error is None and mapped.warning.code == "OPERATION_CANCELLED"
    assert mapped.completion_action is TaskCompletionAction.NONE
    assert set(mapped.warning.details) == {
        "stage", "current_words", "total_words", "protocol_state_clean", "outcome_uncertain",
        "connection_recovery_required", "partial_flash_programmed", "erase_before_retry_required",
        "service_attached", "recovery_action", "operation", "target",
    }
    assert mapped.warning.details["stage"] == "PROGRAM_END"
    assert mapped.warning.details["connection_recovery_required"] is False


def test_completed_after_cancel_preserves_status_action_and_evidence() -> None:
    mapped = operation_result_to_task_result(
        "task",
        operation(OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST, cancellation_info=cancellation(current_words=16)),
        completion_action=TaskCompletionAction.RELEASE_CONNECTION,
    )
    assert mapped.status is TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST
    assert mapped.warning.code == "OPERATION_COMPLETED_AFTER_CANCEL_REQUEST"
    assert "completed successfully" in mapped.message
    assert mapped.completion_action is TaskCompletionAction.RELEASE_CONNECTION


@pytest.mark.parametrize("completion", [OperationCompletion.CANCELLED, OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST])
def test_cancel_completion_without_evidence_is_rejected(completion) -> None:
    result = operation(completion, cancellation_info=cancellation(current_words=16) if completion is OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST else cancellation())
    object.__setattr__(result, "cancellation", None)
    with pytest.raises(ValueError):
        operation_result_to_task_result("task", result)


@pytest.mark.parametrize("code", ["DSP_STATUS_ERROR", "UNSUPPORTED_OPERATION", "SOMETHING_NEW"])
def test_normal_failure_maps_show_only_and_preserves_error(code) -> None:
    mapped = operation_result_to_task_result("task", operation(OperationCompletion.FAILED, code=code))
    assert mapped.status is TaskFinalStatus.FAILED and not mapped.cancel_requested
    assert mapped.error.disposition is ErrorDisposition.SHOW_ONLY
    assert (mapped.error.code, mapped.error.message, mapped.error.stage, mapped.error.recoverable) == (
        code, "operation failed", "PROGRAM_DATA", True
    )
    assert mapped.error.details["status"] == 7
    assert mapped.error.details["operation"] == "program_flash_image"


@pytest.mark.parametrize("code", ["PROTOCOL_ERROR", "TARGET_MISMATCH", "CANCELLATION_CLEANUP_FAILED"])
def test_known_uncertain_failure_codes_ask_disconnect(code) -> None:
    mapped = operation_result_to_task_result("task", operation(OperationCompletion.FAILED, code=code))
    assert mapped.error.disposition is ErrorDisposition.ASK_DISCONNECT
    assert mapped.error.outcome_uncertain
    assert mapped.completion_action is TaskCompletionAction.NONE


@pytest.mark.parametrize("field", ["outcome_uncertain", "connection_recovery_required"])
def test_cancellation_recovery_evidence_asks_disconnect(field) -> None:
    values = dict(protocol_state_clean=False, connection_recovery_required=True, recovery_action="RECONNECT_ERASE_AND_RESTART_PROGRAM")
    if field == "outcome_uncertain":
        values["outcome_uncertain"] = True
    result = operation(OperationCompletion.FAILED, cancellation_info=cancellation(**values), code="DSP_STATUS_ERROR")
    mapped = operation_result_to_task_result("task", result)
    assert mapped.status is TaskFinalStatus.FAILED and mapped.cancel_requested
    assert mapped.warning is None and mapped.error.disposition is ErrorDisposition.ASK_DISCONNECT
    assert mapped.error.details["cancellation"][field] is True


def test_failed_without_error_and_invalid_completion_are_rejected() -> None:
    failed = operation(OperationCompletion.FAILED)
    object.__setattr__(failed, "error", None)
    with pytest.raises(TypeError):
        operation_result_to_task_result("task", failed)
    succeeded = operation()
    object.__setattr__(succeeded, "completion", "SUCCEEDED")
    with pytest.raises(TypeError):
        operation_result_to_task_result("task", succeeded)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"task_id": "", "result": operation()},
        {"task_id": "task", "result": object()},
        {"task_id": "task", "result": operation(), "completion_action": "NONE"},
        {"task_id": "task", "result": operation(), "success_summary": 1},
        {"task_id": "task", "result": operation(), "success_message": 1},
    ],
)
def test_invalid_result_inputs_are_rejected(kwargs) -> None:
    with pytest.raises((TypeError, ValueError)):
        operation_result_to_task_result(**kwargs)


def test_all_nested_result_data_is_immutable() -> None:
    success = operation_result_to_task_result("task", operation(), payload={"nested": {"x": 1}})
    stored = success.step_results[0]
    for mapping in (stored.summary, stored.details, stored.service, stored.warning, success.payload):
        assert isinstance(mapping, MappingProxyType)
        with pytest.raises(TypeError):
            mapping["new"] = 1

    failed = operation_result_to_task_result("task", operation(OperationCompletion.FAILED))
    with pytest.raises(TypeError):
        failed.step_results[0].error.details["new"] = 1
    with pytest.raises(TypeError):
        failed.error.details["new"] = 1

    cancelled = operation_result_to_task_result("task", operation(OperationCompletion.CANCELLED, cancellation_info=cancellation()))
    with pytest.raises(TypeError):
        cancelled.warning.details["new"] = 1


def test_adapter_functions_are_available_through_lazy_gui_exports() -> None:
    from bootloader_upgrade_tool import gui

    assert gui.operation_progress_to_task_update is operation_progress_to_task_update
    assert gui.operation_result_to_task_result is operation_result_to_task_result
