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
from bootloader_upgrade_tool.gui.runtime_backend import ActiveTargetContext
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, ErrorDisposition, GuiRuntimeError, RequestAdmission, RuntimeSnapshot, RuntimeState, TaskExecutionResult, TaskFinalStatus
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration, ConnectionRuntimeState, EraseScope, FlashImageSummary,
    ImageParseStatus, MemoryRuntimeState, RuntimeCpuId, RuntimeV2Snapshot,
    TargetResourceState,
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
        self.last_admission = None

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        self.requests.append(request)
        self.last_admission = RequestAdmission(True, task_id=f"task-{len(self.requests)}")
        return self.last_admission


class Confirmation:
    def __init__(self, auto_confirm=True):
        self.auto_confirm = auto_confirm
        self.presented = []

    def present(self, plan, request, callback):
        self.presented.append((plan, request, callback))
        if self.auto_confirm:
            callback(plan, request)
        return True


class Backend:
    configuration_revision = 2

    def __init__(self, resource, service_state):
        self.target_resources = {
            RuntimeCpuId.CPU1: resource,
            RuntimeCpuId.CPU2: TargetResourceState(RuntimeCpuId.CPU2),
        }
        self.flash_service_resource_state = service_state
        self.active_target = CPU1_PROFILE
        self.active_context_override = None
        self.image_revision = 1
        self.listeners = []
        self.erase_updates = []

    def subscribe_runtime_v2(self, listener):
        self.listeners.append(listener)

    def unsubscribe_runtime_v2(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)

    def set_erase_configuration(self, target, scope, mask):
        self.erase_updates.append((target, scope, mask))
        cpu = RuntimeCpuId.from_target_key(target)
        self.target_resources[cpu] = replace(
            self.target_resources[cpu], erase_scope=scope, custom_sector_mask=mask
        )
        result = object()
        for listener in tuple(self.listeners):
            listener(result)
        return result

    def advanced_flash_selection_revision(self, target):
        return self.image_revision

    @property
    def runtime_v2_snapshot(self):
        generation = ConnectionGeneration(1)
        connection = ConnectionRuntimeState(
            generation, "connection", RuntimeCpuId.CPU1, "SCI", "COM3",
            datetime.now(timezone.utc),
        )
        return RuntimeV2Snapshot(
            generation, connection, self.target_resources,
            {cpu_id: MemoryRuntimeState(cpu_id) for cpu_id in RuntimeCpuId},
        )

    @property
    def active_target_context(self):
        if self.active_context_override is not None:
            return self.active_context_override
        connection = self.runtime_v2_snapshot.connection
        if connection is None or self.active_target is None:
            return None
        cpu_id = connection.cpu_id
        return ActiveTargetContext(
            cpu_id, cpu_id.value, connection, self.active_target,
            self.target_resources[cpu_id],
        )

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


def connected(target="cpu1", connection_id="connection"):
    info = ConnectionInfo(connection_id, "SCI", "COM3", datetime.now(timezone.utc), target)
    return RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=info, active_target_key=target)


def setup_binding(tmp_path, *, auto_confirm=True):
    QApplication.instance() or QApplication([])
    page = AdvancedPage()
    controller = Controller()
    resource, service_cache = caches(tmp_path)
    backend = Backend(resource, service_cache)
    binding = AdvancedFlashOperationBinding(
        page, controller, backend, Confirmation(auto_confirm)
    )
    return page, controller, backend, binding


def apply(controller, backend, snapshot, profile):
    controller._snapshot = snapshot
    backend.active_target = profile
    controller.runtimeStateChanged.emit(snapshot)


def _set_program_error(backend, *, code="IMAGE_CHANGED", message="The Flash App no longer matches the selected Program image"):
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    backend.target_resources[RuntimeCpuId.CPU1] = replace(
        resource,
        program_image_summary=None,
        program_image_parse_status=ImageParseStatus.ERROR,
        program_image_parse_error=f"Code: {code}\n{message}",
    )


def _failed_result(task_id, *, code="IMAGE_CHANGED", message="The Flash App no longer matches the selected Program image"):
    error = GuiRuntimeError(
        code, message, "program_advanced_flash", ErrorDisposition.SHOW_ONLY, task_id
    )
    return TaskExecutionResult(
        task_id, TaskFinalStatus.FAILED, "failed", message, error=error
    )


def test_button_state_requires_connected_idle_cpu1_and_current_caches(tmp_path) -> None:
    page, controller, backend, _binding = setup_binding(tmp_path)
    assert page.erase_scope_combo.currentIndex() == -1
    assert page.custom_sector_selector.sectors == ()
    assert not page.erase_scope_combo.isEnabled()
    apply(controller, backend, connected(), CPU1_PROFILE)
    assert tuple(option.sector_id for option in page.custom_sector_selector.sectors) == tuple("ABCDEFGHIJKLMN")
    assert page.custom_sector_selector.sectors[0].protected
    assert page.erase_button.isEnabled()
    assert page.program_only_button.isEnabled()
    assert page.verify_only_button.isEnabled()

    page.erase_scope_combo.setCurrentText("Custom Sector Mask")
    assert not page.erase_button.isEnabled()
    assert page.program_only_button.isEnabled() and page.verify_only_button.isEnabled()
    page.custom_sector_selector.set_selected_sector_ids(("B", "C"))
    assert page.erase_button.isEnabled()
    assert backend.erase_updates[-1] == ("cpu1", EraseScope.CUSTOM, 0x0006)

    apply(controller, backend, connected("cpu2"), CPU2_PROFILE)
    assert page.erase_scope_combo.currentIndex() == -1
    assert page.custom_sector_selector.sectors == ()
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
    assert all(
        plan.cpu_id is backend.active_target_context.cpu_id
        for plan, _request, _callback in binding.confirmation_coordinator.presented
    )


@pytest.mark.parametrize(
    "case",
    (
        "busy",
        "shutdown",
        "cleanup",
        "suspect",
        "disconnect_decision",
        "connection_id",
        "target_key",
        "connection_cpu",
        "profile_cpu",
        "resource_cpu",
    ),
)
def test_direct_submission_uses_the_complete_current_context_gate(tmp_path, case) -> None:
    _page, controller, backend, binding = setup_binding(tmp_path)
    snapshot = connected()
    context = backend.active_target_context
    if case == "busy":
        snapshot = replace(snapshot, state=RuntimeState.BUSY, active_task_id="busy")
    elif case == "shutdown":
        snapshot = replace(snapshot, shutdown_requested=True)
    elif case == "cleanup":
        snapshot = RuntimeSnapshot(cleanup_pending=True)
    elif case == "suspect":
        snapshot = replace(snapshot, connection_suspect=True)
    elif case == "disconnect_decision":
        snapshot = replace(
            snapshot,
            state=RuntimeState.BUSY,
            active_task_id="busy",
            connection_suspect=True,
            disconnect_decision_pending=True,
        )
    elif case == "connection_id":
        context = replace(
            context,
            connection=replace(context.connection, connection_id="other"),
        )
    elif case == "target_key":
        context = replace(context, target_key="cpu2")
    elif case == "connection_cpu":
        context = replace(
            context,
            connection=replace(context.connection, cpu_id=RuntimeCpuId.CPU2),
        )
    elif case == "profile_cpu":
        context = replace(context, profile=CPU2_PROFILE)
    elif case == "resource_cpu":
        context = replace(
            context,
            resource=TargetResourceState(RuntimeCpuId.CPU2),
        )
    backend.active_context_override = context
    controller._snapshot = snapshot

    assert binding.erase() is None
    assert binding.program_only() is None
    assert binding.verify_only() is None
    assert controller.requests == []
    assert binding.confirmation_coordinator.presented == []


def test_cpu2_context_stays_unavailable_without_cpu1_fallback(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    cpu1_resource = backend.target_resources[RuntimeCpuId.CPU1]
    cpu2_resource = replace(cpu1_resource, cpu_id=RuntimeCpuId.CPU2)
    backend.target_resources[RuntimeCpuId.CPU2] = cpu2_resource
    connection = replace(
        backend.runtime_v2_snapshot.connection,
        cpu_id=RuntimeCpuId.CPU2,
    )
    backend.active_context_override = ActiveTargetContext(
        RuntimeCpuId.CPU2, "cpu2", connection, CPU2_PROFILE, cpu2_resource
    )
    controller._snapshot = connected("cpu2")
    binding.refresh()

    assert not any(
        button.isEnabled()
        for button in (page.erase_button, page.program_only_button, page.verify_only_button)
    )
    assert binding.erase() is None
    assert binding.program_only() is None
    assert binding.verify_only() is None
    assert controller.requests == []
    assert binding.confirmation_coordinator.presented == []


def test_injected_same_cpu_profile_supplies_layout_and_plan_cpu(tmp_path) -> None:
    _page, controller, backend, binding = setup_binding(tmp_path)
    injected_flash = replace(
        CPU1_PROFILE.memory_map.flash,
        allowed_erase_mask=0x0006,
    )
    profile = replace(
        CPU1_PROFILE,
        name="Injected same-id CPU1",
        memory_map=replace(CPU1_PROFILE.memory_map, flash=injected_flash),
    )
    backend.set_erase_configuration("cpu1", EraseScope.ENTIRE_APPLICATION_REGION, 0)
    apply(controller, backend, connected(), profile)

    context = binding._current_context(AdvancedFlashOperationType.ERASE)
    assert context is not None
    assert context.erase_sector_mask == injected_flash.allowed_erase_mask
    plan = binding.program_only()
    assert plan.cpu_id is backend.active_target_context.cpu_id
    assert controller.requests[-1].target_key == backend.active_target_context.target_key


def test_writes_wait_for_confirmation_and_submit_the_exact_request(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path, auto_confirm=False)
    apply(controller, backend, connected(), CPU1_PROFILE)
    plan = binding.program_only()
    shown_plan, request, callback = binding.confirmation_coordinator.presented[-1]
    assert plan is shown_plan
    assert controller.requests == []
    callback(shown_plan, request)
    assert controller.requests == [request]


def test_confirm_rejects_a_changed_service_summary_without_admission(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path, auto_confirm=False)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    shown_plan, request, callback = binding.confirmation_coordinator.presented[-1]
    state = backend.flash_service_resource_state
    backend.flash_service_resource_state = replace(
        state, summary=replace(state.summary, descriptor_address=0x10002)
    )
    callback(shown_plan, request)
    assert controller.requests == []
    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["code"] == "FLASH_WRITE_PLAN_STALE"


@pytest.mark.parametrize("change", ("revision", "identity"))
def test_confirm_rejects_changed_program_image_inputs(tmp_path, change) -> None:
    page, controller, backend, binding = setup_binding(tmp_path, auto_confirm=False)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    shown_plan, request, callback = binding.confirmation_coordinator.presented[-1]
    if change == "revision":
        backend.image_revision += 1
    else:
        resource = backend.target_resources[RuntimeCpuId.CPU1]
        backend.target_resources[RuntimeCpuId.CPU1] = replace(
            resource,
            program_image_summary=replace(
                resource.program_image_summary,
                identity=replace(resource.program_image_summary.identity, image_crc32=0x5678),
            ),
        )

    callback(shown_plan, request)

    assert controller.requests == []
    assert json.loads(page.result_output.toPlainText())["code"] == "FLASH_WRITE_PLAN_STALE"


def test_erase_requests_use_backend_required_entire_and_custom_masks(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    required = binding._current_context(AdvancedFlashOperationType.ERASE)
    assert required.erase_sector_mask == 0x2
    assert required.erase_sector_mask & CPU1_PROFILE.memory_map.flash.metadata_sector_mask

    backend.set_erase_configuration("cpu1", EraseScope.ENTIRE_APPLICATION_REGION, 0)
    entire = binding._current_context(AdvancedFlashOperationType.ERASE)
    assert entire.erase_sector_mask == CPU1_PROFILE.memory_map.flash.allowed_erase_mask

    backend.set_erase_configuration("cpu1", EraseScope.CUSTOM, 0x6)
    custom = binding._current_context(AdvancedFlashOperationType.ERASE)
    assert custom.erase_sector_mask == 0x6


@pytest.mark.parametrize("mask", (0, 0x1, 1 << 31))
def test_custom_erase_rejects_zero_forbidden_and_outside_masks(tmp_path, mask) -> None:
    _page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    backend.set_erase_configuration("cpu1", EraseScope.CUSTOM, mask)

    assert binding.erase() is None
    assert controller.requests == []
    assert binding.confirmation_coordinator.presented == []


def test_backend_transition_rerenders_without_signal_recursion(tmp_path) -> None:
    page, controller, backend, _binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    backend.erase_updates.clear()
    backend.set_erase_configuration("cpu1", EraseScope.CUSTOM, 0x6)
    assert backend.erase_updates == [("cpu1", EraseScope.CUSTOM, 0x6)]
    assert page.erase_scope_combo.currentText() == "Custom Sector Mask"
    assert page.custom_sector_selector.selected_mask() == 0x6


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


def test_program_only_program_failure_remains_visible(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    admission = controller.last_admission
    _set_program_error(backend)

    controller.runtimeStateChanged.emit(controller.snapshot)
    controller.taskFinished.emit(_failed_result(admission.task_id))

    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["operation"] == "PROGRAM_ONLY"
    assert rendered["status"] == "FAILED"
    assert rendered["error"]["code"] == "IMAGE_CHANGED"


def test_verify_only_program_failure_remains_visible(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.verify_only()
    admission = controller.last_admission
    _set_program_error(backend)

    controller.runtimeStateChanged.emit(controller.snapshot)
    controller.taskFinished.emit(_failed_result(admission.task_id))

    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["operation"] == "VERIFY_ONLY"
    assert rendered["status"] == "FAILED"
    assert rendered["error"]["code"] == "IMAGE_CHANGED"


def test_program_failure_remains_visible_after_clean_disconnect(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    admission = controller.last_admission
    _set_program_error(backend)

    apply(controller, backend, RuntimeSnapshot(), None)
    controller.taskFinished.emit(_failed_result(admission.task_id))

    assert json.loads(page.result_output.toPlainText())["error"]["code"] == "IMAGE_CHANGED"


@pytest.mark.parametrize(("suffix", "visible"), ((".txt", True), (".out", False)))
def test_program_failure_image_tool_revision_rule(tmp_path, suffix, visible) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    source = tmp_path / f"app{suffix}"
    source.write_text("app")
    backend.target_resources[RuntimeCpuId.CPU1] = replace(
        resource, program_image_path=str(source)
    )
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    admission = controller.last_admission
    binding._owned[admission.task_id] = replace(
        binding._owned[admission.task_id], image_tool_configuration_revision=1
    )
    _set_program_error(backend)
    page.result_output.setPlainText("keep")

    controller.taskFinished.emit(_failed_result(admission.task_id))

    assert (page.result_output.toPlainText() != "keep") is visible


@pytest.mark.parametrize(
    "case",
    (
        "foreign_task",
        "revision",
        "path",
        "ready",
        "empty",
        "parsing",
        "error_with_summary",
        "error_code",
        "error_message",
        "later_error",
        "connection",
        "target",
        "service_revision",
    ),
)
def test_stale_program_failure_matrix_does_not_overwrite_shared_result(tmp_path, case) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    admission = controller.last_admission
    original = backend.target_resources[RuntimeCpuId.CPU1]
    _set_program_error(backend)
    result = _failed_result(admission.task_id)

    if case == "foreign_task":
        result = _failed_result("foreign")
    elif case == "revision":
        backend.image_revision += 1
    elif case == "path":
        backend.target_resources[RuntimeCpuId.CPU1] = replace(
            backend.target_resources[RuntimeCpuId.CPU1],
            program_image_path=str(tmp_path / "other.txt"),
        )
    elif case == "ready":
        backend.target_resources[RuntimeCpuId.CPU1] = original
    elif case == "empty":
        backend.target_resources[RuntimeCpuId.CPU1] = TargetResourceState(
            RuntimeCpuId.CPU1, program_image_path=original.program_image_path
        )
    elif case == "parsing":
        backend.target_resources[RuntimeCpuId.CPU1] = replace(
            original,
            program_image_summary=None,
            program_image_parse_status=ImageParseStatus.PARSING,
        )
    elif case == "error_with_summary":
        state = backend.target_resources[RuntimeCpuId.CPU1]
        object.__setattr__(state, "program_image_summary", original.program_image_summary)
    elif case == "error_code":
        result = _failed_result(admission.task_id, code="IMAGE_PARSE_FAILED")
    elif case == "error_message":
        result = _failed_result(admission.task_id, message="different")
    elif case == "later_error":
        _set_program_error(backend, code="IMAGE_PARSE_FAILED", message="later failure")
    elif case == "connection":
        controller._snapshot = connected(connection_id="new")
    elif case == "target":
        controller._snapshot = connected("cpu2")
    elif case == "service_revision":
        backend.flash_service_resource_state = replace(
            backend.flash_service_resource_state,
            revision=4,
            status=FlashServiceResourceStatus.STALE,
            summary=None,
            error_code="SERVICE_RESOURCE_CHANGED",
            error_message="changed",
        )

    page.result_output.setPlainText("keep")
    controller.runtimeStateChanged.emit(controller.snapshot)
    controller.taskFinished.emit(result)
    assert page.result_output.toPlainText() == "keep"


def test_owned_advanced_flash_service_change_failure_remains_visible(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    admission = controller.last_admission
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
    binding.program_only()
    admission = controller.last_admission
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
    binding.program_only()
    admission = controller.last_admission
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
