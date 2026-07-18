from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import pytest
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_flash_models import PreparedAdvancedFlashImageSummary
from bootloader_upgrade_tool.gui.advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    AdvancedFlashOperationSnapshot,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
)
from bootloader_upgrade_tool.gui.advanced_metadata_models import CleanVerifyCredential
from bootloader_upgrade_tool.gui.flash_service_models import (
    DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
    FlashServiceResourceState,
    FlashServiceResourceStatus,
    PreparedFlashServiceSummary,
)
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_v2_models import RuntimeCpuId
from bootloader_upgrade_tool.gui.controller import GuiController
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, ErrorDisposition, ProgressMode, RuntimeSnapshot, RuntimeState, TaskCompletionAction, TaskFinalStatus, TaskStepState
from bootloader_upgrade_tool.images import ImageIdentity, PreparedFlashImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import OperationCancellationInfo, OperationCompletion, OperationErrorInfo, OperationResult, ProgressEvent
from bootloader_upgrade_tool.operations.flash_ops import EraseFlashImageAreaRequest, EraseSectorMaskRequest, ProgramFlashImageRequest, VerifyFlashImageRequest
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


IDENTITY = ("connection", "cpu1", 1, 2, 3, 2)


class Provider:
    def __init__(self, image, map_file):
        self.image, self.map_file = image, map_file

    def flash_service_image_path(self): return self.image
    def flash_service_map_path(self): return self.map_file


def fingerprint(path: Path) -> SourceFileFingerprint:
    return SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)


def populated_backend(tmp_path: Path, calls: list, **overrides) -> tuple[RuntimeBackend, Path, Path, Path]:
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
        "cpu1", str(app_path), 1, 2, ImageSourceKind.TXT, fingerprint(app_path),
        0x082000, 8, 0x1234, 0x082008, 0x2, 0x2, Hex2000Source.NOT_USED, None,
    )
    service = PreparedServiceImage(firmware, 0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF)
    service_summary = PreparedFlashServiceSummary(
        "cpu1", "Provider", str(service_path), str(map_path), DEFAULT_SERVICE_DESCRIPTOR_SYMBOL, 3, 2,
        ImageSourceKind.TXT, fingerprint(service_path), fingerprint(map_path),
        0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF, Hex2000Source.NOT_USED, None,
    )

    def operation(name):
        def run(ctx, request):
            calls.append((name, ctx, request))
            if name == "program":
                ctx.progress(ProgressEvent(name, ctx.target.name, "PROGRAM_DATA", "programmed", 8, 8, 8, cancellation_supported=True))
            return OperationResult(True, name, ctx.target.name, name.upper(), {})
        return run

    kwargs = {
        "app_resource_provider": Provider(service_path, map_path),
        "prepare_service_operation": lambda *_a, **_kw: replace(service),
        "erase_flash_image_area_operation": operation("erase_area"),
        "erase_sector_mask_operation": operation("erase_mask"),
        "program_flash_operation": operation("program"),
        "verify_flash_operation": operation("verify"),
    }
    kwargs.update(overrides)
    backend = RuntimeBackend(**kwargs)
    backend._session = object()
    backend._target = CPU1_PROFILE
    backend._connection_info = ConnectionInfo("connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu1")
    backend._configuration_revision = 2
    backend._program_image_revisions[RuntimeCpuId.CPU1] = 1
    backend._prepared_advanced_flash_images["cpu1"] = (image, image_summary)
    backend._flash_service_resource_state = FlashServiceResourceState(
        3, "Provider", str(service_path), str(map_path),
        FlashServiceResourceStatus.READY, service_summary,
    )
    return backend, app_path, service_path, map_path


def erase(scope, mask=0):
    return EraseAdvancedFlashRequest(*IDENTITY, scope, mask)


def test_erase_scopes_call_only_the_selected_public_operation(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    required = backend.execute("required", erase(AdvancedFlashEraseScope.REQUIRED_APP_SECTORS), object(), None)
    entire = backend.execute("entire", erase(AdvancedFlashEraseScope.ENTIRE_APPLICATION_REGION), object(), None)
    custom = backend.execute("custom", erase(AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, 0x6), object(), None)

    assert [item[0] for item in calls] == ["erase_area", "erase_mask", "erase_mask"]
    assert isinstance(calls[0][2], EraseFlashImageAreaRequest)
    assert isinstance(calls[1][2], EraseSectorMaskRequest)
    assert calls[1][2].sector_mask == CPU1_PROFILE.memory_map.flash.allowed_erase_mask
    assert calls[2][2].sector_mask == 0x6
    assert required.payload.erase_sector_mask == 0x2
    assert entire.payload.erase_sector_mask == CPU1_PROFILE.memory_map.flash.allowed_erase_mask
    assert custom.payload.erase_sector_mask == 0x6


@pytest.mark.parametrize("mask", [0x1, 1 << 20])
def test_forbidden_custom_masks_are_rejected_before_operation(tmp_path, mask) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    result = backend.execute(
        "erase", erase(AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, mask), object(), None
    )
    assert result.status is TaskFinalStatus.FAILED
    assert result.error.code == "FORBIDDEN_SECTOR"
    assert calls == []


def test_program_and_verify_are_independent_and_materialize_distinct_contexts(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    cancellation = object()
    events = []
    program = backend.execute("program", ProgramAdvancedFlashRequest(*IDENTITY), cancellation, events.append)
    verify = backend.execute("verify", VerifyAdvancedFlashRequest(*IDENTITY), cancellation, events.append)

    assert [item[0] for item in calls] == ["program", "verify"]
    assert isinstance(calls[0][2], ProgramFlashImageRequest)
    assert isinstance(calls[1][2], VerifyFlashImageRequest)
    assert calls[0][1].service is not calls[1][1].service
    assert calls[0][1].cancellation is cancellation
    assert any(event.step_state is TaskStepState.PROGRESS for event in events)
    updates = [event for event in events if event.step_state is TaskStepState.PROGRESS]
    assert all(
        update.progress_mode is ProgressMode.INDETERMINATE
        and update.current is None
        and update.total is None
        for update in updates
    )
    assert program.status is verify.status is TaskFinalStatus.SUCCEEDED
    assert program.completion_action is verify.completion_action is TaskCompletionAction.NONE
    assert isinstance(program.payload, AdvancedFlashOperationSnapshot)
    assert program.payload.operation_result_data["operation"] == "program"


def test_flash_operation_materializes_service_once_per_task(tmp_path) -> None:
    backend, *_ = populated_backend(tmp_path, [])
    materialized = []
    original = backend._prepare_service_operation

    def prepare(*args, **kwargs):
        value = original(*args, **kwargs)
        materialized.append(value)
        return value

    backend._prepare_service_operation = prepare
    assert backend.execute("one", ProgramAdvancedFlashRequest(*IDENTITY), None, None).status is TaskFinalStatus.SUCCEEDED
    assert len(materialized) == 1
    assert all(not isinstance(value, PreparedServiceImage) for value in vars(backend).values())


def test_clean_verify_success_creates_current_credential(tmp_path) -> None:
    backend, *_ = populated_backend(tmp_path, [])
    result = backend.execute("verify", VerifyAdvancedFlashRequest(*IDENTITY), object(), None)
    credential = backend.clean_verify_credential
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert isinstance(credential, CleanVerifyCredential)
    assert credential.connection_id == "connection"
    assert credential.image_selection_revision == 1
    assert credential.entry_point == 0x082000
    assert credential.image_crc32 == 0x1234


@pytest.mark.parametrize(
    "completion",
    [OperationCompletion.FAILED, OperationCompletion.CANCELLED, OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST],
)
def test_nonclean_verify_creates_no_credential(tmp_path, completion) -> None:
    cancellation = OperationCancellationInfo("VERIFY", 0, 8, True, False, False)

    def verify(ctx, request):
        if completion is OperationCompletion.FAILED:
            return OperationResult(
                False, "verify", ctx.target.name, "VERIFY", {},
                error=OperationErrorInfo("VERIFY_FAILED", "failed", "VERIFY"),
            )
        return OperationResult(
            completion is OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
            "verify", ctx.target.name, "VERIFY", {}, completion=completion,
            cancellation=cancellation,
        )

    backend, *_ = populated_backend(tmp_path, [], verify_flash_operation=verify)
    backend.execute("verify", VerifyAdvancedFlashRequest(*IDENTITY), object(), None)
    assert backend.clean_verify_credential is None


def test_verify_result_identity_mismatch_creates_no_credential(tmp_path) -> None:
    def verify(ctx, request):
        return OperationResult(
            True, "verify", ctx.target.name, "VERIFY_END", {"total_words": 16}
        )

    backend, *_ = populated_backend(tmp_path, [], verify_flash_operation=verify)
    backend.execute("verify", VerifyAdvancedFlashRequest(*IDENTITY), object(), None)
    assert backend.clean_verify_credential is None


def test_valid_mutating_flash_start_clears_credential_but_rejected_request_does_not(tmp_path) -> None:
    backend, *_ = populated_backend(tmp_path, [])
    backend.execute("verify", VerifyAdvancedFlashRequest(*IDENTITY), object(), None)
    credential = backend.clean_verify_credential
    assert credential is not None
    rejected = backend.execute(
        "stale", ProgramAdvancedFlashRequest("old", "cpu1", 1, 2, 3, 2), object(), None
    )
    assert rejected.error.code == "STALE_CONNECTION"
    assert backend.clean_verify_credential is credential
    backend.execute("program", ProgramAdvancedFlashRequest(*IDENTITY), object(), None)
    assert backend.clean_verify_credential is None


def test_image_and_tool_invalidation_clear_credential_but_service_stale_does_not(tmp_path) -> None:
    backend, *_ = populated_backend(tmp_path, [])
    backend.execute("verify", VerifyAdvancedFlashRequest(*IDENTITY), object(), None)
    credential = backend.clean_verify_credential
    service_path = Path(backend.flash_service_resource_state.image_path)
    service_path.write_text("changed service")
    result = backend.execute("changed", ProgramAdvancedFlashRequest(*IDENTITY), None, None)
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"
    assert backend.clean_verify_credential is credential
    backend.set_program_image_path("cpu1", str(tmp_path / "new.txt"))
    assert backend.clean_verify_credential is None

    backend, *_ = populated_backend(tmp_path, [])
    backend.execute("verify", VerifyAdvancedFlashRequest(*IDENTITY), object(), None)
    backend.set_image_tool_paths("new-hex2000", "new-temp")
    assert backend.clean_verify_credential is None


def test_stale_identities_and_changed_sources_clear_only_affected_cache(tmp_path) -> None:
    calls = []
    backend, app_path, service_path, _map_path = populated_backend(tmp_path, calls)
    assert backend.execute("old", ProgramAdvancedFlashRequest("old", "cpu1", 1, 2, 3, 2), None, None).error.code == "STALE_CONNECTION"
    assert backend.execute("revision", ProgramAdvancedFlashRequest("connection", "cpu1", 0, 2, 3, 2), None, None).error.code == "STALE_IMAGE_CONFIGURATION"

    service_state = backend.flash_service_resource_state
    app_path.write_text("changed app")
    assert backend.execute("changed", ProgramAdvancedFlashRequest(*IDENTITY), None, None).error.code == "IMAGE_CHANGED"
    assert backend.prepared_advanced_flash_image_cache("cpu1") is None
    assert backend.flash_service_resource_state == service_state

    backend, _app_path, service_path, _map_path = populated_backend(tmp_path, calls)
    image_cache = backend.prepared_advanced_flash_image_cache("cpu1")
    service_path.write_text("changed service")
    assert backend.execute("changed-service", ProgramAdvancedFlashRequest(*IDENTITY), None, None).error.code == "SERVICE_RESOURCE_CHANGED"
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.STALE
    assert backend.prepared_advanced_flash_image_cache("cpu1") == image_cache


def test_same_path_service_map_change_rejects_before_flash_operation(tmp_path) -> None:
    calls = []
    backend, _app, _service, map_path = populated_backend(tmp_path, calls)
    map_path.write_text("changed map")
    result = backend.execute("changed-map", ProgramAdvancedFlashRequest(*IDENTITY), None, None)
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.STALE
    assert calls == []


def test_same_path_service_image_change_rejects_before_flash_operation(tmp_path) -> None:
    calls = []
    backend, _app, service_path, _map = populated_backend(tmp_path, calls)
    service_path.write_text("changed image")
    result = backend.execute("changed-image", ProgramAdvancedFlashRequest(*IDENTITY), None, None)
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.STALE
    assert calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("descriptor_address", 0x11000), ("api_table_address", 0x11020), ("crc_patch_address", 0x11030)],
)
def test_changed_service_symbol_address_rejects_before_flash_operation(tmp_path, field, value) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    original = backend._prepare_service_operation(None)
    backend._prepare_service_operation = lambda *_a, **_kw: replace(original, **{field: value})
    result = backend.execute("changed-symbol", ProgramAdvancedFlashRequest(*IDENTITY), None, None)
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"
    assert calls == []


def test_cpu2_and_missing_capabilities_are_rejected_without_invocation(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    forged = ProgramAdvancedFlashRequest(*IDENTITY)
    object.__setattr__(forged, "target_key", "cpu2")
    assert backend.execute("cpu2", forged, None, None).error.code == "UNSUPPORTED_OPERATION"

    backend._target = CPU2_PROFILE
    backend._connection_info = ConnectionInfo("connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu2")
    mismatch = ProgramAdvancedFlashRequest(*IDENTITY)
    assert backend.execute("target", mismatch, None, None).error.code == "STALE_TARGET"
    assert calls == []


def test_missing_ram_check_crc_is_rejected_before_operation(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    backend._target = replace(
        CPU1_PROFILE,
        command_set=replace(CPU1_PROFILE.command_set, ram_check_crc=None),
    )
    result = backend.execute("program", ProgramAdvancedFlashRequest(*IDENTITY), None, None)
    assert result.error.code == "UNSUPPORTED_OPERATION"
    assert calls == []


def test_cancellation_outcomes_and_cleanup_disposition_are_preserved(tmp_path) -> None:
    cancellation = OperationCancellationInfo("PROGRAM_END", 8, 8, True, False, False, recovery_action="RESTART_PROGRAM")

    def completed(ctx, request):
        return OperationResult(
            True, "program_flash_image", ctx.target.name, "PROGRAM_END", {},
            completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
            cancellation=cancellation,
        )

    backend, *_ = populated_backend(tmp_path, [], program_flash_operation=completed)
    result = backend.execute("program", ProgramAdvancedFlashRequest(*IDENTITY), object(), None)
    assert result.status is TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST
    assert all(not isinstance(value, PreparedServiceImage) for value in vars(backend).values())

    uncertain = OperationCancellationInfo("PROGRAM_DATA", 4, 8, False, True, True, recovery_action="RECONNECT_ERASE_AND_RESTART_PROGRAM")

    def failed(ctx, request):
        return OperationResult(
            False, "program_flash_image", ctx.target.name, "PROGRAM_DATA", {},
            error=OperationErrorInfo("CANCELLATION_CLEANUP_FAILED", "cleanup", "PROGRAM_DATA", True),
            cancellation=uncertain,
        )

    backend._program_flash_operation = failed
    failed_result = backend.execute("failed", ProgramAdvancedFlashRequest(*IDENTITY), object(), None)
    assert failed_result.error.disposition is ErrorDisposition.ASK_DISCONNECT


@pytest.mark.parametrize(
    ("request_type", "operation_name", "transfer_stage"),
    [
        (ProgramAdvancedFlashRequest, "program_flash_image", "PROGRAM_DATA"),
        (VerifyAdvancedFlashRequest, "verify_flash_image", "VERIFY_DATA"),
    ],
)
def test_real_controller_accepts_restarted_flash_progress(
    tmp_path, request_type, operation_name, transfer_stage
) -> None:
    def operation(ctx, request):
        ctx.progress(
            ProgressEvent(
                "ensure_service_attached",
                ctx.target.name,
                "RAM_LOAD_SERVICE",
                "service load",
                32,
                64,
                16,
                {"phase": "service"},
                True,
            )
        )
        ctx.progress(
            ProgressEvent(
                operation_name,
                ctx.target.name,
                transfer_stage,
                "flash transfer",
                8,
                128,
                8,
                {"phase": "flash"},
                True,
            )
        )
        return OperationResult(True, operation_name, ctx.target.name, transfer_stage, {})

    override = (
        {"program_flash_operation": operation}
        if request_type is ProgramAdvancedFlashRequest
        else {"verify_flash_operation": operation}
    )
    backend, *_ = populated_backend(tmp_path, [], **override)
    controller = GuiController(backend, backend)
    controller._snapshot = RuntimeSnapshot(
        RuntimeState.CONNECTED,
        connection_info=backend.connection_info,
        active_target_key="cpu1",
    )
    updates = []
    results = []
    controller.taskProgressed.connect(updates.append)
    controller.taskFinished.connect(results.append)
    assert controller.request_task(request_type(*IDENTITY)).accepted

    app = QApplication.instance() or QApplication([])
    deadline = monotonic() + 2
    while controller.snapshot.active_task_id is not None and monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)

    progress = [update for update in updates if update.step_state is TaskStepState.PROGRESS]
    assert [update.stage for update in progress] == ["RAM_LOAD_SERVICE", transfer_stage]
    assert all(update.progress_mode is ProgressMode.INDETERMINATE for update in progress)
    assert all(update.current is None and update.total is None for update in progress)
    assert [update.raw_event.details["phase"] for update in progress] == ["service", "flash"]
    assert [update.details["operation"] for update in progress] == [
        "ensure_service_attached",
        operation_name,
    ]
    assert [update.details["chunk_words"] for update in progress] == [16, 8]
    assert [update.details["operation_details"]["phase"] for update in progress] == [
        "service",
        "flash",
    ]
    assert all(update.details["cancellation_supported"] for update in progress)
    assert controller.snapshot.state is RuntimeState.CONNECTED
    assert controller.snapshot.last_error is None
    assert results[-1].status is TaskFinalStatus.SUCCEEDED
