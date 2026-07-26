from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.gui.memory_models import MemoryReadTaskSnapshot, MemoryRefreshRequest
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import (
    CompletionPolicy,
    ConnectionInfo,
    TaskConnectionRequirement,
    TaskFinalStatus,
    TaskStepState,
)
from bootloader_upgrade_tool.gui.runtime_v2_events import ConnectionClosed, ConnectionOpened
from bootloader_upgrade_tool.gui.runtime_v2_models import ConnectionGeneration, DataFreshness, RuntimeCpuId
from bootloader_upgrade_tool.operations import (
    OperationCancellationInfo,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
    ProgressEvent,
)
from bootloader_upgrade_tool.protocol.constants import CpuId, DeviceId, Feature
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


NOW = datetime(2026, 7, 27, 1, 2, 3, tzinfo=timezone.utc)


def test_memory_request_validates_gui_bounds_and_builds_single_cancellable_plan() -> None:
    generation = ConnectionGeneration(4)
    request = MemoryRefreshRequest("connection", "cpu1", generation, 0xFFFFFFFE, 2)
    plan = request.create_plan("task")
    assert plan.title == "Read CPU1 Memory"
    assert plan.cancellable and len(plan.steps) == 1 and plan.steps[0].step_id == "read_memory"
    assert plan.connection_requirement is TaskConnectionRequirement.CONNECTED
    assert plan.completion_policy is CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS

    for values in (
        ("", "cpu1", generation, 0, 1),
        ("connection", "bad", generation, 0, 1),
        ("connection", "cpu1", generation, True, 1),
        ("connection", "cpu1", generation, 0, False),
        ("connection", "cpu1", generation, 0, 4097),
        ("connection", "cpu1", generation, 0xFFFFFFFF, 2),
    ):
        with pytest.raises((TypeError, ValueError)):
            MemoryRefreshRequest(*values)


class _Executor:
    def __init__(self, session, generation):
        self.session = session
        self.generation = generation
        self.is_valid = True
        self.calls = 0

    def execute_foreground(self, generation, action):
        assert generation == self.generation
        self.calls += 1
        return action(self.session)


def _info(cpu_id):
    return DeviceInfo(
        int(DeviceId.F28377D), int(cpu_id), 1, 0, 0, 1,
        int(Feature.MEMORY_READ), 256, 8, 2, 2,
    )


def _profile(cpu_id):
    if cpu_id is RuntimeCpuId.CPU1:
        return CPU1_PROFILE
    return replace(
        CPU2_PROFILE,
        command_set=replace(CPU2_PROFILE.command_set, memory_read=0x0230),
    )


def _unexpected_metadata(_ctx):
    raise AssertionError("metadata called")


def _backend(operation, *, cpu_id=RuntimeCpuId.CPU1, metadata_operation=None):
    profile = _profile(cpu_id)
    info = _info(CpuId(int(profile.cpu_id)))
    session = SimpleNamespace(client=SimpleNamespace(device_info=info))
    connection_info = ConnectionInfo("connection", "SCI", "COM3", NOW, cpu_id.value)
    backend = RuntimeBackend(
        memory_read_operation=operation,
        metadata_operation=metadata_operation or _unexpected_metadata,
        maintenance_clock=lambda: NOW,
    )
    backend._session = session
    backend._target = profile
    backend._device_info = info
    backend._connection_info = connection_info
    backend._runtime_v2_dispatcher.dispatch(ConnectionOpened(connection_info))
    executor = _Executor(session, backend.connection_generation)
    backend._connection_command_executor = executor
    request = MemoryRefreshRequest(
        "connection", cpu_id.value, backend.connection_generation, 0x12345678, 3
    )
    return backend, request, executor, profile


def _success(ctx, request):
    return OperationResult(
        True,
        "memory_read",
        ctx.target.name,
        "MEMORY_READ",
        {"start_address": request.start_address, "word_count": request.word_count},
        {"words": (1, 2, 3)},
    )


def _failure(ctx, _request):
    return OperationResult(
        False,
        "memory_read",
        ctx.target.name,
        "MEMORY_READ",
        {},
        error=OperationErrorInfo("READ_FAILED", "read failed", "MEMORY_READ", True),
    )


def _cancelled(ctx, _request):
    cancellation = OperationCancellationInfo("MEMORY_READ", 1, 3, True, False, False)
    return OperationResult(
        False,
        "memory_read",
        ctx.target.name,
        "MEMORY_READ",
        {},
        completion=OperationCompletion.CANCELLED,
        cancellation=cancellation,
    )


def _completed_after_cancel(ctx, _request):
    cancellation = OperationCancellationInfo("MEMORY_READ", 3, 3, True, False, False)
    return OperationResult(
        True,
        "memory_read",
        ctx.target.name,
        "MEMORY_READ",
        {"word_count": 3},
        {"words": (4, 5, 6)},
        completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        cancellation=cancellation,
    )


def test_memory_request_only_calls_injected_operation_with_captured_profile_and_foreground_lease() -> None:
    calls = []
    metadata_calls = []

    def operation(ctx, request):
        calls.append((ctx, request))
        return _success(ctx, request)

    backend, request, executor, profile = _backend(
        operation, metadata_operation=lambda _ctx: metadata_calls.append(1)
    )
    progress = []
    result = backend.execute("task", request, object(), progress.append)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(calls) == executor.calls == 1
    assert metadata_calls == []
    assert calls[0][0].target is profile
    assert calls[0][0].session is executor.session
    assert (calls[0][1].start_address, calls[0][1].word_count) == (0x12345678, 3)
    assert isinstance(result.payload, MemoryReadTaskSnapshot)
    assert progress[0].step_state is TaskStepState.STARTED


@pytest.mark.parametrize("cpu_id", tuple(RuntimeCpuId))
def test_success_dispatches_only_to_requested_cpu(cpu_id) -> None:
    backend, request, _executor, _profile_value = _backend(_success, cpu_id=cpu_id)
    other = next(item for item in RuntimeCpuId if item is not cpu_id)

    result = backend.execute("task", request, None, None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert backend.runtime_v2_snapshot.memory_states[cpu_id].words == (1, 2, 3)
    assert backend.runtime_v2_snapshot.memory_states[other].words == ()
    assert backend.runtime_v2_snapshot.memory_states[cpu_id].read_at == NOW


@pytest.mark.parametrize(
    ("request_change", "code"),
    (
        (lambda request: replace(request, target_key="cpu2"), "STALE_TARGET"),
        (lambda request: replace(request, expected_connection_generation=ConnectionGeneration()), "STALE_CONNECTION"),
    ),
)
def test_target_or_generation_mismatch_has_zero_operation_calls(request_change, code) -> None:
    calls = []
    backend, request, executor, _profile_value = _backend(lambda *_args: calls.append(1))

    result = backend.execute("task", request_change(request), None, None)

    assert result.status is TaskFinalStatus.FAILED and result.error.code == code
    assert calls == [] and executor.calls == 0
    assert all(not state.words for state in backend.runtime_v2_snapshot.memory_states.values())


def test_profile_without_memory_command_has_zero_operation_calls() -> None:
    calls = []
    backend, request, executor, _profile_value = _backend(
        lambda *_args: calls.append(1), cpu_id=RuntimeCpuId.CPU2
    )
    backend._target = CPU2_PROFILE

    result = backend.execute("task", request, None, None)

    assert result.error.code == "UNSUPPORTED_OPERATION"
    assert calls == [] and executor.calls == 0


def test_failure_preserves_old_words_as_stale_and_first_failure_stays_empty() -> None:
    backend, request, _executor, _profile_value = _backend(_failure)
    first = backend.execute("first", request, None, None)
    state = backend.runtime_v2_snapshot.memory_states[RuntimeCpuId.CPU1]
    assert first.status is TaskFinalStatus.FAILED
    assert state.freshness is DataFreshness.EMPTY and state.read_error.code == "READ_FAILED"

    backend.record_memory_read_success(
        RuntimeCpuId.CPU1, backend.connection_generation, 0x1000, (0xCAFE,), NOW
    )
    backend.execute("second", replace(request, start_address=0x2000), None, None)
    state = backend.runtime_v2_snapshot.memory_states[RuntimeCpuId.CPU1]
    assert state.freshness is DataFreshness.STALE
    assert state.base_address == 0x1000 and state.words == (0xCAFE,)


def test_cancelled_does_not_overwrite_retained_snapshot() -> None:
    backend, request, _executor, _profile_value = _backend(_cancelled)
    backend.record_memory_read_success(
        RuntimeCpuId.CPU1, backend.connection_generation, 0x1000, (0xCAFE,), NOW
    )

    result = backend.execute("task", request, object(), None)

    state = backend.runtime_v2_snapshot.memory_states[RuntimeCpuId.CPU1]
    assert result.status is TaskFinalStatus.CANCELLED
    assert state.base_address == 0x1000 and state.words == (0xCAFE,)
    assert state.freshness is DataFreshness.FRESH


def test_completed_after_cancel_commits_complete_snapshot() -> None:
    backend, request, _executor, _profile_value = _backend(_completed_after_cancel)

    result = backend.execute("task", request, object(), None)

    assert result.status is TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST
    assert backend.runtime_v2_snapshot.memory_states[RuntimeCpuId.CPU1].words == (4, 5, 6)


def test_stale_completion_does_not_dispatch_result() -> None:
    backend = None

    def operation(ctx, request):
        connection = backend.runtime_v2_snapshot.connection
        backend._runtime_v2_dispatcher.dispatch(
            ConnectionClosed(connection.connection_id, connection.generation)
        )
        return _success(ctx, request)

    backend, request, _executor, _profile_value = _backend(operation)
    result = backend.execute("task", request, None, None)

    assert result.status is TaskFinalStatus.FAILED
    assert result.error.code == "STALE_CONNECTION"
    assert backend.runtime_v2_snapshot.memory_states[RuntimeCpuId.CPU1].words == ()


def test_operation_progress_uses_adapter_without_raw_words() -> None:
    def operation(ctx, request):
        ctx.progress(
            ProgressEvent(
                "memory_read",
                ctx.target.name,
                "MEMORY_READ",
                "Memory read progress",
                2,
                request.word_count,
                2,
                {"frame_index": 0},
                True,
            )
        )
        return _success(ctx, request)

    backend, request, _executor, _profile_value = _backend(operation)
    updates = []
    backend.execute("task", request, None, updates.append)
    determinate = next(update for update in updates if update.step_state is TaskStepState.PROGRESS)

    assert (determinate.current, determinate.total) == (2, 3)
    assert "words" not in repr(determinate.details)


def test_invalid_success_payload_becomes_failure_without_replacing_old_words() -> None:
    def invalid(ctx, _request):
        return OperationResult(True, "memory_read", ctx.target.name, "MEMORY_READ", {}, {"words": (1,)})

    backend, request, _executor, _profile_value = _backend(invalid)
    backend.record_memory_read_success(
        RuntimeCpuId.CPU1, backend.connection_generation, 0x1000, (0xCAFE,), NOW
    )
    result = backend.execute("task", request, None, None)
    state = backend.runtime_v2_snapshot.memory_states[RuntimeCpuId.CPU1]

    assert result.error.code == "INVALID_OPERATION_RESULT"
    assert state.words == (0xCAFE,) and state.freshness is DataFreshness.STALE
