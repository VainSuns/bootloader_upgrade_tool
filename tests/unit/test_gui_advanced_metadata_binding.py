from dataclasses import asdict, replace
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_flash_models import PreparedAdvancedFlashImageSummary
from bootloader_upgrade_tool.gui.advanced_metadata_binding import AdvancedMetadataOperationBinding
from bootloader_upgrade_tool.gui.advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
    AdvancedMetadataOperationType,
    CleanVerifyCredential,
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
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataStatusSnapshot
from bootloader_upgrade_tool.images import ImageIdentity, PreparedFlashImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import OperationResult, operation_result_to_dict
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
    configuration_revision = 2

    def __init__(self, image_cache, service_state, credential, metadata):
        self.image_cache = image_cache
        self.flash_service_resource_state = service_state
        self.clean_verify_credential = credential
        self.metadata_status_snapshot = metadata
        self.active_target = CPU1_PROFILE
        self.image_revision = 1

    def prepared_advanced_flash_image_cache(self, target):
        return self.image_cache if target == "cpu1" else None

    def advanced_flash_selection_revision(self, target):
        return self.image_revision

    @property
    def service_configuration_revision(self):
        return self.flash_service_resource_state.revision


def _fingerprint(path: Path):
    return SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)


def _setup(tmp_path: Path):
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
    image = PreparedFlashImage(firmware, ImageIdentity(0x082000, 8, 0x1234, 0x082008), 0x2)
    image_summary = PreparedAdvancedFlashImageSummary(
        "cpu1", str(app_path), 1, 2, ImageSourceKind.TXT, _fingerprint(app_path),
        0x082000, 8, 0x1234, 0x082008, 0x2, 0x2, Hex2000Source.NOT_USED, None,
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
    credential = CleanVerifyCredential(
        "token", "connection", "cpu1", 1, 2, image_summary.source_fingerprint,
        0x082000, 8, 0x1234, 0x082008,
    )
    backend = Backend((image, image_summary), service_state, credential, metadata)
    applied = []
    cleared = []
    binding = AdvancedMetadataOperationBinding(
        page, controller, backend,
        apply_metadata_snapshot=lambda snapshot: applied.append(snapshot) or True,
        clear_metadata=lambda: cleared.append(True),
    )
    return page, controller, backend, binding, image_summary, operation, applied, cleared


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


def test_button_state_uses_current_cpu1_caches_credential_and_metadata(tmp_path) -> None:
    page, controller, backend, _binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    assert page.write_image_valid_button.isEnabled()
    assert page.write_boot_attempt_button.isEnabled()
    assert page.write_app_confirmed_button.isEnabled()

    backend.clean_verify_credential = None
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
    assert controller.requests[0].verification_token == "token"
    assert len(cleared) == 3


def test_current_owned_result_renders_strict_json_and_applies_readback(tmp_path) -> None:
    page, controller, backend, binding, image_summary, operation, applied, _cleared = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    admission = binding.write_boot_attempt()
    metadata = backend.metadata_status_snapshot
    primary = OperationResult(
        True, "append_boot_attempt", "cpu1", "METADATA",
        {"written": True, "already_exists": False, "reason": None},
    )
    payload = AdvancedMetadataOperationSnapshot(
        "connection", "cpu1", 1, 2, 3, 2,
        AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, None,
        image_summary.entry_point, image_summary.image_size_words,
        image_summary.image_crc32, image_summary.app_end,
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
    assert applied == [metadata]


def test_stale_result_does_not_overwrite_shared_result(tmp_path) -> None:
    page, controller, backend, binding, image_summary, _operation, applied, _cleared = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    admission = binding.write_boot_attempt()
    page.result_output.setPlainText("keep")
    _apply(controller, backend, _connected("new"), CPU1_PROFILE)
    primary = OperationResult(True, "append", "cpu1", "METADATA", {})
    payload = AdvancedMetadataOperationSnapshot(
        "connection", "cpu1", 1, 2, 3, 2,
        AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, None,
        image_summary.entry_point, image_summary.image_size_words,
        image_summary.image_crc32, image_summary.app_end,
        primary, operation_result_to_dict(primary),
    )
    controller.taskFinished.emit(
        TaskExecutionResult(admission.task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload)
    )
    assert page.result_output.toPlainText() == "keep"
    assert applied == []


def test_owned_advanced_metadata_service_change_failure_remains_visible(tmp_path) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    admission = binding.write_boot_attempt()
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
        (AdvancedMetadataOperationType.WRITE_IMAGE_VALID, "CLEAN_VERIFY_REQUIRED"),
        (AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, "IMAGE_CHANGED"),
        (AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, "SERVICE_CHANGED"),
        (AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, "STALE_CONNECTION"),
        (AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT, "UNSUPPORTED_OPERATION"),
    ],
)
def test_owned_no_payload_failure_retains_submitted_context(tmp_path, operation, code) -> None:
    page, controller, backend, binding, *_ = _setup(tmp_path)
    _apply(controller, backend, _connected(), CPU1_PROFILE)
    admission = binding._submit_operation(operation)
    if operation is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
        backend.clean_verify_credential = None
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
    )] == [1, 2, 3, 2]
    assert rendered["prepared_image"] == {
        "entry_point": 0x082000,
        "image_size_words": 8,
        "image_crc32": 0x1234,
        "app_end": 0x082008,
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
    admission = binding.write_boot_attempt()
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
