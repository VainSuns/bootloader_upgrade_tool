import json
import os
from dataclasses import replace
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_execution_binding import AdvancedExecutionBinding
from bootloader_upgrade_tool.gui.advanced_execution_models import RunAdvancedFlashAppRequest
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.runtime_backend import ActiveTargetContext
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, RequestAdmission, RuntimeSnapshot, RuntimeState
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration,
    ConnectionRuntimeState,
    DataFreshness,
    MemoryRuntimeState,
    MetadataRuntimeState,
    RuntimeCpuId,
    RuntimeV2Snapshot,
    TargetResourceState,
)
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataStatusSnapshot
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

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        self.requests.append(request)
        return RequestAdmission(True, task_id=f"task-{len(self.requests)}")


class Backend:
    def __init__(self, metadata):
        self.generation = ConnectionGeneration(1)
        self.connection = ConnectionRuntimeState(
            self.generation, "connection", RuntimeCpuId.CPU1, "SCI", "COM3",
            datetime.now(timezone.utc),
        )
        self.profile = CPU1_PROFILE
        self.metadata_state = MetadataRuntimeState(metadata, DataFreshness.FRESH)
        self.listeners = []

    @property
    def runtime_v2_snapshot(self):
        return RuntimeV2Snapshot(
            self.generation,
            self.connection,
            {cpu: TargetResourceState(cpu) for cpu in RuntimeCpuId},
            {cpu: MemoryRuntimeState(cpu) for cpu in RuntimeCpuId},
            self.metadata_state,
        )

    @property
    def active_target_context(self):
        if self.connection is None:
            return None
        cpu = self.connection.cpu_id
        return ActiveTargetContext(
            cpu, cpu.value, self.connection, self.profile, TargetResourceState(cpu)
        )

    def subscribe_runtime_v2(self, listener):
        self.listeners.append(listener)

    def unsubscribe_runtime_v2(self, listener):
        self.listeners.remove(listener)

    def notify(self):
        for listener in tuple(self.listeners):
            listener(object())


def metadata(**changes):
    raw = MetadataSummary(
        1, 1, 1, 0, 0, 3, 1, 0, 0, 0, 0x82400, 0x1234,
        1, 1, 0, 0, 1, 1, 8, 0x377D, 1,
    )
    result = OperationResult(True, "get_metadata_summary", "CPU1", "GET_METADATA_SUMMARY", {})
    value = MetadataStatusSnapshot(
        "connection", "cpu1", result, raw, True, True, True,
        False, False, False, LoadedImageMatch.NO_PREPARED_IMAGE, False,
    )
    return replace(value, **changes)


def setup_binding():
    QApplication.instance() or QApplication([])
    page = AdvancedPage()
    controller = Controller()
    backend = Backend(metadata())
    controller._snapshot = RuntimeSnapshot(
        RuntimeState.CONNECTED,
        connection_info=ConnectionInfo(
            "connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu1"
        ),
        active_target_key="cpu1",
    )
    binding = AdvancedExecutionBinding(page, controller, backend)
    return page, controller, backend, binding


def test_fresh_image_valid_enables_run_without_other_evidence() -> None:
    page, _controller, _backend, _binding = setup_binding()

    assert page.execution_entry_point.text() == "0x00082400"
    assert page.run_flash_app_button.isEnabled()
    assert not page.reset_target_button.isEnabled()


def test_runtime_and_metadata_changes_refresh_gate() -> None:
    page, controller, backend, _binding = setup_binding()
    controller._snapshot = replace(controller.snapshot, state=RuntimeState.BUSY, active_task_id="busy")
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert not page.run_flash_app_button.isEnabled()

    controller._snapshot = replace(controller.snapshot, state=RuntimeState.CONNECTED, active_task_id=None)
    backend.metadata_state = MetadataRuntimeState()
    backend.notify()
    assert page.execution_entry_point.text() == "—"
    assert not page.run_flash_app_button.isEnabled()

    backend.metadata_state = MetadataRuntimeState(metadata(), DataFreshness.FRESH)
    backend.notify()
    assert page.execution_entry_point.text() == "0x00082400"
    assert page.run_flash_app_button.isEnabled()


def test_all_business_and_connection_gates_disable_run() -> None:
    page, controller, backend, binding = setup_binding()
    invalid_states = (
        MetadataRuntimeState(metadata(), DataFreshness.STALE),
        MetadataRuntimeState(replace(metadata(), connection_id="other"), DataFreshness.FRESH),
        MetadataRuntimeState(replace(metadata(), target_key="cpu2"), DataFreshness.FRESH),
        MetadataRuntimeState(replace(metadata(), metadata_valid=False), DataFreshness.FRESH),
        MetadataRuntimeState(replace(metadata(), image_valid=False), DataFreshness.FRESH),
        MetadataRuntimeState(replace(metadata(), entry_point_valid=False), DataFreshness.FRESH),
    )
    for state in invalid_states:
        backend.metadata_state = state
        binding.refresh()
        assert not page.run_flash_app_button.isEnabled()

    backend.metadata_state = MetadataRuntimeState(metadata(), DataFreshness.FRESH)
    backend.profile = replace(CPU1_PROFILE, command_set=replace(CPU1_PROFILE.command_set, run=None))
    binding.refresh()
    assert not page.run_flash_app_button.isEnabled()
    backend.profile = CPU2_PROFILE
    binding.refresh()
    assert not page.run_flash_app_button.isEnabled()
    controller._snapshot = RuntimeSnapshot()
    binding.refresh()
    assert not page.run_flash_app_button.isEnabled()


def test_click_freezes_current_metadata_request() -> None:
    page, controller, backend, _binding = setup_binding()

    page.run_flash_app_button.click()

    assert len(controller.requests) == 1
    request = controller.requests[0]
    assert type(request) is RunAdvancedFlashAppRequest
    assert request.connection_id == "connection"
    assert request.target_key == "cpu1"
    assert request.expected_connection_generation == backend.generation
    assert request.expected_metadata_snapshot == backend.metadata_state.value
    assert request.entry_point == 0x82400
