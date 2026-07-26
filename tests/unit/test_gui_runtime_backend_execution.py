from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic

import pytest
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_execution_models import (
    AdvancedFlashAppRunSnapshot,
    RunAdvancedFlashAppRequest,
)
from bootloader_upgrade_tool.gui.connection_command_executor import ConnectionCommandExecutor
from bootloader_upgrade_tool.gui.controller import GuiController
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, RuntimeSnapshot, RuntimeState, TaskCompletionAction, TaskFinalStatus, TaskStepState
from bootloader_upgrade_tool.gui.runtime_v2_events import ConnectionOpened, MetadataReadSucceeded
from bootloader_upgrade_tool.gui.runtime_v2_models import ConnectionGeneration, RuntimeCpuId
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataStatusSnapshot
from bootloader_upgrade_tool.operations import OperationErrorInfo, OperationResult, RunFlashAppRequest, run_flash_app
from bootloader_upgrade_tool.protocol.constants import Command, Target
from bootloader_upgrade_tool.protocol.models import split_u32
from bootloader_upgrade_tool.protocol import DeviceInfo
from bootloader_upgrade_tool.protocol.models import MetadataSummary
from bootloader_upgrade_tool.targets import CPU1_PROFILE


def metadata(connection_id="connection", *, entry_point=0x82400, **changes):
    raw = MetadataSummary(
        1, 1, 1, 0, 0, 3, 1, 0, 0, 0, entry_point, 0x1234,
        1, 1, 0, 0, 1, 1, 8, 0x377D, 1,
    )
    result = OperationResult(True, "get_metadata_summary", "CPU1", "GET_METADATA_SUMMARY", {})
    value = MetadataStatusSnapshot(
        connection_id, "cpu1", result, raw, True, True, True,
        False, False, False, LoadedImageMatch.NO_PREPARED_IMAGE, False,
    )
    return replace(value, **changes)


def connected_backend(run_operation):
    traps = {
        name: (lambda *_a, name=name, **_k: (_ for _ in ()).throw(
            AssertionError(f"unexpected {name}")
        ))
        for name in (
            "metadata", "prepare_flash", "prepare_service", "append_image_valid",
            "append_boot_attempt", "append_app_confirmed",
        )
    }
    backend = RuntimeBackend(
        run_flash_operation=run_operation,
        metadata_operation=traps["metadata"],
        prepare_flash_operation=traps["prepare_flash"],
        prepare_service_operation=traps["prepare_service"],
        append_image_valid_operation=traps["append_image_valid"],
        append_boot_attempt_operation=traps["append_boot_attempt"],
        append_app_confirmed_operation=traps["append_app_confirmed"],
    )
    backend._session = object()
    backend._target = CPU1_PROFILE
    backend._device_info = DeviceInfo(0x377D, 1, 1, 0, 0, 1, 0, 64, 56, 0, 0)
    backend._connection_info = ConnectionInfo(
        "connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu1"
    )
    backend._runtime_v2_dispatcher.dispatch(ConnectionOpened(backend._connection_info))
    backend._connection_command_executor = ConnectionCommandExecutor(
        backend._session, backend.connection_generation
    )
    current = metadata()
    backend._runtime_v2_dispatcher.dispatch(
        MetadataReadSucceeded(RuntimeCpuId.CPU1, backend.connection_generation, current)
    )
    return backend, current


def request(backend, current):
    return RunAdvancedFlashAppRequest(
        "connection", "cpu1", backend.connection_generation, current,
        current.raw_metadata.entry_point,
    )


def test_success_calls_only_run_operation_and_releases_connection() -> None:
    calls = []

    def run(ctx, value):
        calls.append((ctx, value))
        return OperationResult(True, "run_flash_app", ctx.target.name, "RUN", {})

    backend, current = connected_backend(run)
    progress = []
    result = backend.execute("run", request(backend, current), None, progress.append)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert result.completion_action is TaskCompletionAction.RELEASE_CONNECTION
    assert type(result.payload) is AdvancedFlashAppRunSnapshot
    assert len(calls) == 1
    assert calls[0][0].target is CPU1_PROFILE
    assert type(calls[0][1]) is RunFlashAppRequest
    assert calls[0][1].entry_point == 0x82400
    assert [update.step_state for update in progress] == [
        TaskStepState.STARTED, TaskStepState.COMPLETED
    ]


def test_run_failure_does_not_release_connection() -> None:
    backend, current = connected_backend(
        lambda ctx, _request: OperationResult(
            False, "run_flash_app", ctx.target.name, "RUN", {},
            error=OperationErrorInfo("RUN_FAILED", "failed", "RUN"),
        )
    )

    result = backend.execute("run", request(backend, current), None, None)

    assert result.status is TaskFinalStatus.FAILED
    assert result.completion_action is TaskCompletionAction.NONE
    assert backend.connection_info is not None


@pytest.mark.parametrize("gate", ("connection", "generation", "capability", "metadata", "entry"))
def test_backend_gates_before_operation(gate) -> None:
    calls = []
    backend, current = connected_backend(lambda *_args: calls.append(True))
    value = request(backend, current)
    if gate == "connection":
        value = RunAdvancedFlashAppRequest(
            "other", "cpu1", backend.connection_generation, metadata("other"), 0x82400
        )
    elif gate == "generation":
        value = replace(value, expected_connection_generation=ConnectionGeneration(99))
    elif gate == "capability":
        backend._target = replace(
            CPU1_PROFILE, command_set=replace(CPU1_PROFILE.command_set, run=None)
        )
    elif gate == "metadata":
        changed = metadata(entry_point=0x82402)
        backend._runtime_v2_dispatcher.dispatch(
            MetadataReadSucceeded(RuntimeCpuId.CPU1, backend.connection_generation, changed)
        )
    else:
        object.__setattr__(value, "entry_point", 0x82402)

    result = backend.execute("run", value, None, None)

    assert result.status is TaskFinalStatus.FAILED
    assert calls == []


def test_controller_releases_pc_connection_after_exact_run_frame() -> None:
    class Client:
        def __init__(self):
            self.calls = []

        def transact(self, command, payload=(), *, timeout_ms=None):
            self.calls.append((command, tuple(payload)))
            return ()

    class Session:
        def __init__(self):
            self.client = Client()
            self.closed = False

        def close(self):
            self.closed = True

    app = QApplication.instance() or QApplication([])
    backend, current = connected_backend(run_flash_app)
    session = Session()
    backend._session = session
    backend._connection_command_executor.invalidate()
    backend._connection_command_executor = ConnectionCommandExecutor(
        session, backend.connection_generation
    )
    controller = GuiController(backend, backend)
    controller._snapshot = RuntimeSnapshot(
        RuntimeState.CONNECTED,
        connection_info=backend.connection_info,
        active_target_key="cpu1",
    )

    admission = controller.request_task(request(backend, current))
    deadline = monotonic() + 3
    while controller.snapshot.active_task_id is not None and monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)

    assert admission.accepted
    assert controller.snapshot.state is RuntimeState.DISCONNECTED
    assert controller.snapshot.active_task_id is None
    assert controller.snapshot.connection_info is None
    assert session.closed
    assert session.client.calls == [
        (int(Command.RUN), (int(Target.FLASH_APP), *split_u32(0x82400), 0))
    ]
