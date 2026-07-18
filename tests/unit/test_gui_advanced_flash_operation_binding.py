from dataclasses import replace
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_flash_operation_binding import AdvancedFlashOperationBinding
from bootloader_upgrade_tool.gui.flash_service_binding import FlashServiceBinding
from bootloader_upgrade_tool.gui.advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    AdvancedFlashOperationSnapshot,
    AdvancedFlashOperationType,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
)
from bootloader_upgrade_tool.gui.flash_service_models import (
    DEFAULT_SERVICE_DESCRIPTOR_SYMBOL, FlashServiceResourceState,
    FlashServiceResourceStatus, PreparedFlashServiceSummary,
)
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.pages.settings_page import SettingsPage
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, ErrorDisposition, GuiRuntimeError, RequestAdmission, RuntimeSnapshot, RuntimeState, TaskExecutionResult, TaskFinalStatus
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    FlashImageSummary, ImageParseStatus, RuntimeCpuId, TargetResourceState,
)
from bootloader_upgrade_tool.images import ImageIdentity, PreparedServiceImage
from bootloader_upgrade_tool.operations import OperationCancellationInfo, OperationCompletion, OperationErrorInfo, OperationResult
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
    configuration_revision = 2

    def __init__(self, resource, service_state):
        self.target_resources = {RuntimeCpuId.CPU1: resource}
        self.flash_service_resource_state = service_state
        self.active_target = CPU1_PROFILE
        self.image_revision = 1

    def advanced_flash_selection_revision(self, target):
        return self.image_revision

    def refresh_flash_service_resources(self):
        state = self.flash_service_resource_state
        if state.status is FlashServiceResourceStatus.UNAVAILABLE:
            self.flash_service_resource_state = replace(
                state, revision=state.revision + 1,
                status=FlashServiceResourceStatus.UNVALIDATED,
                error_code=None, error_message=None,
            )
        return self.flash_service_resource_state

    @property
    def service_configuration_revision(self):
        return self.flash_service_resource_state.revision


def caches(tmp_path: Path):
    app_path = tmp_path / "app.txt"
    service_path = tmp_path / "service.txt"
    map_path = tmp_path / "service.map"
    for path in (app_path, service_path, map_path):
        path.write_text(path.name)
    firmware = FirmwareImage(
        source_out_file=str(app_path),
        generated_hex_file=str(app_path),
        entry_point=0x082000,
        blocks=(FirmwareBlock(0x082000, tuple(range(8))),),
        file_checksum="sha",
        format_info={},
    )
    fingerprint = lambda path: SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)
    resource = TargetResourceState(
        RuntimeCpuId.CPU1,
        program_image_path=str(app_path),
        program_image_summary=FlashImageSummary(
            ImageIdentity(0x082000, 8, 0x1234, 0x082008), 0x2
        ),
        program_image_parse_status=ImageParseStatus.READY,
    )
    service = PreparedServiceImage(firmware, 0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF)
    service_summary = PreparedFlashServiceSummary(
        "cpu1", "Provider", str(service_path), str(map_path), DEFAULT_SERVICE_DESCRIPTOR_SYMBOL, 3, 2,
        ImageSourceKind.TXT, fingerprint(service_path), fingerprint(map_path),
        0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF, Hex2000Source.NOT_USED, None,
    )
    state = FlashServiceResourceState(
        3, "Provider", str(service_path), str(map_path),
        FlashServiceResourceStatus.READY, service_summary,
    )
    return resource, state


def connected(target="cpu1"):
    info = ConnectionInfo("connection", "SCI", "COM3", datetime.now(timezone.utc), target)
    return RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=info, active_target_key=target)


def setup_binding(tmp_path):
    QApplication.instance() or QApplication([])
    page = AdvancedPage()
    controller = Controller()
    resource, service_cache = caches(tmp_path)
    backend = Backend(resource, service_cache)
    binding = AdvancedFlashOperationBinding(page, controller, backend)
    return page, controller, backend, binding


def apply(controller, backend, snapshot, profile):
    controller._snapshot = snapshot
    backend.active_target = profile
    controller.runtimeStateChanged.emit(snapshot)


def test_button_state_requires_connected_idle_cpu1_and_current_caches(tmp_path) -> None:
    page, controller, backend, _binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    assert page.erase_button.isEnabled()
    assert page.program_only_button.isEnabled()
    assert page.verify_only_button.isEnabled()

    page.erase_scope_combo.setCurrentText("Custom Sector Mask")
    assert not page.erase_button.isEnabled()
    assert page.program_only_button.isEnabled() and page.verify_only_button.isEnabled()
    page.custom_sector_selector.set_selected_sector_ids(("B", "C"))
    assert page.erase_button.isEnabled()

    apply(controller, backend, connected("cpu2"), CPU2_PROFILE)
    assert not any((page.erase_button.isEnabled(), page.program_only_button.isEnabled(), page.verify_only_button.isEnabled()))
    apply(controller, backend, RuntimeSnapshot(), None)
    assert not page.program_only_button.isEnabled()


def test_missing_ram_check_crc_disables_all_flash_operations(tmp_path) -> None:
    page, controller, backend, _binding = setup_binding(tmp_path)
    profile = replace(
        CPU1_PROFILE,
        command_set=replace(CPU1_PROFILE.command_set, ram_check_crc=None),
    )
    apply(controller, backend, connected(), profile)
    assert not any(
        button.isEnabled()
        for button in (page.erase_button, page.program_only_button, page.verify_only_button)
    )


def test_each_button_submits_one_current_cpu1_request(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    page.erase_button.click()
    apply(controller, backend, connected(), CPU1_PROFILE)
    page.program_only_button.click()
    apply(controller, backend, connected(), CPU1_PROFILE)
    page.verify_only_button.click()
    assert [type(item) for item in controller.requests] == [
        EraseAdvancedFlashRequest,
        ProgramAdvancedFlashRequest,
        VerifyAdvancedFlashRequest,
    ]
    assert all(item.target_key == "cpu1" and item.connection_id == "connection" for item in controller.requests)


def test_owned_result_is_retained_after_disconnect_and_stale_result_is_rejected(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    operation = OperationResult(True, "program_flash_image", CPU1_PROFILE.name, "PROGRAM_END", {})
    payload = AdvancedFlashOperationSnapshot(
        "connection", "cpu1", 1, 2, 3, 2,
        AdvancedFlashOperationType.PROGRAM_ONLY, operation,
        {"operation": "backend_serialized_program", "summary": {}},
    )
    apply(controller, backend, RuntimeSnapshot(), None)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload))
    retained = page.result_output.toPlainText()
    assert "PROGRAM_ONLY" in retained and "backend_serialized_program" in retained

    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.verify_only()
    apply(
        controller, backend,
        RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=ConnectionInfo("new", "SCI", "COM4", datetime.now(timezone.utc), "cpu1"), active_target_key="cpu1"),
        CPU1_PROFILE,
    )
    stale = AdvancedFlashOperationSnapshot(
        "connection", "cpu1", 1, 2, 3, 2,
        AdvancedFlashOperationType.VERIFY_ONLY, operation,
        {"operation": "backend_serialized_verify", "summary": {}},
    )
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=stale))
    assert page.result_output.toPlainText() == retained


def test_owned_advanced_flash_service_change_failure_remains_visible(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    admission = binding.program_only()
    old = backend.flash_service_resource_state
    backend.flash_service_resource_state = replace(
        old, revision=4, status=FlashServiceResourceStatus.STALE, summary=None,
        error_code="SERVICE_RESOURCE_CHANGED", error_message="changed",
    )
    error = GuiRuntimeError(
        "SERVICE_RESOURCE_CHANGED", "changed", "program_only",
        ErrorDisposition.SHOW_ONLY, admission.task_id,
    )
    controller.taskFinished.emit(TaskExecutionResult(
        admission.task_id, TaskFinalStatus.FAILED, "failed", "changed", error=error
    ))
    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["operation"] == "PROGRAM_ONLY"
    assert rendered["error"]["code"] == "SERVICE_RESOURCE_CHANGED"


def test_owned_advanced_flash_unavailable_failure_survives_signal_order(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    settings = SettingsPage()
    FlashServiceBinding(settings, page, controller, backend)
    apply(controller, backend, connected(), CPU1_PROFILE)
    admission = binding.program_only()
    backend.flash_service_resource_state = replace(
        backend.flash_service_resource_state, revision=4,
        status=FlashServiceResourceStatus.UNAVAILABLE, summary=None,
        error_code="IMAGE_FILE_NOT_FOUND", error_message="missing",
    )
    failure_state = backend.flash_service_resource_state
    error = GuiRuntimeError(
        "IMAGE_FILE_NOT_FOUND", "missing", "program_only",
        ErrorDisposition.SHOW_ONLY, admission.task_id,
    )
    result = TaskExecutionResult(
        admission.task_id, TaskFinalStatus.FAILED, "failed", "missing", error=error
    )

    controller.runtimeStateChanged.emit(controller.snapshot)
    assert backend.flash_service_resource_state is failure_state
    controller.taskFinished.emit(result)
    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["operation"] == "PROGRAM_ONLY"
    assert rendered["error"]["code"] == "IMAGE_FILE_NOT_FOUND"

    QApplication.processEvents()
    assert backend.flash_service_resource_state.revision == 5
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.UNVALIDATED
    assert json.loads(page.result_output.toPlainText()) == rendered


def test_foreign_service_change_failure_does_not_render(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    page.result_output.setPlainText("keep")
    backend.flash_service_resource_state = replace(
        backend.flash_service_resource_state, revision=4,
        status=FlashServiceResourceStatus.STALE, summary=None,
        error_code="SERVICE_RESOURCE_CHANGED", error_message="changed",
    )
    error = GuiRuntimeError(
        "SERVICE_RESOURCE_CHANGED", "changed", "program_only", ErrorDisposition.SHOW_ONLY
    )
    controller.taskFinished.emit(TaskExecutionResult(
        "foreign", TaskFinalStatus.FAILED, "failed", "changed", error=error
    ))
    assert page.result_output.toPlainText() == "keep"


def test_later_service_transition_does_not_authorize_old_owned_failure(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    admission = binding.program_only()
    page.result_output.setPlainText("keep")
    backend.flash_service_resource_state = replace(
        backend.flash_service_resource_state, revision=5,
        status=FlashServiceResourceStatus.STALE, summary=None,
        error_code="SERVICE_RESOURCE_CHANGED", error_message="later",
    )
    error = GuiRuntimeError(
        "SERVICE_RESOURCE_CHANGED", "old", "program_only",
        ErrorDisposition.SHOW_ONLY, admission.task_id,
    )
    controller.taskFinished.emit(TaskExecutionResult(
        admission.task_id, TaskFinalStatus.FAILED, "failed", "old", error=error
    ))
    assert page.result_output.toPlainText() == "keep"


@pytest.mark.parametrize(
    "status",
    [
        TaskFinalStatus.SUCCEEDED,
        TaskFinalStatus.FAILED,
        TaskFinalStatus.CANCELLED,
        TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST,
    ],
)
def test_each_final_status_renders_strict_json_from_plain_result_data(tmp_path, status) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    cancellation = OperationCancellationInfo(
        "PROGRAM_END", 8, 8, True, False, False
    )
    if status is TaskFinalStatus.FAILED:
        operation = OperationResult(
            False,
            "program_flash_image",
            CPU1_PROFILE.name,
            "PROGRAM_END",
            {},
            error=OperationErrorInfo("PROGRAM_FAILED", "failed", "PROGRAM_END"),
        )
    elif status is TaskFinalStatus.CANCELLED:
        operation = OperationResult(
            False,
            "program_flash_image",
            CPU1_PROFILE.name,
            "PROGRAM_END",
            {},
            completion=OperationCompletion.CANCELLED,
            cancellation=cancellation,
        )
    elif status is TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST:
        operation = OperationResult(
            True,
            "program_flash_image",
            CPU1_PROFILE.name,
            "PROGRAM_END",
            {},
            completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
            cancellation=cancellation,
        )
    else:
        operation = OperationResult(
            True, "program_flash_image", CPU1_PROFILE.name, "PROGRAM_END", {}
        )
    serialized = {
        "operation": "backend_serialized_program",
        "summary": {"packets": 1},
        "items": [{"word": 1}, (2, 3)],
    }
    payload = AdvancedFlashOperationSnapshot(
        "connection",
        "cpu1",
        1,
        2,
        3,
        2,
        AdvancedFlashOperationType.PROGRAM_ONLY,
        operation,
        serialized,
    )
    error = None
    if status is TaskFinalStatus.FAILED:
        error = GuiRuntimeError(
            "PROGRAM_FAILED", "failed", "PROGRAM_END", ErrorDisposition.SHOW_ONLY
        )
    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            status,
            "summary",
            "message",
            payload=payload,
            error=error,
            cancel_requested=status
            in {
                TaskFinalStatus.CANCELLED,
                TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST,
            },
        )
    )

    rendered_text = page.result_output.toPlainText()
    rendered = json.loads(rendered_text)
    assert rendered["result"] == {
        "operation": "backend_serialized_program",
        "summary": {"packets": 1},
        "items": [{"word": 1}, [2, 3]],
    }
    assert "MappingProxyType" not in rendered_text


def test_binding_source_has_no_operation_or_lower_layer_imports() -> None:
    import bootloader_upgrade_tool.gui.advanced_flash_operation_binding as module

    source = inspect.getsource(module)
    assert "operation_result_to_dict" not in source
    assert ".operation_result_data" not in source
    assert "MappingProxyType" not in source
    assert not any(
        token in source
        for token in ("..operations", "..protocol", "..session", "..transport", "..targets")
    )
