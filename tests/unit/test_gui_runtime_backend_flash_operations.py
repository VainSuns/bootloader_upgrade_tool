from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import pytest
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    AdvancedFlashOperationSnapshot,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
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
    VerifyEvidence,
)
from bootloader_upgrade_tool.gui.runtime_v2_events import (
    ConnectionOpened, OperationStarted, OperationSucceeded, ProgramImageChanged,
    RuntimeOperationType,
)
from bootloader_upgrade_tool.gui.controller import GuiController
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, ErrorDisposition, ProgressMode, RuntimeSnapshot, RuntimeState, TaskCompletionAction, TaskFinalStatus, TaskStepState
from bootloader_upgrade_tool.images import ImageIdentity, PreparedFlashImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import OperationCancellationInfo, OperationCompletion, OperationErrorInfo, OperationResult, ProgressEvent
from bootloader_upgrade_tool.operations.flash_ops import EraseFlashImageAreaRequest, EraseSectorMaskRequest, ProgramFlashImageRequest, VerifyFlashImageRequest
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


IMAGE_IDENTITY = ImageIdentity(0x082000, 8, 0x1234, 0x082008)


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
    image = PreparedFlashImage(firmware, IMAGE_IDENTITY, 0x2)
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
        "prepare_flash_operation": lambda *_a, **_kw: replace(image),
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
    backend._runtime_v2_dispatcher.dispatch(ConnectionOpened(backend._connection_info))
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
    return backend, app_path, service_path, map_path


def flash_request(backend, request_type, **values):
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


def erase(backend, scope, mask=0):
    return flash_request(
        backend,
        EraseAdvancedFlashRequest,
        erase_scope=scope,
        custom_sector_mask=mask,
    )


@pytest.mark.parametrize(
    ("request_factory", "event_type", "has_identity", "expected_order"),
    (
        (
            lambda backend: erase(backend, AdvancedFlashEraseScope.REQUIRED_APP_SECTORS),
            RuntimeOperationType.ERASE,
            True,
            ["event", "app", "service", "operation"],
        ),
        (
            lambda backend: flash_request(backend, ProgramAdvancedFlashRequest),
            RuntimeOperationType.PROGRAM,
            True,
            ["event", "app", "service", "operation"],
        ),
        (
            lambda backend: flash_request(backend, VerifyAdvancedFlashRequest),
            RuntimeOperationType.VERIFY,
            True,
            ["event", "app", "service", "operation"],
        ),
        (
            lambda backend: erase(backend, AdvancedFlashEraseScope.ENTIRE_APPLICATION_REGION),
            RuntimeOperationType.ERASE,
            False,
            ["event", "service", "operation"],
        ),
        (
            lambda backend: erase(backend, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, 0x2),
            RuntimeOperationType.ERASE,
            False,
            ["event", "service", "operation"],
        ),
    ),
)
def test_flash_typed_start_identity_and_ordering(
    tmp_path, monkeypatch, request_factory, event_type, has_identity, expected_order
) -> None:
    order, events = [], []
    backend, *_ = populated_backend(tmp_path, [])
    original_app = backend._materialize_flash_app
    original_service = backend._materialize_flash_service
    monkeypatch.setattr(
        backend,
        "_materialize_flash_app",
        lambda **kwargs: order.append("app") or original_app(**kwargs),
    )
    monkeypatch.setattr(
        backend,
        "_materialize_flash_service",
        lambda **kwargs: order.append("service") or original_service(**kwargs),
    )
    for name in (
        "_erase_flash_image_area_operation",
        "_erase_sector_mask_operation",
        "_program_flash_operation",
        "_verify_flash_operation",
    ):
        original = getattr(backend, name)
        monkeypatch.setattr(
            backend,
            name,
            lambda *args, _original=original: order.append("operation") or _original(*args),
        )
    backend.subscribe_runtime_v2(
        lambda result: (events.append(result.source_event), order.append("event"))
        if isinstance(result.source_event, OperationStarted)
        else None
    )
    request = request_factory(backend)

    backend.execute("flash-task", request, None, None)

    assert order == expected_order
    assert events == [
        OperationStarted(
            "flash-task",
            event_type,
            RuntimeCpuId.CPU1,
            backend.connection_generation,
            request.expected_image_identity if has_identity else None,
        )
    ]


def test_flash_post_start_materialization_failure_emits_one_event_and_stale_emits_zero(
    tmp_path
) -> None:
    backend, app_path, *_ = populated_backend(tmp_path, [])
    events = []
    backend.subscribe_runtime_v2(
        lambda result: events.append(result.source_event)
        if isinstance(result.source_event, OperationStarted)
        else None
    )
    request = flash_request(backend, ProgramAdvancedFlashRequest)
    stale_request = flash_request(
        backend, ProgramAdvancedFlashRequest, connection_id="old"
    )
    app_path.unlink()

    failed = backend.execute("failed", request, None, None)
    stale = backend.execute("stale", stale_request, None, None)

    assert failed.error.code == "IMAGE_FILE_ACCESS_FAILED"
    assert stale.error.code == "STALE_CONNECTION"
    assert len(events) == 1 and events[0].operation_id == "failed"


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
    return out_path, root


def test_program_only_materializes_app_once(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    template = backend._prepare_flash_operation()
    materialized = []

    def prepare(*_args, **_kwargs):
        value = replace(template)
        materialized.append(value)
        return value

    backend._prepare_flash_operation = prepare
    result = backend.execute("program", flash_request(backend, ProgramAdvancedFlashRequest), None, None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(materialized) == 1
    assert calls[0][2].image is materialized[0]


def test_verify_only_materializes_app_once_and_creates_evidence(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    template = backend._prepare_flash_operation()
    materialized = []

    def prepare(*_args, **_kwargs):
        value = replace(template)
        materialized.append(value)
        return value

    backend._prepare_flash_operation = prepare
    result = backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), None, None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(materialized) == 1
    assert calls[0][2].image is materialized[0]
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is not None


def test_required_app_erase_materializes_app_once(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    template = backend._prepare_flash_operation()
    materialized = []
    backend._prepare_flash_operation = lambda *_a, **_kw: materialized.append(replace(template)) or materialized[-1]

    result = backend.execute(
        "erase",
        erase(backend, AdvancedFlashEraseScope.REQUIRED_APP_SECTORS),
        None,
        None,
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(materialized) == 1
    assert calls[0][2].image is materialized[0]


def test_entire_and_custom_erase_materialize_app_zero_times(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    backend._prepare_flash_operation = lambda *_a, **_kw: pytest.fail("App must not materialize")

    entire = backend.execute(
        "entire", erase(backend, AdvancedFlashEraseScope.ENTIRE_APPLICATION_REGION), None, None
    )
    custom = backend.execute(
        "custom", erase(backend, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, 0x6), None, None
    )

    assert entire.status is custom.status is TaskFinalStatus.SUCCEEDED


@pytest.mark.parametrize(
    ("field", "value", "sector_mask"),
    (
        ("entry_point", 0x082008, 0x2),
        ("image_size_words", 16, 0x2),
        ("image_crc32", 0x9999, 0x2),
        ("app_end", 0x082010, 0x2),
        (None, None, 0x4),
    ),
)
def test_same_path_identity_change_rejects_before_service_and_operation(
    tmp_path, field, value, sector_mask
) -> None:
    calls = []
    service_materializations = []
    backend, *_ = populated_backend(tmp_path, calls)
    template = backend._prepare_flash_operation()
    identity = replace(template.identity, **({field: value} if field else {}))
    backend._prepare_flash_operation = lambda *_a, **_kw: replace(
        template, identity=identity, sector_mask=sector_mask
    )
    backend._prepare_service_operation = lambda *_a, **_kw: service_materializations.append(1)

    result = backend.execute("changed", flash_request(backend, ProgramAdvancedFlashRequest), None, None)

    assert result.error.code == "IMAGE_CHANGED"
    assert calls == []
    assert service_materializations == []


def test_out_flash_success_workspace_cleanup(tmp_path) -> None:
    calls = []
    backend, app_path, *_ = populated_backend(tmp_path, calls)
    template = backend._prepare_flash_operation()
    children = []

    def prepare(*_args, **kwargs):
        sci8 = Path(kwargs["sci8_txt"])
        children.append(sci8.parent)
        return replace(template, generated_sci8_txt=str(sci8))

    _out_path, root = _use_out_source(backend, app_path, tmp_path, prepare)
    result = backend.execute("program", flash_request(backend, ProgramAdvancedFlashRequest), None, None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(children) == 1 and not children[0].exists()
    assert list(root.iterdir()) == []
    assert calls[0][2].image.generated_sci8_txt is None


def test_out_flash_failure_workspace_cleanup(tmp_path) -> None:
    backend, app_path, *_ = populated_backend(tmp_path, [])
    template = backend._prepare_flash_operation()
    children = []

    def prepare(*_args, **kwargs):
        sci8 = Path(kwargs["sci8_txt"])
        children.append(sci8.parent)
        return replace(template, generated_sci8_txt=str(sci8))

    def fail(ctx, request):
        return OperationResult(
            False,
            "program",
            ctx.target.name,
            "PROGRAM",
            {},
            error=OperationErrorInfo("PROGRAM_FAILED", "failed", "PROGRAM"),
        )

    backend._program_flash_operation = fail
    _out_path, root = _use_out_source(backend, app_path, tmp_path, prepare)
    result = backend.execute("program", flash_request(backend, ProgramAdvancedFlashRequest), None, None)

    assert result.status is TaskFinalStatus.FAILED
    assert len(children) == 1 and not children[0].exists()
    assert list(root.iterdir()) == []


def test_txt_operation_is_read_only_and_uses_no_workspace(tmp_path) -> None:
    backend, app_path, *_ = populated_backend(tmp_path, [])
    template = backend._prepare_flash_operation()
    before = (app_path.read_bytes(), app_path.stat().st_mtime_ns)
    kwargs_seen = []

    def prepare(*_args, **kwargs):
        kwargs_seen.append(kwargs)
        return replace(template)

    backend._prepare_flash_operation = prepare
    result = backend.execute("program", flash_request(backend, ProgramAdvancedFlashRequest), None, None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert kwargs_seen == [{"target": CPU1_PROFILE}]
    assert (app_path.read_bytes(), app_path.stat().st_mtime_ns) == before


def test_erase_scopes_call_only_the_selected_public_operation(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    required = backend.execute("required", erase(backend, AdvancedFlashEraseScope.REQUIRED_APP_SECTORS), object(), None)
    entire = backend.execute("entire", erase(backend, AdvancedFlashEraseScope.ENTIRE_APPLICATION_REGION), object(), None)
    custom = backend.execute("custom", erase(backend, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, 0x6), object(), None)

    assert [item[0] for item in calls] == ["erase_area", "erase_mask", "erase_mask"]
    assert isinstance(calls[0][2], EraseFlashImageAreaRequest)
    assert isinstance(calls[1][2], EraseSectorMaskRequest)
    assert calls[1][2].sector_mask == CPU1_PROFILE.memory_map.flash.allowed_erase_mask
    assert calls[2][2].sector_mask == 0x6
    assert required.payload.erase_sector_mask == 0x2
    assert entire.payload.erase_sector_mask == CPU1_PROFILE.memory_map.flash.allowed_erase_mask
    assert custom.payload.erase_sector_mask == 0x6
    assert required.payload.erase_sector_mask & CPU1_PROFILE.memory_map.flash.metadata_sector_mask


@pytest.mark.parametrize("mask", [0x1, 1 << 20])
def test_forbidden_custom_masks_are_rejected_before_operation(tmp_path, mask) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    result = backend.execute(
        "erase", erase(backend, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, mask), object(), None
    )
    assert result.status is TaskFinalStatus.FAILED
    assert result.error.code == "FORBIDDEN_SECTOR"
    assert calls == []


def test_program_and_verify_are_independent_and_materialize_distinct_contexts(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    cancellation = object()
    events = []
    completion_events = []
    backend.subscribe_runtime_v2(
        lambda transition: completion_events.append(transition.source_event)
        if isinstance(transition.source_event, OperationSucceeded)
        else None
    )
    program = backend.execute("program", flash_request(backend, ProgramAdvancedFlashRequest), cancellation, events.append)
    verify = backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), cancellation, events.append)

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
    assert len(completion_events) == 1
    assert completion_events[0].operation_type is RuntimeOperationType.VERIFY


def test_flash_operation_materializes_service_once_per_task(tmp_path) -> None:
    backend, *_ = populated_backend(tmp_path, [])
    materialized = []
    original = backend._prepare_service_operation

    def prepare(*args, **kwargs):
        value = original(*args, **kwargs)
        materialized.append(value)
        return value

    backend._prepare_service_operation = prepare
    assert backend.execute("one", flash_request(backend, ProgramAdvancedFlashRequest), None, None).status is TaskFinalStatus.SUCCEEDED
    assert len(materialized) == 1
    assert all(not isinstance(value, PreparedServiceImage) for value in vars(backend).values())


def test_clean_verify_success_dispatches_once_and_creates_exact_evidence(tmp_path) -> None:
    backend, *_ = populated_backend(tmp_path, [])
    events = []
    backend.subscribe_runtime_v2(
        lambda transition: events.append(transition.source_event)
        if isinstance(transition.source_event, OperationSucceeded)
        else None
    )
    result = backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), object(), None)
    evidence = backend.target_resources[RuntimeCpuId.CPU1].verify_evidence
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert evidence == VerifyEvidence(
        RuntimeCpuId.CPU1, backend.connection_generation, IMAGE_IDENTITY, "verify"
    )
    assert events == [OperationSucceeded(
        "verify", RuntimeOperationType.VERIFY, RuntimeCpuId.CPU1,
        backend.connection_generation, IMAGE_IDENTITY,
    )]


@pytest.mark.parametrize(
    "completion",
    [OperationCompletion.FAILED, OperationCompletion.CANCELLED, OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST],
)
def test_nonclean_verify_creates_no_evidence(tmp_path, completion) -> None:
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
    backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), object(), None)
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is None


def test_verify_result_word_mismatch_creates_no_evidence(tmp_path) -> None:
    def verify(ctx, request):
        return OperationResult(
            True, "verify", ctx.target.name, "VERIFY_END", {"total_words": 16}
        )

    backend, *_ = populated_backend(tmp_path, [], verify_flash_operation=verify)
    backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), object(), None)
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is None


@pytest.mark.parametrize("change", ("source", "generation", "revision", "tool", "identity", "sector", "target"))
def test_verify_post_operation_change_creates_no_evidence(tmp_path, change) -> None:
    backend, app_path, *_ = populated_backend(tmp_path, [])

    def verify(ctx, request):
        if change == "source":
            app_path.write_text("changed")
        elif change == "generation":
            backend._runtime_v2_dispatcher.dispatch(ConnectionOpened(backend.connection_info))
        elif change == "revision":
            backend._program_image_revisions[RuntimeCpuId.CPU1] += 1
        elif change == "tool":
            backend._configuration_revision += 1
        elif change in {"identity", "sector"}:
            resource = backend.target_resources[RuntimeCpuId.CPU1]
            summary = resource.program_image_summary
            summary = replace(
                summary,
                identity=replace(summary.identity, image_crc32=0x9999)
                if change == "identity" else summary.identity,
                sector_mask=0x4 if change == "sector" else summary.sector_mask,
            )
            backend._runtime_v2_store.replace_target_resource(
                RuntimeCpuId.CPU1, replace(resource, program_image_summary=summary)
            )
        else:
            backend._target = CPU2_PROFILE
        return OperationResult(True, "verify", ctx.target.name, "VERIFY_END", {})

    backend._verify_flash_operation = verify
    backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), None, None)
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is None


def test_verify_wrong_result_target_creates_no_evidence(tmp_path) -> None:
    backend, *_ = populated_backend(
        tmp_path,
        [],
        verify_flash_operation=lambda _ctx, _request: OperationResult(
            True, "verify", "cpu2", "VERIFY_END", {}
        ),
    )
    backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), None, None)
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is None


def test_valid_mutating_flash_start_clears_evidence_but_rejected_request_does_not(tmp_path) -> None:
    backend, *_ = populated_backend(tmp_path, [])
    backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), object(), None)
    evidence = backend.target_resources[RuntimeCpuId.CPU1].verify_evidence
    assert evidence is not None
    rejected = backend.execute(
        "stale", flash_request(backend, ProgramAdvancedFlashRequest, connection_id="old"), object(), None
    )
    assert rejected.error.code == "STALE_CONNECTION"
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is evidence
    backend.execute("program", flash_request(backend, ProgramAdvancedFlashRequest), object(), None)
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is None


def test_operation_identity_and_configuration_invalidation_follow_v2_rules(tmp_path) -> None:
    backend, *_ = populated_backend(tmp_path, [])
    backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), object(), None)
    evidence = backend.target_resources[RuntimeCpuId.CPU1].verify_evidence
    service_path = Path(backend.flash_service_resource_state.image_path)
    service_path.write_text("changed service")
    result = backend.execute("changed", flash_request(backend, ProgramAdvancedFlashRequest), None, None)
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is None

    backend, *_ = populated_backend(tmp_path, [])
    backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), object(), None)
    evidence = backend.target_resources[RuntimeCpuId.CPU1].verify_evidence
    backend.set_program_image_path("cpu1", str(tmp_path / "new.txt"))
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is evidence
    backend._runtime_v2_dispatcher.dispatch(
        ProgramImageChanged(
            RuntimeCpuId.CPU1,
            str(tmp_path / "new.txt"),
            ImageParseStatus.READY,
            FlashImageSummary(replace(IMAGE_IDENTITY, image_crc32=0x9999), 0x2),
        )
    )
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is None

    backend, *_ = populated_backend(tmp_path, [])
    backend.execute("verify", flash_request(backend, VerifyAdvancedFlashRequest), object(), None)
    evidence = backend.target_resources[RuntimeCpuId.CPU1].verify_evidence
    backend.set_image_tool_paths("new-hex2000", "new-temp")
    assert backend.target_resources[RuntimeCpuId.CPU1].verify_evidence is evidence


def test_stale_identities_and_changed_sources_clear_only_affected_cache(tmp_path) -> None:
    calls = []
    backend, app_path, service_path, _map_path = populated_backend(tmp_path, calls)
    assert backend.execute("old", flash_request(backend, ProgramAdvancedFlashRequest, connection_id="old"), None, None).error.code == "STALE_CONNECTION"
    assert backend.execute("revision", flash_request(backend, ProgramAdvancedFlashRequest, image_selection_revision=0), None, None).error.code == "STALE_IMAGE_CONFIGURATION"

    service_state = backend.flash_service_resource_state
    app_path.write_text("changed app")
    original_prepare = backend._prepare_flash_operation
    backend._prepare_flash_operation = lambda *_a, **_kw: replace(
        original_prepare(),
        identity=replace(IMAGE_IDENTITY, image_crc32=0x9999),
    )
    assert backend.execute("changed", flash_request(backend, ProgramAdvancedFlashRequest), None, None).error.code == "IMAGE_CHANGED"
    assert backend.target_resources[RuntimeCpuId.CPU1].program_image_parse_status is ImageParseStatus.ERROR
    assert backend.flash_service_resource_state == service_state

    backend, _app_path, service_path, _map_path = populated_backend(tmp_path, calls)
    service_path.write_text("changed service")
    assert backend.execute("changed-service", flash_request(backend, ProgramAdvancedFlashRequest), None, None).error.code == "SERVICE_RESOURCE_CHANGED"
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.STALE


def test_same_path_service_map_change_rejects_before_flash_operation(tmp_path) -> None:
    calls = []
    backend, _app, _service, map_path = populated_backend(tmp_path, calls)
    map_path.write_text("changed map")
    result = backend.execute("changed-map", flash_request(backend, ProgramAdvancedFlashRequest), None, None)
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.STALE
    assert calls == []


def test_same_path_service_image_change_rejects_before_flash_operation(tmp_path) -> None:
    calls = []
    backend, _app, service_path, _map = populated_backend(tmp_path, calls)
    service_path.write_text("changed image")
    result = backend.execute("changed-image", flash_request(backend, ProgramAdvancedFlashRequest), None, None)
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"


def test_provider_path_replacement_publishes_new_stale_paths(tmp_path) -> None:
    calls = []
    backend, _app, _service, _map = populated_backend(tmp_path, calls)
    new_service = tmp_path / "replacement.txt"
    new_map = tmp_path / "replacement.map"
    new_service.write_text("service.txt")
    new_map.write_text("service.map")
    backend.app_resource_provider.image = new_service
    backend.app_resource_provider.map_file = new_map

    result = backend.execute("changed", flash_request(backend, ProgramAdvancedFlashRequest), None, None)

    state = backend.flash_service_resource_state
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"
    assert state.status is FlashServiceResourceStatus.STALE
    assert (state.image_path, state.map_path) == (
        str(new_service.resolve()), str(new_map.resolve())
    )
    assert state.summary is None
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
    result = backend.execute("changed-symbol", flash_request(backend, ProgramAdvancedFlashRequest), None, None)
    assert result.error.code == "SERVICE_RESOURCE_CHANGED"
    assert calls == []


def test_cpu2_and_missing_capabilities_are_rejected_without_invocation(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    forged = flash_request(backend, ProgramAdvancedFlashRequest)
    object.__setattr__(forged, "target_key", "cpu2")
    assert backend.execute("cpu2", forged, None, None).error.code == "UNSUPPORTED_OPERATION"

    backend._target = CPU2_PROFILE
    backend._connection_info = ConnectionInfo("connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu2")
    mismatch = flash_request(backend, ProgramAdvancedFlashRequest)
    assert backend.execute("target", mismatch, None, None).error.code == "STALE_TARGET"
    assert calls == []


def test_missing_ram_check_crc_is_rejected_before_operation(tmp_path) -> None:
    calls = []
    backend, *_ = populated_backend(tmp_path, calls)
    backend._target = replace(
        CPU1_PROFILE,
        command_set=replace(CPU1_PROFILE.command_set, ram_check_crc=None),
    )
    result = backend.execute("program", flash_request(backend, ProgramAdvancedFlashRequest), None, None)
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
    result = backend.execute("program", flash_request(backend, ProgramAdvancedFlashRequest), object(), None)
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
    failed_result = backend.execute("failed", flash_request(backend, ProgramAdvancedFlashRequest), object(), None)
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
    evidence_at_finish = []
    controller.taskProgressed.connect(updates.append)
    controller.taskFinished.connect(results.append)
    controller.taskFinished.connect(
        lambda _result: evidence_at_finish.append(
            backend.target_resources[RuntimeCpuId.CPU1].verify_evidence
        )
    )
    assert controller.request_task(flash_request(backend, request_type)).accepted

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
    if request_type is VerifyAdvancedFlashRequest:
        assert evidence_at_finish[-1].operation_id == results[-1].task_id
    else:
        assert evidence_at_finish[-1] is None
