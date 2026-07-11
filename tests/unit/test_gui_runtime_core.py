from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bootloader_upgrade_tool.gui.runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)
from bootloader_upgrade_tool.gui.runtime_ports import CancellationToken
from bootloader_upgrade_tool.gui.workers import TaskWorker, WorkerFinishedMessage, WorkerResultMessage
from bootloader_upgrade_tool.gui.runtime_models import TaskExecutionResult, TaskFinalStatus


class _Job:
    task_id = "id"
    def execute(self, cancellation, progress):
        return TaskExecutionResult("id", TaskFinalStatus.SUCCEEDED, "ok", "ok")


def test_plan_rejects_state_machine_breaking_shapes() -> None:
    step = TaskStepPlan("prepare", "Prepare", ProgressMode.INDETERMINATE)
    with pytest.raises(ValueError):
        TaskPlan("id", "Title", (), TaskConnectionRequirement.NONE, True, CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT)
    with pytest.raises(ValueError):
        TaskPlan("id", "Title", (step, step), TaskConnectionRequirement.NONE, True, CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT)


def test_cancellation_token_is_idempotent() -> None:
    token = CancellationToken()
    assert not token.is_cancel_requested()
    token.request_cancel()
    token.request_cancel()
    assert token.is_cancel_requested()


def test_worker_emits_one_result_and_finished() -> None:
    worker = TaskWorker("id", 2, _Job(), CancellationToken(), True)
    results, finished = [], []
    worker.resultReady.connect(results.append)
    worker.workFinished.connect(finished.append)
    worker.run()
    assert isinstance(results[0], WorkerResultMessage)
    assert isinstance(finished[0], WorkerFinishedMessage)
