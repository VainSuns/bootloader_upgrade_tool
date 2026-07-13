from __future__ import annotations

from dataclasses import asdict, FrozenInstanceError
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QEventLoop, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.image_preparation_models import (
    Hex2000Source,
    ImageSourceKind,
    PreparedImageSummary,
    PrepareFlashImageRequest,
    SourceFileFingerprint,
)
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.pages.program_page import ProgramTargetPage
from bootloader_upgrade_tool.gui.pages.settings_page import SettingsPage
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_binding import RuntimeViewBinding
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
    ErrorDisposition,
    RequestAdmission,
    RuntimeSnapshot,
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.gui.status_models import (
    DeviceInfoRequest,
    DeviceInfoStatusSnapshot,
    LastErrorRequest,
    LastErrorStatusSnapshot,
    LoadedImageMatch,
    MetadataRefreshRequest,
    MetadataScanState,
    MetadataStatusSnapshot,
    ProtocolInfoRequest,
    ProtocolInfoStatusSnapshot,
    StatusRequest,
)
from bootloader_upgrade_tool.gui.widgets.ribbon.operate_ribbon import OperateRibbon
from bootloader_upgrade_tool.operations import OperationErrorInfo, OperationResult
from bootloader_upgrade_tool.protocol.boot_protocol_client import ProtocolInfo
from bootloader_upgrade_tool.protocol.models import DeviceInfo, ErrorDetail, MetadataSummary
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


def _connection(connection_id: str = "connection", target_key: str = "cpu1") -> ConnectionInfo:
    return ConnectionInfo(connection_id, "SCI", "COM3", datetime.now(timezone.utc), target_key)


def _device_info(*, cpu_id: int = 1, device_id: int = 0x377D) -> DeviceInfo:
    return DeviceInfo(device_id, cpu_id, 1, 0, 0, 1, 0, 256, 8, 2, 2)


def _metadata(**overrides: int) -> MetadataSummary:
    values = dict(
        metadata_valid=1,
        active_slot=1,
        latest_record_type=1,
        boot_attempt_count=1,
        app_confirmed=1,
        boot_attempt_limit=0,
        app_version_major=1,
        app_version_minor=0,
        app_version_patch=0,
        app_version_build=0,
        entry_point=0x082400,
        image_crc32=0x12345678,
        state=int(MetadataScanState.VALID),
        valid_record_count=1,
        invalid_record_count=0,
        erased_record_count=0,
        free_record_count=1,
        next_record_index=1,
        image_size_words=8,
        target_device_id=0x377D,
        target_cpu_id=1,
    )
    values.update(overrides)
    return MetadataSummary(**values)


def _protocol_info() -> ProtocolInfo:
    return ProtocolInfo(1, 1, 1, 8, 1, 1, 256, 0)


def _last_error() -> ErrorDetail:
    return ErrorDetail(1, 2, 0x082400, 8, 0, 0, 0, 0)


def _ok(operation: str, model) -> OperationResult:
    return OperationResult(True, operation, "cpu1", operation.upper(), asdict(model))


def _failed(operation: str, code: str) -> OperationResult:
    error = OperationErrorInfo(code, "failed", operation.upper(), True, {})
    return OperationResult(False, operation, "cpu1", operation.upper(), {}, error=error)


def _backend(**operations) -> RuntimeBackend:
    backend = RuntimeBackend(**operations)
    backend._session = SimpleNamespace(client=SimpleNamespace())
    backend._target = CPU1_PROFILE
    backend._device_info = _device_info()
    backend._connection_info = _connection()
    return backend


def _prepared_summary(tmp_path, **overrides) -> PreparedImageSummary:
    source = tmp_path / "app.txt"
    source.write_text("test")
    values = dict(
        target_key="cpu1",
        selection_revision=1,
        source_path=str(source),
        source_kind=ImageSourceKind.TXT,
        source_fingerprint=SourceFileFingerprint(str(source), 4, 1),
        entry_point=0x082400,
        image_size_words=8,
        image_crc32=0x12345678,
        app_end=0x082408,
        image_sector_mask=2,
        effective_sector_mask=2,
        image_sector_bits=(1,),
        hex2000_source=Hex2000Source.NOT_USED,
        hex2000_executable=None,
    )
    values.update(overrides)
    return PreparedImageSummary(**values)


def test_requests_are_explicit_connection_bound_frozen_plans() -> None:
    with pytest.raises(TypeError):
        StatusRequest("id")
    with pytest.raises(ValueError):
        MetadataRefreshRequest(" ")
    request = MetadataRefreshRequest(" id ", automatic=True)
    assert request.connection_id == "id" and request.automatic is True
    with pytest.raises(FrozenInstanceError):
        request.connection_id = "other"
    for item in (request, DeviceInfoRequest("id"), ProtocolInfoRequest("id"), LastErrorRequest("id")):
        plan = item.create_plan("task")
        assert plan.connection_requirement.name == "CONNECTED"
        assert len(plan.steps) == 1 and plan.steps[0].initial_progress_mode.name == "INDETERMINATE"
        assert plan.cancellable is False and plan.completion_policy.name == "AUTO_CLOSE_ON_CLEAN_SUCCESS"
        assert not hasattr(item, "operation")


def test_backend_dispatches_each_concrete_request_once_and_returns_typed_snapshots() -> None:
    calls = []

    def operation(name, model):
        def run(ctx):
            calls.append((name, ctx.target))
            return _ok(name, model)

        return run

    backend = _backend(
        metadata_operation=operation("get_metadata_summary", _metadata()),
        device_info_operation=operation("get_device_info", _device_info()),
        protocol_info_operation=operation("get_protocol_info", _protocol_info()),
        last_error_operation=operation("get_last_error", _last_error()),
    )
    requests = (
        (MetadataRefreshRequest("connection"), MetadataStatusSnapshot),
        (DeviceInfoRequest("connection"), DeviceInfoStatusSnapshot),
        (ProtocolInfoRequest("connection"), ProtocolInfoStatusSnapshot),
        (LastErrorRequest("connection"), LastErrorStatusSnapshot),
    )
    for index, (request, snapshot_type) in enumerate(requests):
        result = backend.execute(str(index), request, None, lambda _event: None)
        assert result.status is TaskFinalStatus.SUCCEEDED
        assert isinstance(result.payload, snapshot_type)
        assert isinstance(result.step_results[0], OperationResult)
    assert calls == [
        ("get_metadata_summary", CPU1_PROFILE),
        ("get_device_info", CPU1_PROFILE),
        ("get_protocol_info", CPU1_PROFILE),
        ("get_last_error", CPU1_PROFILE),
    ]


def test_stale_precheck_does_not_call_operation_or_change_cache() -> None:
    calls = []
    backend = _backend(metadata_operation=lambda _ctx: calls.append(1))
    sentinel = object()
    backend._metadata_status_snapshot = sentinel

    result = backend.execute("task", MetadataRefreshRequest("old"), None, None)

    assert result.error.code == "STALE_CONNECTION"
    assert result.error.disposition is ErrorDisposition.SHOW_ONLY
    assert calls == [] and backend.metadata_status_snapshot is sentinel


def test_stale_postcheck_does_not_overwrite_new_connection_cache() -> None:
    backend = None
    new_snapshot = object()

    def metadata(_ctx):
        backend._connection_info = _connection("new")
        backend._session = SimpleNamespace(client=SimpleNamespace())
        backend._target = CPU1_PROFILE
        backend._metadata_status_snapshot = new_snapshot
        return _ok("get_metadata_summary", _metadata())

    backend = _backend(metadata_operation=metadata)
    result = backend.execute("task", MetadataRefreshRequest("connection"), None, None)

    assert result.error.code == "STALE_CONNECTION"
    assert backend.metadata_status_snapshot is new_snapshot
    assert isinstance(result.step_results[0], OperationResult)


def test_stale_failed_operation_does_not_clear_new_connection_cache() -> None:
    backend = None
    new_snapshot = object()

    def metadata(_ctx):
        backend._connection_info = _connection("new")
        backend._session = SimpleNamespace(client=SimpleNamespace())
        backend._metadata_status_snapshot = new_snapshot
        return _failed("get_metadata_summary", "PROTOCOL_ERROR")

    backend = _backend(metadata_operation=metadata)
    result = backend.execute("task", MetadataRefreshRequest("connection"), None, None)
    assert result.error.code == "STALE_CONNECTION"
    assert backend.metadata_status_snapshot is new_snapshot


def test_metadata_derivation_is_backend_owned_and_attempt_limit_is_not_bootability() -> None:
    backend = _backend(metadata_operation=lambda _ctx: _ok("get_metadata_summary", _metadata(boot_attempt_count=5, boot_attempt_limit=1)))
    result = backend.execute("task", MetadataRefreshRequest("connection", automatic=True), None, None)
    snapshot = result.payload
    assert snapshot.metadata_valid and snapshot.image_valid and snapshot.entry_point_valid
    assert snapshot.boot_attempt_present and snapshot.app_confirmed and snapshot.confirmed_bootable
    assert snapshot.loaded_image_match is LoadedImageMatch.NO_PREPARED_IMAGE
    assert snapshot.automatic is True and backend.metadata_status_snapshot == snapshot


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"state": int(MetadataScanState.EMPTY)}, "metadata_valid"),
        ({"target_cpu_id": 2}, "image_valid"),
        ({"image_crc32": 0}, "image_valid"),
        ({"entry_point": 0x080000}, "entry_point_valid"),
        ({"entry_point": 0x082401}, "entry_point_valid"),
        ({"boot_attempt_count": 0}, "boot_attempt_present"),
        ({"app_confirmed": 0}, "app_confirmed"),
    ],
)
def test_metadata_derivation_rejects_invalid_components(overrides, field) -> None:
    backend = _backend(metadata_operation=lambda _ctx: _ok("get_metadata_summary", _metadata(**overrides)))
    snapshot = backend.execute("task", MetadataRefreshRequest("connection"), None, None).payload
    assert getattr(snapshot, field) is False
    assert snapshot.confirmed_bootable is False


def test_loaded_image_match_uses_only_current_cpu1_summary(tmp_path) -> None:
    backend = _backend(metadata_operation=lambda _ctx: _ok("get_metadata_summary", _metadata()))
    backend._prepared_image_summary = _prepared_summary(tmp_path)
    matched = backend.execute("match", MetadataRefreshRequest("connection"), None, None).payload
    assert matched.loaded_image_match is LoadedImageMatch.MATCH

    backend._prepared_image_summary = _prepared_summary(tmp_path, image_crc32=1)
    mismatch = backend.execute("mismatch", MetadataRefreshRequest("connection"), None, None).payload
    assert mismatch.loaded_image_match is LoadedImageMatch.MISMATCH

    backend._target = CPU2_PROFILE
    backend._device_info = _device_info(cpu_id=2)
    backend._connection_info = _connection(target_key="cpu2")
    backend._metadata_operation = lambda _ctx: _ok("get_metadata_summary", _metadata(target_cpu_id=2))
    cpu2 = backend.execute("cpu2", MetadataRefreshRequest("connection"), None, None).payload
    assert cpu2.loaded_image_match is LoadedImageMatch.NO_PREPARED_IMAGE

    backend._target = CPU1_PROFILE
    backend._device_info = _device_info()
    backend._connection_info = _connection()
    backend._metadata_operation = lambda _ctx: _ok("get_metadata_summary", _metadata(metadata_valid=0))
    invalid = backend.execute("invalid", MetadataRefreshRequest("connection"), None, None).payload
    assert invalid.loaded_image_match is LoadedImageMatch.NO_VALID_TARGET_IMAGE


def test_device_info_reread_updates_only_after_identity_match() -> None:
    backend = _backend(device_info_operation=lambda _ctx: _ok("get_device_info", _device_info()))
    matched = backend.execute("match", DeviceInfoRequest("connection"), None, None)
    assert matched.status is TaskFinalStatus.SUCCEEDED and backend.active_device_info == matched.payload.device_info

    original = backend.active_device_info
    backend._device_info_operation = lambda _ctx: _ok("get_device_info", _device_info(cpu_id=2))
    mismatch = backend.execute("mismatch", DeviceInfoRequest("connection"), None, None)
    assert mismatch.error.code == "TARGET_MISMATCH"
    assert mismatch.error.disposition is ErrorDisposition.ASK_DISCONNECT
    assert backend.active_device_info is original and mismatch.payload is None


@pytest.mark.parametrize(
    ("code", "disposition"),
    [
        ("UNSUPPORTED_OPERATION", ErrorDisposition.SHOW_ONLY),
        ("DSP_STATUS_ERROR", ErrorDisposition.SHOW_ONLY),
        ("PROTOCOL_ERROR", ErrorDisposition.ASK_DISCONNECT),
        ("TARGET_MISMATCH", ErrorDisposition.ASK_DISCONNECT),
    ],
)
def test_status_error_mapping_and_failed_result_contract(code, disposition) -> None:
    backend = _backend(protocol_info_operation=lambda _ctx: _failed("get_protocol_info", code))
    result = backend.execute("task", ProtocolInfoRequest("connection"), None, None)
    assert result.status is TaskFinalStatus.FAILED and result.error.disposition is disposition
    assert result.payload is None and isinstance(result.step_results[0], OperationResult)


def test_invalid_operation_results_raise_contract_exceptions() -> None:
    backend = _backend(protocol_info_operation=lambda _ctx: object())
    with pytest.raises(TypeError):
        backend.execute("bad-type", ProtocolInfoRequest("connection"), None, None)

    backend._protocol_info_operation = lambda _ctx: OperationResult(False, "get_protocol_info", "cpu1", "stage", {})
    with pytest.raises(RuntimeError, match="error details"):
        backend.execute("missing-error", ProtocolInfoRequest("connection"), None, None)

    backend._protocol_info_operation = lambda _ctx: (_ for _ in ()).throw(ArithmeticError("bug"))
    with pytest.raises(ArithmeticError, match="bug"):
        backend.execute("unknown", ProtocolInfoRequest("connection"), None, None)


def test_metadata_failure_clears_only_metadata_cache() -> None:
    backend = _backend(metadata_operation=lambda _ctx: _failed("get_metadata_summary", "DSP_STATUS_ERROR"))
    backend._metadata_status_snapshot = object()
    failed = backend.execute("metadata", MetadataRefreshRequest("connection"), None, None)
    assert failed.error.code == "DSP_STATUS_ERROR" and backend.metadata_status_snapshot is None

    sentinel = object()
    backend._metadata_status_snapshot = sentinel
    backend._protocol_info_operation = lambda _ctx: _failed("get_protocol_info", "DSP_STATUS_ERROR")
    backend.execute("diagnostic", ProtocolInfoRequest("connection"), None, None)
    assert backend.metadata_status_snapshot is sentinel

    failed_image = backend.execute(
        "image", PrepareFlashImageRequest("cpu1", "", 0), None, None
    )
    assert failed_image.error.code == "INVALID_IMAGE_PATH"
    assert backend.metadata_status_snapshot is sentinel


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


def _binding():
    app = QApplication.instance() or QApplication([])
    ribbon, settings = OperateRibbon(), SettingsPage()
    program, advanced = ProgramTargetPage("cpu1"), AdvancedPage()
    controller = _Controller()
    view = SimpleNamespace(
        operate_ribbon=ribbon,
        settings_page=settings,
        program_cpu1_page=program,
        advanced_page=advanced,
    )
    return app, RuntimeViewBinding(view, controller), controller, program, advanced


def test_cpu1_auto_refresh_is_connection_bound_one_shot_and_manual_wins() -> None:
    app, binding, controller, _program, _advanced = _binding()
    connected = RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=_connection(), active_target_key="cpu1")
    binding.apply_snapshot(connected)
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert len(controller.requests) == 1
    assert controller.requests[0] == MetadataRefreshRequest("connection", automatic=True)

    binding.apply_snapshot(RuntimeSnapshot(RuntimeState.BUSY, "manual", _connection(), "cpu1"))
    binding.apply_snapshot(connected)
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert len(controller.requests) == 1

    binding.apply_snapshot(RuntimeSnapshot())
    binding.apply_snapshot(connected)
    binding.request_status("get_metadata_summary")
    app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
    assert controller.requests[-1] == MetadataRefreshRequest("connection")
    assert len(controller.requests) == 2


def test_binding_uses_current_connection_and_ignores_stale_snapshots() -> None:
    _app, binding, controller, program, advanced = _binding()
    assert binding.request_status("get_device_info") is None
    connected = RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=_connection("new"), active_target_key="cpu1")
    binding.apply_snapshot(connected)
    binding.request_status("get_device_info")
    assert controller.requests[-1] == DeviceInfoRequest("new")

    operation = _ok("get_metadata_summary", _metadata())
    stale = MetadataStatusSnapshot(
        "old", "cpu1", operation, _metadata(), True, True, True, True, True, True,
        LoadedImageMatch.MATCH, False,
    )
    previous_result = advanced.result_output.toPlainText()
    controller.taskFinished.emit(TaskExecutionResult("stale", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=stale))
    assert program.status_rows["metadata_valid"].state_widget.text_label.text() == "Unknown"
    assert advanced.result_output.toPlainText() == previous_result


def test_binding_renders_metadata_snapshot_without_rederiving_bootability() -> None:
    _app, binding, controller, program, advanced = _binding()
    binding.apply_snapshot(RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=_connection(), active_target_key="cpu1"))
    operation = _ok("get_metadata_summary", _metadata(boot_attempt_count=0, app_confirmed=0))
    snapshot = MetadataStatusSnapshot(
        "connection", "cpu1", operation, _metadata(boot_attempt_count=0, app_confirmed=0),
        True, True, True, False, False, True, LoadedImageMatch.MISMATCH, False,
    )
    controller.taskFinished.emit(TaskExecutionResult("task", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot))
    assert program.status_rows["confirmed_bootable"].state_widget.text_label.text() == "Yes"
    assert program.status_rows["loaded_image_matches"].state_widget.text_label.text() == "No"
    assert "get_metadata_summary" in advanced.result_output.toPlainText()
