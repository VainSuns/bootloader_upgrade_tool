from dataclasses import asdict, replace
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_metadata_binding import AdvancedMetadataOperationBinding
from bootloader_upgrade_tool.gui.flash_service_binding import FlashServiceBinding
from bootloader_upgrade_tool.gui.advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
    AdvancedMetadataOperationType,
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from bootloader_upgrade_tool.gui.flash_service_models import (
    DEFAULT_SERVICE_DESCRIPTOR_SYMBOL, FlashServiceResourceState,
    FlashServiceResourceStatus, PreparedFlashServiceSummary,
)
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.pages.settings_page import SettingsPage
from bootloader_upgrade_tool.gui.runtime_backend import ActiveTargetContext
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
    ErrorDisposition,
    GuiRuntimeError,
    GuiTaskWarning,
    RequestAdmission,
    RuntimeSnapshot,
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration, ConnectionRuntimeState, DataFreshness, FlashImageSummary,
    ImageParseStatus, MemoryRuntimeState, MetadataRuntimeState, RuntimeCpuId, RuntimeV2Snapshot,
    TargetResourceState, VerifyEvidence,
)
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataStatusSnapshot
from bootloader_upgrade_tool.images import ImageIdentity, PreparedFlashImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import OperationErrorInfo, OperationResult, operation_result_to_dict
from bootloader_upgrade_tool.protocol.models import MetadataSummary
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


_DEFAULT_CONTEXT = object()


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

    def __init__(self, resource, service_state, evidence, metadata):
        self.target_resources = {
            RuntimeCpuId.CPU1: replace(resource, verify_evidence=evidence),
            RuntimeCpuId.CPU2: TargetResourceState(RuntimeCpuId.CPU2),
        }
        self.flash_service_resource_state = service_state
        self.metadata_status_snapshot = metadata
        self.active_target = CPU1_PROFILE
        self.image_revision = 1
        self.runtime_connection = True
        self.runtime_cpu_id = RuntimeCpuId.CPU1
        self.context_override = _DEFAULT_CONTEXT

    @property
    def connection_generation(self):
        return ConnectionGeneration(1)

    @property
    def runtime_v2_snapshot(self):
        generation = self.connection_generation
        connection = ConnectionRuntimeState(
            generation, "connection", self.runtime_cpu_id, "SCI", "COM3",
            datetime.now(timezone.utc),
        ) if self.runtime_connection else None
        return RuntimeV2Snapshot(
            generation,
            connection,
            self.target_resources,
            {cpu_id: MemoryRuntimeState(cpu_id) for cpu_id in RuntimeCpuId},
            MetadataRuntimeState(self.metadata_status_snapshot, DataFreshness.FRESH),
        )

    @property
    def active_target_context(self):
        if self.context_override is not _DEFAULT_CONTEXT:
            return self.context_override
        connection = self.runtime_v2_snapshot.connection
        if connection is None or self.active_target is None:
            return None
        cpu_id = connection.cpu_id
        return ActiveTargetContext(
            cpu_id, cpu_id.value, connection, self.active_target,
            self.target_resources[cpu_id],
        )

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


def _fingerprint(path: Path):
    return SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)


def _setup(tmp_path: Path, *, auto_confirm=True):
    QApplication.instance() or QApplication([])
    page = AdvancedPage()
    controller = Controller()
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
    identity = ImageIdentity(0x082000, 8, 0x1234, 0x082008)
    resource = TargetResourceState(
        RuntimeCpuId.CPU1,
        program_image_path=str(app_path),
        program_image_summary=FlashImageSummary(identity, 0x2),
        program_image_parse_status=ImageParseStatus.READY,
    )
    service = PreparedServiceImage(firmware, 0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF)
    service_summary = PreparedFlashServiceSummary(
        "cpu1", "Provider", str(service_path), str(map_path), DEFAULT_SERVICE_DESCRIPTOR_SYMBOL, 3, 2,
        ImageSourceKind.TXT, _fingerprint(service_path), _fingerprint(map_path),
        0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF, Hex2000Source.NOT_USED, None,
    )
    service_state = FlashServiceResourceState(
        3, "Provider", str(service_path), str(map_path),
        FlashServiceResourceStatus.READY, service_summary,
    )
    raw = MetadataSummary(
        1, 1, 1, 1, 0, 3, 1, 0, 0, 0, 0x082000, 0x1234,
        1, 1, 0, 0, 1, 1, 8, 0x377D, 1,
    )
    operation = OperationResult(True, "get_metadata_summary", "cpu1", "GET_METADATA_SUMMARY", asdict(raw))
    metadata = MetadataStatusSnapshot(
        "connection", "cpu1", operation, raw, True, True, True, True, False,
        False, LoadedImageMatch.MATCH, False,
    )
    evidence = VerifyEvidence(
        RuntimeCpuId.CPU1, ConnectionGeneration(1), identity, "verify"
    )
    backend = Backend(resource, service_state, evidence, metadata)
    applied = []
    cleared = []
    binding = AdvancedMetadataOperationBinding(
        page, controller, backend, Confirmation(auto_confirm),
        apply_metadata_snapshot=lambda snapshot: applied.append(snapshot) or True,
        clear_metadata=lambda: cleared.append(True),
    )
    return page, controller, backend, binding, resource.program_image_summary, operation, applied, cleared


def _connected(connection_id="connection", target="cpu1"):
    return RuntimeSnapshot(
        RuntimeState.CONNECTED,
        connection_info=ConnectionInfo(
            connection_id, "SCI", "COM3", datetime.now(timezone.utc), target
        ),
        active_target_key=target,
    )


def _apply(controller, backend, snapshot, profile):
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


def _clear_evidence(backend):
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    backend.target_resources[RuntimeCpuId.CPU1] = replace(resource, verify_evidence=None)


def _failed_result(task_id, *, code="IMAGE_CHANGED", message="The Flash App no longer matches the selected Program image"):
    error = GuiRuntimeError(
        code, message, "write_metadata", ErrorDisposition.SHOW_ONLY, task_id
    )
    return TaskExecutionResult(
        task_id, TaskFinalStatus.FAILED, "failed", message, error=error
    )


def test_button_state_uses_current_cpu1_evidence_and_metadata(tmp_path) -> None:
    page, controller, backend, _binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    assert page.write_image_valid_button.isEnabled()
    assert page.write_boot_attempt_button.isEnabled()
    assert page.write_app_confirmed_button.isEnabled()

    _clear_evidence(backend)
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert not page.write_image_valid_button.isEnabled()
    assert page.write_boot_attempt_button.isEnabled()
    backend.metadata_status_snapshot = replace(backend.metadata_status_snapshot, boot_attempt_present=False)
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert not page.write_app_confirmed_button.isEnabled()

    _apply(controller, backend, _connected(target="cpu2"), CPU2_PROFILE)
    assert not any((
        page.write_image_valid_button.isEnabled(),
        page.write_boot_attempt_button.isEnabled(),
        page.write_app_confirmed_button.isEnabled(),
    ))


@pytest.mark.parametrize("cpu_id", RuntimeCpuId)
def test_program_image_edit_change_refreshes_once(tmp_path, cpu_id) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    calls = []
    refresh = binding.refresh
    binding.refresh = lambda: calls.append(None) or refresh()

    getattr(page, f"{cpu_id.value}_flash_image_edit").setText(cpu_id.name)

    assert calls == [None]
    assert page.write_image_valid_button.isEnabled()
    assert page.write_boot_attempt_button.isEnabled()
    assert page.write_app_confirmed_button.isEnabled()


def test_equivalent_cpu1_profile_instance_drives_binding(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    profile = replace(CPU1_PROFILE)
    assert profile is not CPU1_PROFILE

    _apply(controller, backend, _connected(), profile)

    assert page.write_image_valid_button.isEnabled()
    plan = binding.write_image_valid()
    assert plan.cpu_id is RuntimeCpuId.CPU1
    assert controller.requests[-1].target_key == RuntimeCpuId.CPU1.value


def test_real_cpu2_context_is_unavailable_without_cpu1_fallback(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    backend.runtime_cpu_id = RuntimeCpuId.CPU2
    _apply(controller, backend, _connected(target="cpu2"), CPU2_PROFILE)

    assert not any((
        page.write_image_valid_button.isEnabled(),
        page.write_boot_attempt_button.isEnabled(),
        page.write_app_confirmed_button.isEnabled(),
    ))
    assert [
        binding.write_image_valid(),
        binding.write_boot_attempt(),
        binding.write_app_confirmed(),
    ] == [None, None, None]
    assert binding.confirmation_coordinator.presented == []
    assert controller.requests == []


@pytest.mark.parametrize(
    "case",
    ("context_cpu", "profile", "resource", "connection_cpu", "connection_id", "target"),
)
def test_context_identity_mismatch_rejects_all_operations(tmp_path, case) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    context = backend.active_target_context
    if case == "context_cpu":
        context = replace(context, cpu_id=RuntimeCpuId.CPU2)
    elif case == "profile":
        context = replace(context, profile=CPU2_PROFILE)
    elif case == "resource":
        context = replace(context, resource=TargetResourceState(RuntimeCpuId.CPU2))
    elif case == "connection_cpu":
        context = replace(
            context, connection=replace(context.connection, cpu_id=RuntimeCpuId.CPU2)
        )
    elif case == "connection_id":
        context = replace(context, connection=replace(context.connection, connection_id="other"))
    else:
        context = replace(context, target_key=RuntimeCpuId.CPU2.value)
    backend.context_override = context

    binding.refresh()

    assert not any((
        page.write_image_valid_button.isEnabled(),
        page.write_boot_attempt_button.isEnabled(),
        page.write_app_confirmed_button.isEnabled(),
    ))
    assert binding.write_image_valid() is None
    assert binding.write_boot_attempt() is None
    assert binding.write_app_confirmed() is None
    assert binding.confirmation_coordinator.presented == []
    assert controller.requests == []


@pytest.mark.parametrize("program_state", ("missing", "different"))
def test_metadata_only_buttons_do_not_depend_on_program_image(tmp_path, program_state) -> None:
    page, controller, backend, _binding, *_ = _setup(tmp_path)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    if program_state == "missing":
        resource = replace(
            resource, program_image_path="", program_image_summary=None,
            program_image_parse_status=ImageParseStatus.EMPTY, verify_evidence=None,
        )
    else:
        resource = replace(
            resource,
            program_image_summary=FlashImageSummary(
                ImageIdentity(0x084000, 16, 0x9999, 0x084010), 0x4
            ),
            verify_evidence=None,
        )
    backend.target_resources[RuntimeCpuId.CPU1] = resource
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    assert not page.write_image_valid_button.isEnabled()
    assert page.write_boot_attempt_button.isEnabled()
    assert page.write_app_confirmed_button.isEnabled()


@pytest.mark.parametrize(
    ("count", "confirmed", "boot_enabled", "confirm_enabled"),
    ((0, False, True, False), (3, False, False, True), (1, True, False, False)),
)
def test_metadata_only_admission_uses_frozen_metadata_rules(
    tmp_path, count, confirmed, boot_enabled, confirm_enabled
) -> None:
    page, controller, backend, _binding, *_ = _setup(tmp_path)
    snapshot = backend.metadata_status_snapshot
    backend.metadata_status_snapshot = replace(
        snapshot,
        raw_metadata=replace(snapshot.raw_metadata, boot_attempt_count=count, app_confirmed=int(confirmed)),
        boot_attempt_present=count > 0,
        app_confirmed=confirmed,
    )
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    assert page.write_boot_attempt_button.isEnabled() is boot_enabled
    assert page.write_app_confirmed_button.isEnabled() is confirm_enabled


def test_missing_common_capability_disables_all(tmp_path) -> None:
    page, controller, backend, _binding, *_ = _setup(tmp_path)
    profile = replace(
        CPU1_PROFILE,
        command_set=replace(CPU1_PROFILE.command_set, metadata_append_record=None),
    )
    _apply(controller, backend, _connected(), profile)
    assert not any((
        page.write_image_valid_button.isEnabled(),
        page.write_boot_attempt_button.isEnabled(),
        page.write_app_confirmed_button.isEnabled(),
    ))


def test_each_button_submits_exactly_one_typed_request_and_clears_after_admission(tmp_path) -> None:
    page, controller, backend, _binding, *_rest, cleared = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    for button in (
        page.write_image_valid_button,
        page.write_boot_attempt_button,
        page.write_app_confirmed_button,
    ):
        button.click()
        _apply(controller, backend, _connected(), CPU1_PROFILE)
    assert [type(request) for request in controller.requests] == [
        WriteAdvancedImageValidRequest,
        WriteAdvancedBootAttemptRequest,
        WriteAdvancedAppConfirmedRequest,
    ]
    assert controller.requests[0].expected_verify_evidence.operation_id == "verify"
    assert cleared == []


def test_metadata_write_waits_for_confirmation_and_submits_exact_request(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path, auto_confirm=False)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    plan = binding.write_boot_attempt()
    shown_plan, request, callback = binding.confirmation_coordinator.presented[-1]
    assert plan is shown_plan and controller.requests == []
    callback(shown_plan, request)
    assert controller.requests == [request]


def test_each_boot_attempt_invocation_gets_a_new_plan(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path, auto_confirm=False)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    first = binding.write_boot_attempt()
    second = binding.write_boot_attempt()
    assert first.plan_id != second.plan_id


def test_confirm_rejects_changed_metadata_snapshot(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path, auto_confirm=False)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_boot_attempt()
    shown_plan, request, callback = binding.confirmation_coordinator.presented[-1]
    backend.metadata_status_snapshot = replace(
        backend.metadata_status_snapshot,
        raw_metadata=replace(backend.metadata_status_snapshot.raw_metadata, boot_attempt_count=2),
    )
    callback(shown_plan, request)
    assert controller.requests == []
    assert json.loads(page.result_output.toPlainText())["code"] == "FLASH_WRITE_PLAN_STALE"


@pytest.mark.parametrize("case", ("stale_generation", "wrong_cpu", "identity", "no_connection"))
def test_image_valid_requires_exact_current_cpu1_evidence(tmp_path, case) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    evidence = resource.verify_evidence
    if case == "stale_generation":
        evidence = replace(evidence, connection_generation=ConnectionGeneration(2))
        backend.target_resources[RuntimeCpuId.CPU1] = replace(resource, verify_evidence=evidence)
    elif case == "wrong_cpu":
        object.__setattr__(evidence, "cpu_id", RuntimeCpuId.CPU2)
    elif case == "identity":
        evidence = replace(
            evidence,
            image_identity=replace(evidence.image_identity, image_crc32=0x9999),
        )
        backend.target_resources[RuntimeCpuId.CPU1] = replace(resource, verify_evidence=evidence)
    else:
        backend.runtime_connection = False
    binding.refresh()
    assert not page.write_image_valid_button.isEnabled()


def test_image_valid_request_captures_exact_current_evidence(tmp_path) -> None:
    _page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    evidence = backend.target_resources[RuntimeCpuId.CPU1].verify_evidence
    binding.write_image_valid()
    admission = controller.last_admission
    assert admission.accepted
    assert controller.requests[-1].expected_verify_evidence is evidence
    assert binding._owned[admission.task_id].expected_verify_evidence is evidence


def test_image_valid_uses_current_context_program_state(tmp_path) -> None:
    _page, controller, backend, binding, *_ = _setup(tmp_path, auto_confirm=False)
    identity = ImageIdentity(0x084000, 16, 0xABCD, 0x084010)
    evidence = VerifyEvidence(
        RuntimeCpuId.CPU1, backend.connection_generation, identity, "current-verify"
    )
    backend.image_revision = 7
    backend.target_resources[RuntimeCpuId.CPU1] = replace(
        backend.target_resources[RuntimeCpuId.CPU1],
        program_image_summary=FlashImageSummary(identity, 0x24),
        verify_evidence=evidence,
    )
    _apply(controller, backend, _connected(), replace(CPU1_PROFILE))

    plan = binding.write_image_valid()
    request = binding.confirmation_coordinator.presented[-1][1]

    assert plan.cpu_id is RuntimeCpuId.CPU1
    assert plan.connection_generation == backend.connection_generation
    assert plan.image_selection_revision == 7
    assert plan.image_identity == identity
    assert plan.effective_sector_mask == 0x24
    assert plan.verify_evidence is evidence
    assert request.expected_image_identity == identity
    assert request.expected_effective_sector_mask == 0x24
    assert request.expected_verify_evidence is evidence


def test_metadata_snapshot_must_match_current_target(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    backend.metadata_status_snapshot = replace(
        backend.metadata_status_snapshot, target_key=RuntimeCpuId.CPU2.value
    )
    _apply(controller, backend, _connected(), CPU1_PROFILE)

    assert not page.write_boot_attempt_button.isEnabled()
    assert not page.write_app_confirmed_button.isEnabled()
    assert binding.write_boot_attempt() is None
    assert binding.write_app_confirmed() is None
    assert binding.confirmation_coordinator.presented == []
    assert controller.requests == []


def test_current_owned_result_renders_strict_json_and_applies_readback(tmp_path) -> None:
    page, controller, backend, binding, image_summary, operation, applied, _cleared = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_boot_attempt()
    admission = controller.last_admission
    metadata = backend.metadata_status_snapshot
    primary = OperationResult(
        True, "append_boot_attempt", "cpu1", "METADATA",
        {"written": True, "already_exists": False, "reason": None},
    )
    payload = AdvancedMetadataOperationSnapshot(
        "connection", "cpu1", None, None, 3, 2,
        AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, None,
        image_summary.identity.entry_point, image_summary.identity.image_size_words,
        image_summary.identity.image_crc32, None,
        primary, operation_result_to_dict(primary),
        operation, operation_result_to_dict(operation), metadata,
    )
    controller.taskFinished.emit(
        TaskExecutionResult(admission.task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload)
    )
    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["operation"] == "WRITE_BOOT_ATTEMPT"
    assert rendered["written"] is True
    assert rendered["metadata_summary"]["boot_attempt_count"] == 1
    assert applied == []


def test_owned_metadata_result_remains_visible_after_clean_disconnect(tmp_path) -> None:
    page, controller, backend, binding, image_summary, operation, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_boot_attempt()
    admission = controller.last_admission
    primary = OperationResult(True, "append_boot_attempt", "cpu1", "METADATA", {})
    payload = AdvancedMetadataOperationSnapshot(
        "connection", "cpu1", None, None, 3, 2,
        AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, None,
        image_summary.identity.entry_point, image_summary.identity.image_size_words,
        image_summary.identity.image_crc32, None,
        primary, operation_result_to_dict(primary),
        operation, operation_result_to_dict(operation), backend.metadata_status_snapshot,
    )
    backend.runtime_connection = False
    controller._snapshot = RuntimeSnapshot(RuntimeState.DISCONNECTED)

    controller.taskFinished.emit(
        TaskExecutionResult(
            admission.task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload
        )
    )

    assert json.loads(page.result_output.toPlainText())["task_id"] == admission.task_id


def test_metadata_refresh_failure_shared_result_keeps_primary_and_warning(tmp_path) -> None:
    page, controller, backend, binding, image_summary, _operation, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_boot_attempt()
    admission = controller.last_admission
    primary = OperationResult(
        True, "append_boot_attempt", "cpu1", "METADATA_APPEND",
        {"written": True, "already_exists": False, "reason": None},
    )
    refresh = OperationResult(
        False, "get_metadata_summary", "cpu1", "GET_METADATA_SUMMARY", {},
        error=OperationErrorInfo("READ_FAILED", "lost", "GET_METADATA_SUMMARY"),
    )
    payload = AdvancedMetadataOperationSnapshot(
        "connection", "cpu1", None, None, 3, 2,
        AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, None,
        image_summary.identity.entry_point, image_summary.identity.image_size_words,
        image_summary.identity.image_crc32, None,
        primary, operation_result_to_dict(primary),
        refresh, operation_result_to_dict(refresh), None,
    )
    warning = GuiTaskWarning(
        "METADATA_REFRESH_FAILED", "refresh failed", "GET_METADATA_SUMMARY",
        {
            "primary_operation": primary.operation,
            "refresh_error_code": "READ_FAILED",
            "metadata_freshness": "stale",
            "primary_retry_performed": False,
        },
    )
    controller.taskFinished.emit(TaskExecutionResult(
        admission.task_id, TaskFinalStatus.SUCCEEDED, "ok", "refresh failed",
        step_results=(primary, refresh), payload=payload, warning=warning,
    ))
    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["primary_result"]["operation"] == "append_boot_attempt"
    assert rendered["readback_result"]["error"]["code"] == "READ_FAILED"
    assert rendered["metadata_summary"] is None
    assert rendered["warning"]["code"] == "METADATA_REFRESH_FAILED"
    assert rendered["warning"]["details"]["metadata_freshness"] == "stale"
    assert rendered["warning"]["details"]["primary_retry_performed"] is False


def test_stale_result_does_not_overwrite_shared_result(tmp_path) -> None:
    page, controller, backend, binding, image_summary, _operation, applied, _cleared = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_boot_attempt()
    admission = controller.last_admission
    page.result_output.setPlainText("keep")
    _apply(controller, backend, _connected("new"), CPU1_PROFILE)
    primary = OperationResult(True, "append", "cpu1", "METADATA", {})
    payload = AdvancedMetadataOperationSnapshot(
        "connection", "cpu1", None, None, 3, 2,
        AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, None,
        image_summary.identity.entry_point, image_summary.identity.image_size_words,
        image_summary.identity.image_crc32, None,
        primary, operation_result_to_dict(primary),
    )
    controller.taskFinished.emit(
        TaskExecutionResult(admission.task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload)
    )
    assert page.result_output.toPlainText() == "keep"
    assert applied == []


def test_boot_attempt_ignores_program_failure(tmp_path) -> None:
    page, controller, backend, binding, *_rest, applied, _cleared = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_boot_attempt()
    admission = controller.last_admission
    _set_program_error(backend)

    controller.runtimeStateChanged.emit(controller.snapshot)
    controller.taskFinished.emit(_failed_result(admission.task_id))

    assert not page.result_output.toPlainText().startswith("{")
    assert applied == []


def test_image_valid_evidence_cleared_program_failure_remains_visible(tmp_path) -> None:
    page, controller, backend, binding, *_rest, applied, _cleared = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_image_valid()
    admission = controller.last_admission
    _set_program_error(backend)
    _clear_evidence(backend)

    controller.runtimeStateChanged.emit(controller.snapshot)
    controller.taskFinished.emit(_failed_result(admission.task_id))

    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["operation"] == "WRITE_IMAGE_VALID"
    assert rendered["status"] == "FAILED"
    assert rendered["error"]["code"] == "IMAGE_CHANGED"
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is None
    assert applied == []


@pytest.mark.parametrize(
    "case",
    (
        "foreign_task",
        "revision",
        "path",
        "status",
        "error",
        "connection",
        "target",
        "service_revision",
        "missing_credential_foreign",
    ),
)
def test_stale_metadata_program_failure_matrix_does_not_overwrite_shared_result(tmp_path, case) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    operation = (
        AdvancedMetadataOperationType.WRITE_IMAGE_VALID
        if case == "missing_credential_foreign"
        else AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT
    )
    binding._submit_operation(operation)
    admission = controller.last_admission
    _set_program_error(backend)
    result = _failed_result(admission.task_id)

    if case in {"foreign_task", "missing_credential_foreign"}:
        result = _failed_result("foreign")
    if case == "missing_credential_foreign":
        _clear_evidence(backend)
    elif case == "revision":
        backend.image_revision += 1
    elif case == "path":
        backend.target_resources[RuntimeCpuId.CPU1] = replace(
            backend.target_resources[RuntimeCpuId.CPU1],
            program_image_path=str(tmp_path / "other.txt"),
        )
    elif case == "status":
        backend.target_resources[RuntimeCpuId.CPU1] = TargetResourceState(
            RuntimeCpuId.CPU1,
            program_image_path=str(tmp_path / "app.txt"),
        )
    elif case == "error":
        result = _failed_result(admission.task_id, message="different")
    elif case == "connection":
        controller._snapshot = _connected("new")
    elif case == "target":
        controller._snapshot = _connected(target="cpu2")
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


def test_owned_advanced_metadata_service_change_failure_remains_visible(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_boot_attempt()
    admission = controller.last_admission
    backend.flash_service_resource_state = replace(
        backend.flash_service_resource_state, revision=4,
        status=FlashServiceResourceStatus.STALE, summary=None,
        error_code="SERVICE_RESOURCE_CHANGED", error_message="changed",
    )
    error = GuiRuntimeError(
        "SERVICE_RESOURCE_CHANGED", "changed", "write_boot_attempt",
        ErrorDisposition.SHOW_ONLY, admission.task_id,
    )
    controller.taskFinished.emit(TaskExecutionResult(
        admission.task_id, TaskFinalStatus.FAILED, "failed", "changed", error=error
    ))
    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["operation"] == "WRITE_BOOT_ATTEMPT"
    assert rendered["error"]["code"] == "SERVICE_RESOURCE_CHANGED"


def test_owned_advanced_metadata_unavailable_failure_survives_signal_order(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    settings = SettingsPage()
    FlashServiceBinding(settings, page, controller, backend)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_boot_attempt()
    admission = controller.last_admission
    backend.flash_service_resource_state = replace(
        backend.flash_service_resource_state, revision=4,
        status=FlashServiceResourceStatus.UNAVAILABLE, summary=None,
        error_code="IMAGE_FILE_NOT_FOUND", error_message="missing",
    )
    failure_state = backend.flash_service_resource_state
    error = GuiRuntimeError(
        "IMAGE_FILE_NOT_FOUND", "missing", "write_boot_attempt",
        ErrorDisposition.SHOW_ONLY, admission.task_id,
    )
    result = TaskExecutionResult(
        admission.task_id, TaskFinalStatus.FAILED, "failed", "missing", error=error
    )

    controller.runtimeStateChanged.emit(controller.snapshot)
    assert backend.flash_service_resource_state is failure_state
    controller.taskFinished.emit(result)
    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["operation"] == "WRITE_BOOT_ATTEMPT"
    assert rendered["error"]["code"] == "IMAGE_FILE_NOT_FOUND"

    QApplication.processEvents()
    assert backend.flash_service_resource_state.revision == 5
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.UNVALIDATED
    assert json.loads(page.result_output.toPlainText()) == rendered


def test_foreign_metadata_service_change_failure_does_not_render(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    page.result_output.setPlainText("keep")
    backend.flash_service_resource_state = replace(
        backend.flash_service_resource_state, revision=4,
        status=FlashServiceResourceStatus.STALE, summary=None,
        error_code="SERVICE_RESOURCE_CHANGED", error_message="changed",
    )
    error = GuiRuntimeError(
        "SERVICE_RESOURCE_CHANGED", "changed", "metadata", ErrorDisposition.SHOW_ONLY
    )
    controller.taskFinished.emit(TaskExecutionResult(
        "foreign", TaskFinalStatus.FAILED, "failed", "changed", error=error
    ))
    assert page.result_output.toPlainText() == "keep"


@pytest.mark.parametrize(
    "operation,code",
    [
        (AdvancedMetadataOperationType.WRITE_IMAGE_VALID, "VERIFY_EVIDENCE_REQUIRED"),
        (AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, "SERVICE_CHANGED"),
        (AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, "STALE_CONNECTION"),
        (AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, "UNSUPPORTED_OPERATION"),
    ],
)
def test_owned_no_payload_failure_retains_submitted_context(tmp_path, operation, code) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding._submit_operation(operation)
    admission = controller.last_admission
    if operation is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
        _clear_evidence(backend)
    error = GuiRuntimeError(
        code,
        "pre-validation failed",
        "metadata",
        ErrorDisposition.SHOW_ONLY,
        admission.task_id,
        True,
        False,
        {"recovery": {"steps": ["prepare", "retry"], "allowed": True}},
    )
    binding._task_finished(
        TaskExecutionResult(
            admission.task_id,
            TaskFinalStatus.FAILED,
            "Metadata operation failed",
            error.message,
            error=error,
        )
    )
    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["task_id"] == admission.task_id
    assert rendered["operation"] == operation.name
    assert rendered["connection_id"] == "connection"
    assert rendered["target_key"] == "cpu1"
    assert [rendered[name] for name in (
        "image_selection_revision",
        "image_tool_configuration_revision",
        "service_configuration_revision",
        "service_tool_configuration_revision",
    )] == ([1, 2, 3, 2] if operation is AdvancedMetadataOperationType.WRITE_IMAGE_VALID else [None, None, 3, 2])
    assert rendered["prepared_image"] == {
        "entry_point": 0x082000,
        "image_size_words": 8,
        "image_crc32": 0x1234,
        "app_end": 0x082008 if operation is AdvancedMetadataOperationType.WRITE_IMAGE_VALID else None,
    }
    assert rendered["status"] == "FAILED"
    assert rendered["primary_result"] is None
    assert rendered["written"] is None
    assert rendered["already_exists"] is None
    assert rendered["reason"] is None
    assert rendered["readback_result"] is None
    assert rendered["metadata_summary"] is None
    assert rendered["error"]["code"] == code
    assert rendered["error"]["recoverable"] is True
    assert rendered["error"]["disposition"] == "SHOW_ONLY"
    assert rendered["error"]["outcome_uncertain"] is False
    assert rendered["error"]["details"]["recovery"]["steps"] == ["prepare", "retry"]


def test_complete_warning_and_error_serialization_is_strict(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    binding.write_boot_attempt()
    admission = controller.last_admission
    owned = binding._owned[admission.task_id]
    warning = GuiTaskWarning(
        "COMPLETED_AFTER_CANCEL_REQUEST",
        "completed",
        "metadata",
        {"recovery_action": "NONE", "service_attached": True, "nested": [1, {"ok": True}]},
    )
    binding._task_finished(
        TaskExecutionResult(
            admission.task_id,
            TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST,
            "completed",
            "completed",
            warning=warning,
            cancel_requested=True,
        )
    )
    rendered = json.loads(page.result_output.toPlainText())
    assert rendered["warning"] == {
        "code": "COMPLETED_AFTER_CANCEL_REQUEST",
        "message": "completed",
        "stage": "metadata",
        "details": {
            "recovery_action": "NONE",
            "service_attached": True,
            "nested": [1, {"ok": True}],
        },
    }
    assert rendered["cancel_requested"] is True

    bad_error = GuiRuntimeError(
        "BAD", "bad", "metadata", ErrorDisposition.SHOW_ONLY, admission.task_id
    )
    object.__setattr__(bad_error, "details", {"unsupported": object()})
    binding._owned[admission.task_id] = owned
    with pytest.raises(TypeError, match="Unsupported Shared Result value"):
        binding._task_finished(
            TaskExecutionResult(
                admission.task_id,
                TaskFinalStatus.FAILED,
                "failed",
                "failed",
                error=bad_error,
            )
        )


def test_binding_has_no_operation_or_lower_layer_imports() -> None:
    import bootloader_upgrade_tool.gui.advanced_metadata_binding as module

    source = inspect.getsource(module)
    assert "operation_result_to_dict" not in source
    assert not any(
        token in source
        for token in ("..operations", "..images", "..protocol", "..session", "..transport", "..targets")
    )
