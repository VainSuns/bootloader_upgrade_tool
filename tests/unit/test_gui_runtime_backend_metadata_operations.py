from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
    CleanVerifyCredential,
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from bootloader_upgrade_tool.gui.flash_service_models import (
    DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
    FlashServiceResourceState,
    FlashServiceResourceStatus,
    PreparedFlashServiceSummary,
)
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    FlashImageSummary, ImageParseStatus, RuntimeCpuId, TargetResourceState,
)
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


IMAGE_IDENTITY = ImageIdentity(0x082000, 8, 0x1234, 0x082008)


class Provider:
    def __init__(self, image, map_file): self.image, self.map_file = image, map_file
    def flash_service_image_path(self): return self.image
    def flash_service_map_path(self): return self.map_file


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
        firmware, IMAGE_IDENTITY, 0x2
    )
    service = PreparedServiceImage(firmware, 0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF)
    service_summary = PreparedFlashServiceSummary(
        "cpu1", "Provider", str(service_path), str(map_path), DEFAULT_SERVICE_DESCRIPTOR_SYMBOL, 3, 2,
        ImageSourceKind.TXT, _fingerprint(service_path), _fingerprint(map_path),
        0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF, Hex2000Source.NOT_USED, None,
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
        app_resource_provider=Provider(service_path, map_path),
        prepare_service_operation=lambda *_a, **_kw: replace(service),
        prepare_flash_operation=lambda *_a, **_kw: replace(image),
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
        3, "Provider", str(service_path), str(map_path),
        FlashServiceResourceStatus.READY, service_summary,
    )
    backend._clean_verify_credential = CleanVerifyCredential(
        "token", "connection", "cpu1", 1, 2, _fingerprint(app_path),
        0x082000, 8, 0x1234, 0x082008,
    )
    return backend, image, service, app_path, service_path, map_path


def metadata_request(backend, request_type, **values):
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    fields = {
        "connection_id": "connection",
        "target_key": "cpu1",
        "image_source_path": resource.program_image_path,
        "image_selection_revision": backend.program_image_revision("cpu1"),
        "image_tool_configuration_revision": backend.configuration_revision,
        "expected_image_identity": resource.program_image_summary.identity,
        "expected_effective_sector_mask": resource.program_image_summary.sector_mask,
        "service_configuration_revision": backend.service_configuration_revision,
        "service_tool_configuration_revision": backend.configuration_revision,
    }
    fields.update(values)
    return request_type(**fields)


def _use_out_source(backend, app_path: Path, tmp_path: Path, prepare):
    out_path = app_path.with_suffix(".out")
    app_path.rename(out_path)
    tool = tmp_path / "hex2000.exe"
    tool.touch()
    root = tmp_path / "materializations"
    backend._hex2000_executable_path = str(tool)
    backend._sci8_temp_dir = str(root)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    backend._runtime_v2_store.replace_target_resource(
        RuntimeCpuId.CPU1,
        replace(resource, program_image_path=str(out_path)),
    )
    backend._prepare_flash_operation = prepare
    return root


def test_image_valid_materializes_app_once(tmp_path) -> None:
    calls = []
    backend, image, *_ = _backend(tmp_path, calls)
    materialized = []

    def prepare(*_args, **_kwargs):
        value = replace(image)
        materialized.append(value)
        return value

    backend._prepare_flash_operation = prepare
    result = backend.execute(
        "image-valid",
        metadata_request(backend, WriteAdvancedImageValidRequest, verification_token="token"),
        None,
        None,
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(materialized) == 1
    assert calls[0][2].image is materialized[0]


def test_out_metadata_workspace_cleanup(tmp_path) -> None:
    calls = []
    backend, image, _service, app_path, *_ = _backend(tmp_path, calls)
    children = []

    def prepare(*_args, **kwargs):
        sci8 = Path(kwargs["sci8_txt"])
        children.append(sci8.parent)
        return replace(image, generated_sci8_txt=str(sci8))

    root = _use_out_source(backend, app_path, tmp_path, prepare)
    result = backend.execute(
        "metadata", metadata_request(backend, WriteAdvancedBootAttemptRequest), None, None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(children) == 1 and not children[0].exists()
    assert list(root.iterdir()) == []


def test_out_metadata_failure_workspace_cleanup(tmp_path) -> None:
    def fail(ctx, request):
        return OperationResult(
            False,
            "append_boot_attempt",
            ctx.target.name,
            "METADATA_APPEND",
            {},
            error=OperationErrorInfo("WRITE_FAILED", "failed", "METADATA_APPEND"),
        )

    backend, image, _service, app_path, *_ = _backend(
        tmp_path, [], append_boot_attempt_operation=fail
    )
    children = []

    def prepare(*_args, **kwargs):
        sci8 = Path(kwargs["sci8_txt"])
        children.append(sci8.parent)
        return replace(image, generated_sci8_txt=str(sci8))

    root = _use_out_source(backend, app_path, tmp_path, prepare)
    result = backend.execute(
        "metadata", metadata_request(backend, WriteAdvancedBootAttemptRequest), None, None
    )

    assert result.status is TaskFinalStatus.FAILED
    assert len(children) == 1 and not children[0].exists()
    assert list(root.iterdir()) == []


def test_each_metadata_request_calls_only_its_public_operation_and_one_readback(tmp_path) -> None:
    calls = []
    backend, image, service, *_ = _backend(tmp_path, calls)
    materialized = []

    def prepare(*_args, **_kwargs):
        value = replace(image)
        materialized.append(value)
        return value

    backend._prepare_flash_operation = prepare
    requests = (
        metadata_request(backend, WriteAdvancedImageValidRequest, verification_token="token"),
        metadata_request(backend, WriteAdvancedBootAttemptRequest),
        metadata_request(backend, WriteAdvancedAppConfirmedRequest),
    )
    results = [backend.execute(str(index), request, object(), None) for index, request in enumerate(requests)]
    assert [name for name, _ctx, _request in calls] == ["image_valid", "boot_attempt", "app_confirmed"]
    assert isinstance(calls[0][2], AppendImageValidRequest) and calls[0][2].image.identity == image.identity
    assert isinstance(calls[1][2], AppendBootAttemptRequest) and calls[1][2].image_identity == image.identity
    assert isinstance(calls[2][2], AppendAppConfirmedRequest) and calls[2][2].image_identity == image.identity
    assert len(materialized) == 3
    assert len({id(value) for value in materialized}) == 3
    assert len({id(ctx.service) for _name, ctx, _request in calls}) == 3
    assert all(result.status is TaskFinalStatus.SUCCEEDED for result in results)
    assert all(isinstance(result.payload, AdvancedMetadataOperationSnapshot) for result in results)
    assert all(len(result.step_results) == 2 for result in results)
    assert backend.metadata_status_snapshot == results[-1].payload.metadata_snapshot


def test_metadata_operation_materializes_service_once_per_task(tmp_path) -> None:
    backend, *_ = _backend(tmp_path, [])
    materialized = []
    original = backend._prepare_service_operation

    def prepare(*args, **kwargs):
        value = original(*args, **kwargs)
        materialized.append(value)
        return value

    backend._prepare_service_operation = prepare
    result = backend.execute("task", metadata_request(backend, WriteAdvancedBootAttemptRequest), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(materialized) == 1
    assert all(not isinstance(value, PreparedServiceImage) for value in vars(backend).values())


def test_service_identity_mismatch_invokes_no_metadata_or_readback(tmp_path) -> None:
    calls = []
    reads = []
    backend, *_prefix, service_path, _map_path = _backend(
        tmp_path,
        calls,
        metadata_operation=lambda ctx: reads.append(ctx),
    )
    service_path.write_text("changed service")
    result = backend.execute("task", metadata_request(backend, WriteAdvancedBootAttemptRequest), None, None)
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"
    assert calls == [] and reads == []


def test_image_valid_rejects_unknown_or_stale_credential_before_operation(tmp_path) -> None:
    calls = []
    backend, *_ = _backend(tmp_path, calls)
    assert backend.execute(
        "unknown", metadata_request(backend, WriteAdvancedImageValidRequest, verification_token="unknown"), None, None
    ).error.code == "CLEAN_VERIFY_REQUIRED"
    backend._clean_verify_credential = None
    assert backend.execute(
        "missing", metadata_request(backend, WriteAdvancedImageValidRequest, verification_token="token"), None, None
    ).error.code == "CLEAN_VERIFY_REQUIRED"
    assert calls == []


def test_progress_is_indeterminate_and_readback_is_second_step(tmp_path) -> None:
    calls = []
    backend, *_ = _backend(tmp_path, calls)
    updates = []
    backend.execute("task", metadata_request(backend, WriteAdvancedBootAttemptRequest), object(), updates.append)
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
    result = backend.execute("task", metadata_request(backend, WriteAdvancedBootAttemptRequest), object(), None)
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
    result = backend.execute("cancel", metadata_request(backend, WriteAdvancedBootAttemptRequest), object(), None)
    assert result.status is TaskFinalStatus.CANCELLED and reads == []


def test_readback_failure_retains_primary_and_protocol_error_asks_disconnect(tmp_path) -> None:
    def failed_read(ctx):
        return OperationResult(
            False, "get_metadata_summary", ctx.target.name, "GET_METADATA_SUMMARY", {},
            error=OperationErrorInfo("PROTOCOL_ERROR", "lost", "GET_METADATA_SUMMARY", True),
        )

    backend, *_ = _backend(tmp_path, [], metadata_operation=failed_read)
    result = backend.execute("task", metadata_request(backend, WriteAdvancedBootAttemptRequest), None, None)
    assert result.status is TaskFinalStatus.FAILED
    assert result.error.disposition is ErrorDisposition.ASK_DISCONNECT
    assert len(result.step_results) == 2
    assert result.payload.primary_result.summary["written"] is True
    assert result.payload.readback_result.error.code == "PROTOCOL_ERROR"


def test_claimed_write_mismatch_is_ask_disconnect_and_does_not_update_cache(tmp_path) -> None:
    backend, *_ = _backend(tmp_path, [], readback=_metadata(attempts=0))
    result = backend.execute("task", metadata_request(backend, WriteAdvancedBootAttemptRequest), None, None)
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
    result = backend.execute("task", metadata_request(backend, WriteAdvancedBootAttemptRequest), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert result.payload.primary_result.summary["reason"] == "IMAGE_VALID_REQUIRED"
