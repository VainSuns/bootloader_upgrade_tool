from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_flash_models import PreparedAdvancedFlashImageSummary
from bootloader_upgrade_tool.gui.advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
    CleanVerifyCredential,
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from bootloader_upgrade_tool.gui.flash_service_models import PreparedFlashServiceSummary
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, ErrorDisposition, ProgressMode, TaskFinalStatus, TaskStepState
from bootloader_upgrade_tool.images import ImageIdentity, PreparedFlashImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import (
    AppendAppConfirmedRequest,
    AppendBootAttemptRequest,
    AppendImageValidRequest,
    OperationCancellationInfo,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
    ProgressEvent,
)
from bootloader_upgrade_tool.protocol.models import DeviceInfo, MetadataSummary
from bootloader_upgrade_tool.targets import CPU1_PROFILE


IDENTITY = ("connection", "cpu1", 1, 2, 3, 2)


def _fingerprint(path: Path) -> SourceFileFingerprint:
    return SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)


def _metadata(*, attempts=1, confirmed=1, entry=0x082000, crc=0x1234):
    return MetadataSummary(
        1, 1, 1, attempts, confirmed, 3, 1, 0, 0, 0,
        entry, crc, 1, 1, 0, 0, 1, 1, 8, 0x377D, 1,
    )


def _backend(tmp_path: Path, calls: list, *, readback=None, **overrides):
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
    image_summary = PreparedAdvancedFlashImageSummary(
        "cpu1", str(app_path), 1, 2, ImageSourceKind.TXT, _fingerprint(app_path),
        0x082000, 8, 0x1234, 0x082008, 0x2, 0x2, Hex2000Source.NOT_USED, None,
    )
    service = PreparedServiceImage(firmware, 0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF)
    service_summary = PreparedFlashServiceSummary(
        "cpu1", str(service_path), str(map_path), "descriptor", 3, 2,
        ImageSourceKind.TXT, _fingerprint(service_path), _fingerprint(map_path),
        0x10000, 0x10020, 0x10030, 8, 0x5678, Hex2000Source.NOT_USED, None,
    )

    def append(name):
        def run(ctx, request):
            calls.append((name, ctx, request))
            ctx.progress(ProgressEvent(name, ctx.target.name, "METADATA_APPEND", "done", 1, 1, 1))
            return OperationResult(
                True, name, ctx.target.name, "METADATA_APPEND",
                {"written": True, "already_exists": False, "reason": None},
            )
        return run

    raw = readback or _metadata()
    metadata_operation = overrides.pop(
        "metadata_operation",
        lambda ctx: OperationResult(True, "get_metadata_summary", ctx.target.name, "GET_METADATA_SUMMARY", asdict(raw)),
    )
    backend = RuntimeBackend(
        metadata_operation=metadata_operation,
        append_image_valid_operation=overrides.pop("append_image_valid_operation", append("image_valid")),
        append_boot_attempt_operation=overrides.pop("append_boot_attempt_operation", append("boot_attempt")),
        append_app_confirmed_operation=overrides.pop("append_app_confirmed_operation", append("app_confirmed")),
        **overrides,
    )
    backend._session = object()
    backend._target = CPU1_PROFILE
    backend._device_info = DeviceInfo(0x377D, 1, 1, 0, 0, 1, 0, 64, 56, 0, 0)
    backend._connection_info = ConnectionInfo(
        "connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu1"
    )
    backend._configuration_revision = 2
    backend._advanced_flash_selection_revisions["cpu1"] = 1
    backend._service_configuration_revision = 3
    backend._prepared_advanced_flash_images["cpu1"] = (image, image_summary)
    backend._prepared_service_image = service
    backend._prepared_service_summary = service_summary
    backend._clean_verify_credential = CleanVerifyCredential(
        "token", "connection", "cpu1", 1, 2, image_summary.source_fingerprint,
        0x082000, 8, 0x1234, 0x082008,
    )
    return backend, image, service, app_path, service_path, map_path


def test_each_metadata_request_calls_only_its_public_operation_and_one_readback(tmp_path) -> None:
    calls = []
    backend, image, service, *_ = _backend(tmp_path, calls)
    requests = (
        WriteAdvancedImageValidRequest(*IDENTITY, "token"),
        WriteAdvancedBootAttemptRequest(*IDENTITY),
        WriteAdvancedAppConfirmedRequest(*IDENTITY),
    )
    results = [backend.execute(str(index), request, object(), None) for index, request in enumerate(requests)]
    assert [name for name, _ctx, _request in calls] == ["image_valid", "boot_attempt", "app_confirmed"]
    assert isinstance(calls[0][2], AppendImageValidRequest) and calls[0][2].image is image
    assert isinstance(calls[1][2], AppendBootAttemptRequest) and calls[1][2].image_identity is image.identity
    assert isinstance(calls[2][2], AppendAppConfirmedRequest) and calls[2][2].image_identity is image.identity
    assert all(ctx.service is service for _name, ctx, _request in calls)
    assert all(result.status is TaskFinalStatus.SUCCEEDED for result in results)
    assert all(isinstance(result.payload, AdvancedMetadataOperationSnapshot) for result in results)
    assert all(len(result.step_results) == 2 for result in results)
    assert backend.metadata_status_snapshot == results[-1].payload.metadata_snapshot


def test_image_valid_rejects_unknown_or_stale_credential_before_operation(tmp_path) -> None:
    calls = []
    backend, *_ = _backend(tmp_path, calls)
    assert backend.execute(
        "unknown", WriteAdvancedImageValidRequest(*IDENTITY, "unknown"), None, None
    ).error.code == "CLEAN_VERIFY_REQUIRED"
    backend._clean_verify_credential = None
    assert backend.execute(
        "missing", WriteAdvancedImageValidRequest(*IDENTITY, "token"), None, None
    ).error.code == "CLEAN_VERIFY_REQUIRED"
    assert calls == []


def test_progress_is_indeterminate_and_readback_is_second_step(tmp_path) -> None:
    calls = []
    backend, *_ = _backend(tmp_path, calls)
    updates = []
    backend.execute("task", WriteAdvancedBootAttemptRequest(*IDENTITY), object(), updates.append)
    operation_progress = [item for item in updates if item.step_state is TaskStepState.PROGRESS]
    assert operation_progress
    assert all(
        item.progress_mode is ProgressMode.INDETERMINATE
        and item.current is None and item.total is None
        for item in operation_progress
    )
    assert [item.step_id for item in updates if item.step_state is TaskStepState.STARTED] == [
        "write_boot_attempt", "read_metadata_summary"
    ]


def test_completed_after_cancel_still_reads_back_and_preserves_status(tmp_path) -> None:
    cancellation = OperationCancellationInfo("METADATA_APPEND", 1, 1, True, False, False)

    def completed(ctx, request):
        return OperationResult(
            True, "append_boot_attempt", ctx.target.name, "METADATA_APPEND",
            {"written": True, "already_exists": False, "reason": None},
            completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
            cancellation=cancellation,
        )

    backend, *_ = _backend(tmp_path, [], append_boot_attempt_operation=completed)
    result = backend.execute("task", WriteAdvancedBootAttemptRequest(*IDENTITY), object(), None)
    assert result.status is TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST
    assert len(result.step_results) == 2
    assert "readback also completed" in result.message


def test_cancelled_or_failed_append_does_not_read_back(tmp_path) -> None:
    reads = []
    cancellation = OperationCancellationInfo("METADATA_APPEND", 0, 1, True, False, False)

    def cancelled(ctx, request):
        return OperationResult(
            False, "append", ctx.target.name, "METADATA_APPEND", {},
            completion=OperationCompletion.CANCELLED, cancellation=cancellation,
        )

    backend, *_ = _backend(
        tmp_path, [], append_boot_attempt_operation=cancelled,
        metadata_operation=lambda ctx: reads.append(ctx),
    )
    result = backend.execute("cancel", WriteAdvancedBootAttemptRequest(*IDENTITY), object(), None)
    assert result.status is TaskFinalStatus.CANCELLED and reads == []


def test_readback_failure_retains_primary_and_protocol_error_asks_disconnect(tmp_path) -> None:
    def failed_read(ctx):
        return OperationResult(
            False, "get_metadata_summary", ctx.target.name, "GET_METADATA_SUMMARY", {},
            error=OperationErrorInfo("PROTOCOL_ERROR", "lost", "GET_METADATA_SUMMARY", True),
        )

    backend, *_ = _backend(tmp_path, [], metadata_operation=failed_read)
    result = backend.execute("task", WriteAdvancedBootAttemptRequest(*IDENTITY), None, None)
    assert result.status is TaskFinalStatus.FAILED
    assert result.error.disposition is ErrorDisposition.ASK_DISCONNECT
    assert len(result.step_results) == 2
    assert result.payload.primary_result.summary["written"] is True
    assert result.payload.readback_result.error.code == "PROTOCOL_ERROR"


def test_claimed_write_mismatch_is_ask_disconnect_and_does_not_update_cache(tmp_path) -> None:
    backend, *_ = _backend(tmp_path, [], readback=_metadata(attempts=0))
    result = backend.execute("task", WriteAdvancedBootAttemptRequest(*IDENTITY), None, None)
    assert result.error.code == "METADATA_READBACK_MISMATCH"
    assert result.error.disposition is ErrorDisposition.ASK_DISCONNECT
    assert backend.metadata_status_snapshot is None


def test_business_guidance_is_preserved_with_successful_readback(tmp_path) -> None:
    def guidance(ctx, request):
        return OperationResult(
            True, "append_boot_attempt", ctx.target.name, "METADATA",
            {"written": False, "already_exists": False, "reason": "IMAGE_VALID_REQUIRED"},
        )

    backend, *_ = _backend(
        tmp_path, [], readback=_metadata(entry=0, crc=0), append_boot_attempt_operation=guidance
    )
    result = backend.execute("task", WriteAdvancedBootAttemptRequest(*IDENTITY), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert result.payload.primary_result.summary["reason"] == "IMAGE_VALID_REQUIRED"
