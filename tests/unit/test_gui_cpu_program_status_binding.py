from dataclasses import asdict, replace
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QEventLoop, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.cpu_program_status_binding import CpuProgramStatusBinding
from bootloader_upgrade_tool.gui.pages.program_page import ProgramTargetPage
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
    ErrorDisposition,
    GuiRuntimeError,
    RequestAdmission,
    RequestRejection,
    RequestRejectionCode,
    RuntimeSnapshot,
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataRefreshRequest, MetadataStatusSnapshot
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.protocol.models import MetadataSummary
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self):
        super().__init__()
        self._snapshot = RuntimeSnapshot()
        self.requests = []
        self.reject = False

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        self.requests.append(request)
        if self.reject:
            return RequestAdmission(False, rejection=RequestRejection(RequestRejectionCode.TASK_ALREADY_ACTIVE, "busy"))
        return RequestAdmission(True, task_id=f"task-{len(self.requests)}")


def connection(connection_id="connection", target="cpu1"):
    return ConnectionInfo(connection_id, "SCI", "COM3", datetime.now(timezone.utc), target)


def snapshot(connection_id="connection", target="cpu1", *, automatic=True):
    cpu_id = 1 if target == "cpu1" else 2
    raw = MetadataSummary(1, 1, 1, 1, 1, 3, 1, 0, 0, 0, 0x082400, 0x12345678, 1, 1, 0, 0, 1, 1, 8, 0x377D, cpu_id)
    operation = OperationResult(True, "get_metadata_summary", target, "GET_METADATA_SUMMARY", asdict(raw))
    return MetadataStatusSnapshot(
        connection_id, target, operation, raw, True, True, True, True, True, True,
        LoadedImageMatch.NO_PREPARED_IMAGE, automatic,
    )


def setup_binding():
    app = QApplication.instance() or QApplication([])
    cpu1, cpu2 = ProgramTargetPage("cpu1"), ProgramTargetPage("cpu2")
    controller = Controller()
    failures = []
    cpu2_status_profile = replace(
        CPU2_PROFILE,
        command_set=replace(
            CPU2_PROFILE.command_set,
            get_metadata_summary=CPU1_PROFILE.command_set.get_metadata_summary,
        ),
    )
    provider = lambda: cpu2_status_profile if controller.snapshot.active_target_key == "cpu2" else CPU1_PROFILE
    binding = CpuProgramStatusBinding(cpu1, cpu2, controller, provider, automatic_failure_callback=lambda *args: failures.append(args))
    return app, cpu1, cpu2, controller, binding, failures


def apply(controller, runtime_snapshot):
    controller._snapshot = runtime_snapshot
    controller.runtimeStateChanged.emit(runtime_snapshot)


def connected(connection_id="connection", target="cpu1", **changes):
    base = RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(connection_id, target), active_target_key=target)
    return replace(base, **changes)


def status_text(page, key):
    return page.status_rows[key].state_widget.text_label.text()


def test_each_new_cpu_connection_submits_exactly_one_automatic_metadata_request() -> None:
    app, _cpu1, _cpu2, controller, _binding, _failures = setup_binding()
    apply(controller, connected("cpu1-a", "cpu1"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    apply(controller, connected("cpu1-a", "cpu1"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    apply(controller, connected("cpu2-a", "cpu2"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert controller.requests == [
        MetadataRefreshRequest("cpu1-a", automatic=True),
        MetadataRefreshRequest("cpu2-a", automatic=True),
    ]

    apply(controller, connected("cpu2-b", "cpu2"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert controller.requests[-1] == MetadataRefreshRequest("cpu2-b", automatic=True)


def test_manual_or_other_task_consumes_pending_refresh_without_retry() -> None:
    app, _cpu1, _cpu2, controller, binding, _failures = setup_binding()
    apply(controller, connected())
    binding.consume_pending_auto_refresh()
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    apply(controller, connected())
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert controller.requests == []

    apply(controller, connected("other"))
    controller.taskStarted.emit(type("Task", (), {"task_id": "manual"})())
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    apply(controller, connected("other"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert controller.requests == []


def test_automatic_admission_rejection_consumes_connection_without_retry() -> None:
    app, _cpu1, _cpu2, controller, _binding, _failures = setup_binding()
    controller.reject = True
    apply(controller, connected("rejected"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    apply(controller, connected("rejected"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert controller.requests == [MetadataRefreshRequest("rejected", automatic=True)]


def test_dirty_or_unsupported_connection_does_not_submit() -> None:
    app, _cpu1, _cpu2, controller, binding, _failures = setup_binding()
    apply(controller, connected("suspect", connection_suspect=True))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert controller.requests == []
    binding.target_provider = lambda: replace(CPU1_PROFILE, command_set=replace(CPU1_PROFILE.command_set, get_metadata_summary=None))
    apply(controller, connected("unsupported"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert controller.requests == []


def test_cpu1_and_cpu2_metadata_route_only_to_the_current_page() -> None:
    _app, cpu1, cpu2, controller, _binding, _failures = setup_binding()
    apply(controller, connected("one", "cpu1"))
    controller.taskFinished.emit(TaskExecutionResult("manual", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot("one", "cpu1", automatic=False)))
    assert status_text(cpu1, "metadata_valid") == "Valid"
    assert status_text(cpu2, "metadata_valid") == "Unknown"

    apply(controller, connected("two", "cpu2"))
    controller.taskFinished.emit(TaskExecutionResult("manual2", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot("two", "cpu2", automatic=False)))
    assert status_text(cpu1, "metadata_valid") == "Unknown"
    assert status_text(cpu2, "metadata_valid") == "Valid"


def test_stale_or_inactive_metadata_changes_neither_page() -> None:
    _app, cpu1, cpu2, controller, _binding, _failures = setup_binding()
    apply(controller, connected("new", "cpu1"))
    controller.taskFinished.emit(TaskExecutionResult("old", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot("old", "cpu1")))
    controller.taskFinished.emit(TaskExecutionResult("inactive", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot("new", "cpu2")))
    assert status_text(cpu1, "metadata_valid") == "Unknown"
    assert status_text(cpu2, "metadata_valid") == "Unknown"


def test_automatic_failure_clears_only_current_cpu_and_notifies_advanced() -> None:
    app, cpu1, cpu2, controller, binding, failures = setup_binding()
    apply(controller, connected("one", "cpu1"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    controller.taskFinished.emit(TaskExecutionResult("seed", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot("one", "cpu1")))
    error = GuiRuntimeError("DSP_STATUS_ERROR", "failed", "GET_METADATA_SUMMARY", ErrorDisposition.SHOW_ONLY, "task-1")
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.FAILED, "failed", "failed", error=error))
    assert status_text(cpu1, "metadata_valid") == "Unknown"
    assert status_text(cpu2, "metadata_valid") == "Unknown"
    assert failures == [("one", "cpu1")]
    apply(controller, connected("one", "cpu1"))
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert len(controller.requests) == 1


def test_disconnect_and_shutdown_clear_both_pages_without_touching_image_rows() -> None:
    _app, cpu1, cpu2, controller, _binding, _failures = setup_binding()
    cpu1.image_path_row.path_edit.setText("D:/app.txt")
    apply(controller, connected("one", "cpu1"))
    controller.taskFinished.emit(TaskExecutionResult("seed", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot("one", "cpu1")))
    apply(controller, replace(connected("one", "cpu1"), state=RuntimeState.DISCONNECTING))
    assert status_text(cpu1, "metadata_valid") == status_text(cpu2, "metadata_valid") == "Unknown"
    assert cpu1.image_path_row.path_edit.text() == "D:/app.txt"

    controller.taskFinished.emit(TaskExecutionResult("seed2", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot("one", "cpu1")))
    apply(controller, replace(connected("one", "cpu1"), shutdown_requested=True))
    assert status_text(cpu1, "metadata_valid") == status_text(cpu2, "metadata_valid") == "Unknown"
