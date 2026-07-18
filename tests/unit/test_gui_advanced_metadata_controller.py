from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_metadata_binding import AdvancedMetadataOperationBinding
from bootloader_upgrade_tool.gui.advanced_metadata_models import CleanVerifyCredential
from bootloader_upgrade_tool.gui.advanced_read_binding import AdvancedReadOnlyBinding
from bootloader_upgrade_tool.gui.controller import GuiController
from bootloader_upgrade_tool.gui.flash_service_models import (
    DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
    FlashServiceResourceState,
    FlashServiceResourceStatus,
    PreparedFlashServiceSummary,
)
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    FlashImageSummary, ImageParseStatus, RuntimeCpuId, TargetResourceState,
)
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
    ProgressMode,
    RuntimeSnapshot,
    RuntimeState,
    TaskDialogAction,
    TaskFinalStatus,
    TaskStepState,
)
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataStatusSnapshot
from bootloader_upgrade_tool.images import ImageIdentity, PreparedFlashImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import (
    OperationCancellationInfo,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
    ProgressEvent,
)
from bootloader_upgrade_tool.protocol.models import DeviceInfo, MetadataSummary
from bootloader_upgrade_tool.targets import CPU1_PROFILE


APP = QApplication.instance() or QApplication([])
CONTROLLERS = []


def _wait(predicate, timeout=3.0):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        APP.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
    assert predicate()


class _Session:
    def __init__(self):
        self.disconnects = 0

    def disconnect(self):
        self.disconnects += 1


class _Provider:
    def __init__(self, image_path: Path, map_path: Path) -> None:
        self.image_path = image_path
        self.map_path = map_path

    def flash_service_image_path(self) -> Path:
        return self.image_path

    def flash_service_map_path(self) -> Path:
        return self.map_path


def _fingerprint(path: Path):
    return SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)


def _raw_metadata(*, attempts=1, confirmed=0):
    return MetadataSummary(
        1, 1, 1, attempts, confirmed, 3, 1, 0, 0, 0,
        0x082000, 0x1234, 1, 1, 0, 0, 1, 1, 8, 0x377D, 1,
    )


def _fixture(tmp_path, append_operation, metadata_operation):
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
    image = PreparedFlashImage(
        firmware, ImageIdentity(0x082000, 8, 0x1234, 0x082008), 0x2
    )
    service = PreparedServiceImage(firmware, 0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF)
    provider = _Provider(service_path, map_path)
    service_summary = PreparedFlashServiceSummary(
        target_key="cpu1",
        provider_name=type(provider).__name__,
        service_image_path=str(service_path),
        service_map_path=str(map_path),
        descriptor_symbol=DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
        resource_revision=3,
        tool_configuration_revision=2,
        image_source_kind=ImageSourceKind.TXT,
        image_fingerprint=_fingerprint(service_path),
        map_fingerprint=_fingerprint(map_path),
        descriptor_address=0x10000,
        api_table_address=0x10020,
        crc_patch_address=0x10030,
        total_words=8,
        expected_crc32=0x5678,
        required_capabilities=0xF,
        hex2000_source=Hex2000Source.NOT_USED,
        hex2000_executable=None,
    )
    backend = RuntimeBackend(
        app_resource_provider=provider,
        prepare_flash_operation=lambda *_args, **_kwargs: replace(image),
        prepare_service_operation=lambda *_args, **_kwargs: replace(service),
        metadata_operation=metadata_operation,
        append_boot_attempt_operation=append_operation,
    )
    session = _Session()
    connection = ConnectionInfo(
        "connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu1"
    )
    backend._session = session
    backend._target = CPU1_PROFILE
    backend._device_info = DeviceInfo(0x377D, 1, 1, 0, 0, 1, 0, 64, 56, 0, 0)
    backend._connection_info = connection
    backend._configuration_revision = 2
    backend._program_image_revisions[RuntimeCpuId.CPU1] = 1
    backend._runtime_v2_store.replace_target_resource(
        RuntimeCpuId.CPU1,
        TargetResourceState(
            RuntimeCpuId.CPU1,
            program_image_path=str(app_path),
            program_image_summary=FlashImageSummary(image.identity, image.sector_mask),
            program_image_parse_status=ImageParseStatus.READY,
        ),
    )
    backend._flash_service_resource_state = FlashServiceResourceState(
        revision=3,
        provider_name=type(provider).__name__,
        image_path=str(service_path),
        map_path=str(map_path),
        status=FlashServiceResourceStatus.READY,
        summary=service_summary,
    )
    backend._clean_verify_credential = CleanVerifyCredential(
        "token", "connection", "cpu1", 1, 2, _fingerprint(app_path),
        0x082000, 8, 0x1234, 0x082008,
    )
    initial_raw = _raw_metadata()
    initial_result = OperationResult(
        True, "get_metadata_summary", "cpu1", "GET_METADATA_SUMMARY", asdict(initial_raw)
    )
    backend._metadata_status_snapshot = MetadataStatusSnapshot(
        "connection", "cpu1", initial_result, initial_raw,
        True, True, True, True, False, False, LoadedImageMatch.MATCH, False,
    )

    controller = GuiController(backend, backend)
    CONTROLLERS.append(controller)
    page = AdvancedPage()
    read_binding = AdvancedReadOnlyBinding(page, controller, lambda: backend.active_target)
    applied = []
    original_apply = read_binding.apply_external_metadata_snapshot

    def apply(snapshot):
        applied.append(snapshot)
        return original_apply(snapshot)

    binding = AdvancedMetadataOperationBinding(
        page,
        controller,
        backend,
        apply_metadata_snapshot=apply,
        clear_metadata=read_binding.clear_metadata,
    )
    connected = RuntimeSnapshot(
        RuntimeState.CONNECTED, connection_info=connection, active_target_key="cpu1"
    )
    controller._snapshot = connected
    controller.runtimeStateChanged.emit(connected)
    return page, controller, backend, binding, read_binding, session, applied


def _successful_readback(raw=None, reads=None):
    raw = raw or _raw_metadata()

    def read(ctx):
        if reads is not None:
            reads.append(ctx)
        return OperationResult(
            True, "get_metadata_summary", ctx.target.name, "GET_METADATA_SUMMARY", asdict(raw)
        )

    return read


def _successful_append(ctx, _request):
    ctx.progress(ProgressEvent("service_load", ctx.target.name, "SERVICE_LOAD", "load", 2, 10, 2))
    ctx.progress(ProgressEvent("append_boot_attempt", ctx.target.name, "METADATA_APPEND", "append", 1, 3, 1))
    return OperationResult(
        True, "append_boot_attempt", ctx.target.name, "METADATA_APPEND",
        {"written": True, "already_exists": False, "reason": None},
    )


def test_clean_success_runs_two_steps_through_real_controller(tmp_path):
    page, controller, _backend, binding, _read, _session, _applied = _fixture(
        tmp_path, _successful_append, _successful_readback()
    )
    progress, errors, finished = [], [], []
    controller.taskProgressed.connect(progress.append)
    controller.runtimeErrorRaised.connect(errors.append)
    controller.taskFinished.connect(finished.append)
    admission = binding.write_boot_attempt()
    _wait(lambda: controller.snapshot.active_task_id is None)

    assert admission.accepted and not errors
    assert controller.snapshot.state is RuntimeState.CONNECTED
    assert controller.snapshot.last_error is None
    assert all(
        item.progress_mode is ProgressMode.INDETERMINATE
        and item.current is None and item.total is None
        for item in progress
    )
    assert [(item.step_id, item.step_state) for item in progress] == [
        ("write_boot_attempt", TaskStepState.STARTED),
        ("write_boot_attempt", TaskStepState.PROGRESS),
        ("write_boot_attempt", TaskStepState.PROGRESS),
        ("write_boot_attempt", TaskStepState.COMPLETED),
        ("read_metadata_summary", TaskStepState.STARTED),
        ("read_metadata_summary", TaskStepState.COMPLETED),
    ]
    assert finished[-1].status is TaskFinalStatus.SUCCEEDED
    assert json.loads(page.result_output.toPlainText())["status"] == "SUCCEEDED"
    assert page.metadata_summary_values["boot_attempt"].text() == "Yes (1)"


def test_completed_after_cancel_keeps_status_and_required_readback(tmp_path):
    reads, calls = [], []
    cancellation = OperationCancellationInfo(
        "METADATA_APPEND", 1, 1, True, False, False,
        service_attached=True, recovery_action="NONE",
    )

    def completed(ctx, _request):
        calls.append("metadata")
        return OperationResult(
            True, "append_boot_attempt", ctx.target.name, "METADATA_APPEND",
            {"written": True, "already_exists": False, "reason": None},
            completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
            cancellation=cancellation,
        )

    page, controller, _backend, binding, _read, _session, _applied = _fixture(
        tmp_path, completed, _successful_readback(reads=reads)
    )
    errors = []
    controller.runtimeErrorRaised.connect(errors.append)
    admission = binding.write_boot_attempt()
    _wait(lambda: controller.snapshot.active_task_id is None)
    rendered = json.loads(page.result_output.toPlainText())

    assert admission.accepted and not errors
    assert rendered["status"] == "COMPLETED_AFTER_CANCEL_REQUEST"
    assert rendered["warning"]["details"]["service_attached"] is True
    cancellation_data = rendered["primary_result"]["cancellation"]
    assert cancellation_data["protocol_state_clean"] is True
    assert cancellation_data["recovery_action"] == "NONE"
    assert calls == ["metadata"] and len(reads) == 1
    assert controller.snapshot.state is RuntimeState.CONNECTED


def test_readback_protocol_failure_disconnect_retains_result(tmp_path):
    def failed_read(ctx):
        return OperationResult(
            False, "get_metadata_summary", ctx.target.name, "GET_METADATA_SUMMARY", {},
            error=OperationErrorInfo(
                "PROTOCOL_ERROR", "lost", "GET_METADATA_SUMMARY", True,
                {"protocol_state_clean": False, "recovery_action": "RECONNECT_AND_RESTART_VERIFY"},
            ),
        )

    page, controller, _backend, binding, _read, session, applied = _fixture(
        tmp_path, _successful_append, failed_read
    )
    errors = []
    controller.runtimeErrorRaised.connect(errors.append)
    admission = binding.write_boot_attempt()
    _wait(lambda: controller.snapshot.disconnect_decision_pending)
    assert controller.respond_task_action(admission.task_id, TaskDialogAction.DISCONNECT).accepted
    _wait(lambda: controller.snapshot.active_task_id is None)
    rendered = json.loads(page.result_output.toPlainText())

    assert not errors and controller.snapshot.state is RuntimeState.DISCONNECTED
    assert controller.snapshot.connection_info is None and session.disconnects == 1
    assert rendered["error"]["disposition"] == "ASK_DISCONNECT"
    assert rendered["error"]["outcome_uncertain"] is True
    assert rendered["primary_result"]["summary"]["written"] is True
    assert rendered["readback_result"]["error"]["details"]["protocol_state_clean"] is False
    assert rendered["prepared_image"]["image_crc32"] == 0x1234
    assert [rendered[name] for name in (
        "image_selection_revision", "image_tool_configuration_revision",
        "service_configuration_revision", "service_tool_configuration_revision",
    )] == [1, 2, 3, 2]
    assert not applied
    assert all(label.text() == "Unknown" for label in page.metadata_summary_values.values())


def test_readback_mismatch_disconnect_retains_result_and_unknown_summary(tmp_path):
    page, controller, _backend, binding, _read, _session, applied = _fixture(
        tmp_path, _successful_append, _successful_readback(_raw_metadata(attempts=0))
    )
    errors = []
    controller.runtimeErrorRaised.connect(errors.append)
    admission = binding.write_boot_attempt()
    _wait(lambda: controller.snapshot.disconnect_decision_pending)
    controller.respond_task_action(admission.task_id, TaskDialogAction.DISCONNECT)
    _wait(lambda: controller.snapshot.active_task_id is None)
    rendered = json.loads(page.result_output.toPlainText())

    assert not errors and controller.snapshot.state is RuntimeState.DISCONNECTED
    assert rendered["error"]["code"] == "METADATA_READBACK_MISMATCH"
    assert rendered["primary_result"] is not None
    assert rendered["readback_result"] is not None
    assert rendered["metadata_summary"] is not None
    assert not applied
    assert all(label.text() == "Unknown" for label in page.metadata_summary_values.values())
