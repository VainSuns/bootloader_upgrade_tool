from datetime import datetime, timezone
from pathlib import Path

import pytest

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_flash_models import PreparedAdvancedFlashImageSummary
from bootloader_upgrade_tool.gui.advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    AdvancedFlashOperationSnapshot,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
)
from bootloader_upgrade_tool.gui.flash_service_models import PreparedFlashServiceSummary
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, ErrorDisposition, TaskCompletionAction, TaskFinalStatus, TaskStepState
from bootloader_upgrade_tool.images import ImageIdentity, PreparedFlashImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import OperationCancellationInfo, OperationCompletion, OperationErrorInfo, OperationResult, ProgressEvent
from bootloader_upgrade_tool.operations.flash_ops import EraseFlashImageAreaRequest, EraseSectorMaskRequest, ProgramFlashImageRequest, VerifyFlashImageRequest
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


IDENTITY = ("connection", "cpu1", 1, 2, 3, 2)


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
        "cpu1", str(service_path), str(map_path), "descriptor", 3, 2,
        ImageSourceKind.TXT, fingerprint(service_path), fingerprint(map_path),
        0x10000, 0x10020, 0x10030, 8, 0x5678, Hex2000Source.NOT_USED, None,
    )

    def operation(name):
        def run(ctx, request):
            calls.append((name, ctx, request))
            if name == "program":
                ctx.progress(ProgressEvent(name, ctx.target.name, "PROGRAM_DATA", "programmed", 8, 8, 8, cancellation_supported=True))
            return OperationResult(True, name, ctx.target.name, name.upper(), {})
        return run

    kwargs = {
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
    backend._advanced_flash_selection_revisions["cpu1"] = 1
    backend._service_configuration_revision = 3
    backend._prepared_advanced_flash_images["cpu1"] = (image, image_summary)
    backend._prepared_service_image = service
    backend._prepared_service_summary = service_summary
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


def test_program_and_verify_are_independent_and_receive_cached_context(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    cancellation = object()
    events = []
    program = backend.execute("program", ProgramAdvancedFlashRequest(*IDENTITY), cancellation, events.append)
    verify = backend.execute("verify", VerifyAdvancedFlashRequest(*IDENTITY), cancellation, events.append)

    assert [item[0] for item in calls] == ["program", "verify"]
    assert isinstance(calls[0][2], ProgramFlashImageRequest)
    assert isinstance(calls[1][2], VerifyFlashImageRequest)
    assert calls[0][1].service is backend.prepared_service_image
    assert calls[0][1].cancellation is cancellation
    assert any(event.step_state is TaskStepState.PROGRESS for event in events)
    assert program.status is verify.status is TaskFinalStatus.SUCCEEDED
    assert program.completion_action is verify.completion_action is TaskCompletionAction.NONE
    assert isinstance(program.payload, AdvancedFlashOperationSnapshot)


def test_stale_identities_and_changed_sources_clear_only_affected_cache(tmp_path) -> None:
    calls = []
    backend, app_path, service_path, _map_path = populated_backend(tmp_path, calls)
    assert backend.execute("old", ProgramAdvancedFlashRequest("old", "cpu1", 1, 2, 3, 2), None, None).error.code == "STALE_CONNECTION"
    assert backend.execute("revision", ProgramAdvancedFlashRequest("connection", "cpu1", 0, 2, 3, 2), None, None).error.code == "STALE_IMAGE_CONFIGURATION"

    service_cache = backend.prepared_service_image_cache
    app_path.write_text("changed app")
    assert backend.execute("changed", ProgramAdvancedFlashRequest(*IDENTITY), None, None).error.code == "IMAGE_CHANGED"
    assert backend.prepared_advanced_flash_image_cache("cpu1") is None
    assert backend.prepared_service_image_cache == service_cache

    backend, _app_path, service_path, _map_path = populated_backend(tmp_path, calls)
    image_cache = backend.prepared_advanced_flash_image_cache("cpu1")
    service_path.write_text("changed service")
    assert backend.execute("changed-service", ProgramAdvancedFlashRequest(*IDENTITY), None, None).error.code == "SERVICE_CHANGED"
    assert backend.prepared_service_image_cache is None
    assert backend.prepared_advanced_flash_image_cache("cpu1") == image_cache


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
