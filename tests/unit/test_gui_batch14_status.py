from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from PySide6.QtCore import QObject, QEventLoop, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.pages.program_page import ProgramTargetPage
from bootloader_upgrade_tool.gui.runtime_binding import RuntimeViewBinding
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import (
    RequestAdmission,
    RuntimeSnapshot,
    RuntimeState,
)
from bootloader_upgrade_tool.gui.pages.settings_page import SettingsPage
from bootloader_upgrade_tool.gui.status_models import MetadataRefreshRequest
from bootloader_upgrade_tool.gui.widgets.ribbon.operate_ribbon import OperateRibbon
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.targets import CPU1_PROFILE


def test_status_backend_uses_the_active_target_and_only_selected_operation() -> None:
    calls = []

    def metadata(ctx):
        calls.append(ctx)
        return OperationResult(True, "get_metadata_summary", ctx.target.name, "GET_METADATA_SUMMARY", {})

    backend = RuntimeBackend(status_operations={"get_metadata_summary": metadata})
    backend._session = SimpleNamespace(client=SimpleNamespace())
    backend._target = CPU1_PROFILE

    result = backend.execute("task", MetadataRefreshRequest(), None, lambda _event: None)

    assert result.status.name == "SUCCEEDED"
    assert len(calls) == 1 and calls[0].target is CPU1_PROFILE


class _Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskStateChanged = Signal(object)
    taskFinished = Signal(object)
    shutdownReady = Signal()
    forceExitReady = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._snapshot = RuntimeSnapshot()
        self.requests = []

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        self.requests.append(request)
        return RequestAdmission(True, task_id=f"task-{len(self.requests)}")

    def request_cancel(self, _task_id):
        return None

    def respond_task_action(self, _task_id, _action):
        return None


def test_cpu1_auto_refresh_is_one_shot_and_manual_refresh_cancels_pending_timer() -> None:
    app = QApplication.instance() or QApplication([])
    ribbon = OperateRibbon()
    settings = SettingsPage()
    program = ProgramTargetPage("cpu1")
    advanced = AdvancedPage()
    controller = _Controller()
    view = SimpleNamespace(
        operate_ribbon=ribbon,
        settings_page=settings,
        program_cpu1_page=program,
        advanced_page=advanced,
    )
    binding = RuntimeViewBinding(view, controller)
    info = SimpleNamespace(
        connection_id="connection",
        transport_label="SCI",
        endpoint_label="COM3",
        connected_at=datetime.now(timezone.utc),
        target_key="cpu1",
        details={},
    )
    connected = RuntimeSnapshot(
        RuntimeState.CONNECTED,
        connection_info=info,
        active_target_key="cpu1",
    )

    binding.apply_snapshot(connected)
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert len(controller.requests) == 1
    assert controller.requests[0].automatic is True

    binding.apply_snapshot(
        RuntimeSnapshot(
            RuntimeState.BUSY,
            active_task_id="manual",
            connection_info=info,
            active_target_key="cpu1",
        )
    )
    binding.apply_snapshot(connected)
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert len(controller.requests) == 1

    binding.apply_snapshot(RuntimeSnapshot())
    binding.apply_snapshot(connected)
    binding.request_status("get_metadata_summary")
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert len(controller.requests) == 2
    assert controller.requests[1].automatic is False
