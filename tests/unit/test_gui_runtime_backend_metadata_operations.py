from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
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
    ConnectionGeneration, DataFreshness, FlashImageSummary, ImageParseStatus, RuntimeCpuId,
    TargetResourceState, VerifyEvidence,
)
from bootloader_upgrade_tool.gui.runtime_v2_events import ConnectionOpened, MetadataReadSucceeded
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataStatusSnapshot
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

    current_raw = _metadata()
    raw = readback or _metadata(attempts=2, confirmed=1)
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
    backend._runtime_v2_dispatcher.dispatch(ConnectionOpened(backend._connection_info))
    status_result = OperationResult(
        True, "get_metadata_summary", "cpu1", "GET_METADATA_SUMMARY", asdict(current_raw)
    )
    metadata_snapshot = MetadataStatusSnapshot(
        "connection", "cpu1", status_result, current_raw, True, True, True,
        current_raw.boot_attempt_count > 0, bool(current_raw.app_confirmed), False,
        LoadedImageMatch.MATCH, False,
    )
    backend._runtime_v2_dispatcher.dispatch(
        MetadataReadSucceeded(
            RuntimeCpuId.CPU1, backend.connection_generation, metadata_snapshot
        )
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
            verify_evidence=VerifyEvidence(
                RuntimeCpuId.CPU1,
                backend.connection_generation,
                image.identity,
                "verify",
            ),
        ),
    )
    backend._flash_service_resource_state = FlashServiceResourceState(
        3, "Provider", str(service_path), str(map_path),
        FlashServiceResourceStatus.READY, service_summary,
    )
    return backend, image, service, app_path, service_path, map_path


def metadata_request(backend, request_type, **values):
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    fields = {
        "connection_id": "connection",
        "target_key": "cpu1",
        "service_configuration_revision": backend.service_configuration_revision,
        "service_tool_configuration_revision": backend.configuration_revision,
        "expected_connection_generation": backend.connection_generation,
        "expected_service_summary": backend.flash_service_resource_state.summary,
        "expected_metadata_snapshot": (
            None
            if request_type is WriteAdvancedImageValidRequest
            else backend.runtime_v2_snapshot.metadata_state.value
        ),
    }
    if request_type is WriteAdvancedImageValidRequest:
        fields.update(
            image_source_path=resource.program_image_path,
            image_selection_revision=backend.program_image_revision("cpu1"),
            image_tool_configuration_revision=backend.configuration_revision,
            expected_image_identity=resource.program_image_summary.identity,
            expected_effective_sector_mask=resource.program_image_summary.sector_mask,
            expected_verify_evidence=resource.verify_evidence,
        )
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
    profile = replace(CPU1_PROFILE, name="Captured metadata profile")
    backend._target = profile
    backend._target_profile_resolver = lambda _key: pytest.fail("Registry profile queried")
    service_profiles = []
    prepare_service = backend._prepare_service_operation
    backend._prepare_service_operation = lambda *args, **kwargs: (
        service_profiles.append(kwargs["target"]) or prepare_service(*args, **kwargs)
    )

    def prepare(*_args, **kwargs):
        value = replace(image)
        materialized.append((value, kwargs["target"]))
        return value

    backend._prepare_flash_operation = prepare
    result = backend.execute(
        "image-valid",
        metadata_request(backend, WriteAdvancedImageValidRequest),
        None,
        None,
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(materialized) == 1
    assert calls[0][2].image is materialized[0][0]
    assert materialized[0][1] is profile
    assert service_profiles == [profile]


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
    assert children == []
    assert not root.exists()


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
    assert children == []
    assert not root.exists()


def test_each_metadata_request_calls_only_its_public_operation_and_one_readback(tmp_path) -> None:
    calls = []
    materialized = []
    request_types = (
        WriteAdvancedImageValidRequest,
        WriteAdvancedBootAttemptRequest,
        WriteAdvancedAppConfirmedRequest,
    )
    results = []
    for index, request_type in enumerate(request_types):
        case = tmp_path / str(index)
        case.mkdir()
        backend, image, *_ = _backend(case, calls)
        backend._prepare_flash_operation = lambda *_a, _image=image, **_kw: materialized.append(replace(_image)) or materialized[-1]
        results.append(backend.execute(str(index), metadata_request(backend, request_type), object(), None))
    assert [name for name, _ctx, _request in calls] == ["image_valid", "boot_attempt", "app_confirmed"]
    assert isinstance(calls[0][2], AppendImageValidRequest) and calls[0][2].image.identity == image.identity
    assert isinstance(calls[1][2], AppendBootAttemptRequest)
    assert isinstance(calls[2][2], AppendAppConfirmedRequest)
    assert len(materialized) == 1
    assert len({id(ctx.service) for _name, ctx, _request in calls}) == 3
    assert all(result.status is TaskFinalStatus.SUCCEEDED for result in results)
    assert all(isinstance(result.payload, AdvancedMetadataOperationSnapshot) for result in results)
    assert all(len(result.step_results) == 2 for result in results)


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


def test_image_valid_rejects_stale_evidence_before_operation(tmp_path) -> None:
    calls = []
    backend, *_ = _backend(tmp_path, calls)
    current = backend.target_resources[RuntimeCpuId.CPU1].verify_evidence
    stale = replace(current, connection_generation=ConnectionGeneration(current.connection_generation.value + 1))
    assert backend.execute(
        "stale",
        metadata_request(backend, WriteAdvancedImageValidRequest, expected_verify_evidence=stale),
        None,
        None,
    ).error.code == "VERIFY_EVIDENCE_REQUIRED"
    assert calls == []


def test_image_valid_rejects_missing_evidence_before_operation(tmp_path) -> None:
    calls = []
    backend, *_ = _backend(tmp_path, calls)
    current = backend.target_resources[RuntimeCpuId.CPU1].verify_evidence
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    backend._runtime_v2_store.replace_target_resource(
        RuntimeCpuId.CPU1, replace(resource, verify_evidence=None)
    )
    assert backend.execute(
        "missing",
        metadata_request(backend, WriteAdvancedImageValidRequest, expected_verify_evidence=current),
        None,
        None,
    ).error.code == "VERIFY_EVIDENCE_REQUIRED"
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


def test_completed_after_cancel_refresh_failure_preserves_primary_cancellation(tmp_path) -> None:
    cancellation = OperationCancellationInfo("METADATA_APPEND", 1, 1, True, False, False)

    def completed(ctx, request):
        return OperationResult(
            True, "append_boot_attempt", ctx.target.name, "METADATA_APPEND",
            {"written": True, "already_exists": False, "reason": None},
            completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
            cancellation=cancellation,
        )

    def failed_read(ctx):
        return OperationResult(
            False, "get_metadata_summary", ctx.target.name, "GET_METADATA_SUMMARY", {},
            error=OperationErrorInfo("READ_FAILED", "lost", "GET_METADATA_SUMMARY"),
        )

    backend, *_ = _backend(
        tmp_path, [], append_boot_attempt_operation=completed,
        metadata_operation=failed_read,
    )
    result = backend.execute(
        "task", metadata_request(backend, WriteAdvancedBootAttemptRequest), object(), None
    )
    assert result.status is TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST
    assert result.cancel_requested and result.error is None
    assert result.warning.code == "METADATA_REFRESH_FAILED"
    assert result.warning.details["primary_cancel_requested"] is True
    assert result.warning.details["primary_cancellation"]["stage"] == "METADATA_APPEND"


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


def test_readback_failure_keeps_primary_success_and_warns(tmp_path) -> None:
    def failed_read(ctx):
        return OperationResult(
            False, "get_metadata_summary", ctx.target.name, "GET_METADATA_SUMMARY", {},
            error=OperationErrorInfo("PROTOCOL_ERROR", "lost", "GET_METADATA_SUMMARY", True),
        )

    backend, *_ = _backend(tmp_path, [], metadata_operation=failed_read)
    old_snapshot = backend.runtime_v2_snapshot.metadata_state.value
    result = backend.execute("task", metadata_request(backend, WriteAdvancedBootAttemptRequest), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert result.error is None
    assert result.warning.code == "METADATA_REFRESH_FAILED"
    assert result.warning.details["primary_operation"] == "boot_attempt"
    assert result.warning.details["refresh_error_code"] == "PROTOCOL_ERROR"
    assert result.warning.details["metadata_freshness"] == "stale"
    assert result.warning.details["primary_retry_performed"] is False
    assert len(result.step_results) == 2
    assert result.payload.primary_result.summary["written"] is True
    assert result.payload.readback_result.error.code == "PROTOCOL_ERROR"
    assert backend.runtime_v2_snapshot.metadata_state.freshness is DataFreshness.STALE
    assert backend.runtime_v2_snapshot.metadata_state.read_error.code == "PROTOCOL_ERROR"
    assert backend.runtime_v2_snapshot.metadata_state.value == old_snapshot


def test_claimed_write_mismatch_is_ask_disconnect_and_publishes_fresh_readback(tmp_path) -> None:
    backend, *_ = _backend(tmp_path, [], readback=_metadata(attempts=0))
    result = backend.execute("task", metadata_request(backend, WriteAdvancedBootAttemptRequest), None, None)
    assert result.error.code == "METADATA_READBACK_MISMATCH"
    assert result.error.disposition is ErrorDisposition.ASK_DISCONNECT
    assert backend.metadata_status_snapshot == result.payload.metadata_snapshot


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


def test_image_valid_existing_different_image_is_a_verified_noop(tmp_path) -> None:
    def already_exists(ctx, request):
        return OperationResult(
            True, "append_image_valid", ctx.target.name, "READ_METADATA_SUMMARY",
            {"written": False, "already_exists": True, "reason": "IMAGE_VALID_ALREADY_EXISTS"},
        )

    backend, *_ = _backend(
        tmp_path, [], readback=_metadata(entry=0x084000, crc=0x9999),
        append_image_valid_operation=already_exists,
    )
    result = backend.execute(
        "task", metadata_request(backend, WriteAdvancedImageValidRequest), None, None
    )
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert result.payload.primary_result.summary["written"] is False


def test_stale_generation_service_and_metadata_fail_before_materialization(tmp_path, monkeypatch) -> None:
    for change, code in (
        ("generation", "STALE_CONNECTION"),
        ("service", "STALE_SERVICE_CONFIGURATION"),
        ("metadata", "STALE_METADATA_CONFIGURATION"),
    ):
        calls = []
        case_path = tmp_path / change
        case_path.mkdir()
        backend, *_ = _backend(case_path, calls)
        request = metadata_request(backend, WriteAdvancedBootAttemptRequest)
        if change == "generation":
            request = replace(
                request,
                expected_connection_generation=request.expected_connection_generation.next(),
            )
        elif change == "service":
            request = replace(
                request,
                expected_service_summary=replace(
                    request.expected_service_summary, descriptor_address=0x11000
                ),
            )
        else:
            request = replace(
                request,
                expected_metadata_snapshot=replace(
                    request.expected_metadata_snapshot,
                    raw_metadata=replace(
                        request.expected_metadata_snapshot.raw_metadata,
                        boot_attempt_count=2,
                    ),
                ),
            )
        monkeypatch.setattr(backend, "_materialize_flash_app", lambda **_kwargs: pytest.fail("App materialized"))
        monkeypatch.setattr(backend, "_materialize_flash_service", lambda **_kwargs: pytest.fail("Service materialized"))
        result = backend.execute(change, request, None, None)
        assert result.error.code == code
        assert calls == []
