from datetime import datetime, timezone
from pathlib import Path

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_ram_models import (
    CheckAdvancedRamCrcRequest,
    LoadAdvancedRamImageRequest,
    PrepareRamImageRequest,
    RunAdvancedRamImageRequest,
)
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
    ErrorDisposition,
    TaskCompletionAction,
    TaskFinalStatus,
    TaskStepState,
)
from bootloader_upgrade_tool.images import PreparedRamImage
from bootloader_upgrade_tool.operations import (
    OperationCancellationInfo,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
    ProgressEvent,
)
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


def prepared() -> PreparedRamImage:
    image = FirmwareImage(
        source_out_file="ram.txt",
        generated_hex_file="ram.txt",
        entry_point=0x008000,
        blocks=(FirmwareBlock(0x008000, (1, 2, 3)),),
        file_checksum="sha",
        format_info={},
    )
    return PreparedRamImage(image, image.entry_point, image.total_words, 0x12345678)


def connected_backend(tmp_path: Path, **operations):
    calls = []

    def prepare_image(path, **kwargs):
        calls.append(("prepare", str(path), kwargs["target"]))
        return prepared()

    backend = RuntimeBackend(prepare_ram_operation=prepare_image, **operations)
    backend._session = object()
    backend._target = CPU1_PROFILE
    backend._connection_info = ConnectionInfo("connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu1")
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    result = backend.execute("prepare", PrepareRamImageRequest("cpu1", str(path), 0), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    return backend, path, calls


def ok(name, calls, *, progress=False):
    def operation(ctx, request):
        calls.append((name, ctx, request))
        if progress:
            ctx.progress(ProgressEvent(name, ctx.target.name, "RAM_LOAD_DATA", "loaded", 3, 3, 3, cancellation_supported=True))
        return OperationResult(True, name, ctx.target.name, name.upper(), {})
    return operation


def test_ram_operations_are_independent_and_use_batch14c_adapter(tmp_path) -> None:
    calls = []
    backend, _path, _ = connected_backend(
        tmp_path,
        load_ram_operation=ok("load", calls, progress=True),
        check_ram_crc_operation=ok("check", calls),
        run_ram_operation=ok("run", calls),
    )
    events = []
    load = backend.execute("load", LoadAdvancedRamImageRequest("connection", "cpu1", 0), object(), events.append)
    check = backend.execute("check", CheckAdvancedRamCrcRequest("connection", "cpu1", 0), object(), events.append)
    run = backend.execute("run", RunAdvancedRamImageRequest("connection", "cpu1", 0), object(), events.append)

    assert [item[0] for item in calls] == ["load", "check", "run"]
    assert calls[0][1].cancellation is not None
    assert calls[1][1].cancellation is None and calls[2][1].cancellation is None
    progress = [event for event in events if event.step_state is TaskStepState.PROGRESS]
    assert len(progress) == 1 and progress[0].raw_event.stage == "RAM_LOAD_DATA"
    assert load.status is check.status is run.status is TaskFinalStatus.SUCCEEDED
    assert run.completion_action is TaskCompletionAction.RELEASE_CONNECTION


def test_ram_operation_rejects_stale_identity_missing_cache_and_changed_source(tmp_path) -> None:
    backend, path, _ = connected_backend(tmp_path, load_ram_operation=ok("load", []))
    assert backend.execute("x", LoadAdvancedRamImageRequest("old", "cpu1", 0), None, None).error.code == "STALE_CONNECTION"
    assert backend.execute("x", LoadAdvancedRamImageRequest("connection", "cpu2", 0), None, None).error.code == "STALE_CONNECTION"
    backend.invalidate_prepared_ram_image("cpu1", 1)
    assert backend.execute("x", LoadAdvancedRamImageRequest("connection", "cpu1", 1), None, None).error.code == "PREPARED_RAM_IMAGE_REQUIRED"
    backend.execute("prepare2", PrepareRamImageRequest("cpu1", str(path), 1), None, None)
    other = (object(), object())
    with backend._image_lock:
        backend._prepared_ram_images["cpu2"] = other
    path.write_text("changed", encoding="ascii")
    assert backend.execute("x", LoadAdvancedRamImageRequest("connection", "cpu1", 1), None, None).error.code == "IMAGE_CHANGED"
    assert backend.prepared_ram_image_cache("cpu1") is None
    assert backend.prepared_ram_image_cache("cpu2") == other


def test_cpu2_unsupported_capabilities_are_rejected_without_profile_changes(tmp_path) -> None:
    backend, path, _ = connected_backend(tmp_path)
    cpu1 = backend.prepared_ram_image_cache("cpu1")
    backend._target = CPU2_PROFILE
    backend._connection_info = ConnectionInfo("cpu2", "SCI", "COM3", datetime.now(timezone.utc), "cpu2")
    backend.invalidate_prepared_ram_image("cpu2", 1)
    assert backend.execute("prep2", PrepareRamImageRequest("cpu2", str(path), 1), None, None).status is TaskFinalStatus.SUCCEEDED
    assert backend.prepared_ram_image_cache("cpu1") == cpu1
    assert backend.prepared_ram_image_cache("cpu2") is not None
    result = backend.execute("load", LoadAdvancedRamImageRequest("cpu2", "cpu2", 1), None, None)
    assert result.status is TaskFinalStatus.FAILED and result.error.code == "UNSUPPORTED_OPERATION"
    assert CPU2_PROFILE.command_set.ram_load_begin is None


def test_load_preserves_cancellation_outcomes_and_cleanup_disposition(tmp_path) -> None:
    cancellation = OperationCancellationInfo("RAM_LOAD_END", 3, 3, True, False, False)

    def completed(ctx, request):
        return OperationResult(True, "load_ram_image", ctx.target.name, "RAM_LOAD_END", {}, completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST, cancellation=cancellation)

    backend, _path, _ = connected_backend(tmp_path, load_ram_operation=completed)
    result = backend.execute("load", LoadAdvancedRamImageRequest("connection", "cpu1", 0), object(), None)
    assert result.status is TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST

    uncertain = OperationCancellationInfo("RAM_LOAD_END", 1, 3, False, True, True, recovery_action="RECONNECT_AND_RESTART_RAM_LOAD")

    def failed(ctx, request):
        return OperationResult(False, "load_ram_image", ctx.target.name, "RAM_LOAD_END", {}, error=OperationErrorInfo("CANCELLATION_CLEANUP_FAILED", "cleanup", "RAM_LOAD_END", True), cancellation=uncertain)

    backend._load_ram_operation = failed
    result = backend.execute("failed", LoadAdvancedRamImageRequest("connection", "cpu1", 0), object(), None)
    assert result.status is TaskFinalStatus.FAILED
    assert result.error.disposition is ErrorDisposition.ASK_DISCONNECT


def test_clean_load_cancellation_preserves_connection(tmp_path) -> None:
    cancellation = OperationCancellationInfo("RAM_LOAD_END", 1, 3, True, False, False, recovery_action="RESTART_RAM_LOAD")

    def cancelled(ctx, request):
        return OperationResult(False, "load_ram_image", ctx.target.name, "RAM_LOAD_END", {}, completion=OperationCompletion.CANCELLED, cancellation=cancellation)

    backend, _path, _ = connected_backend(tmp_path, load_ram_operation=cancelled)
    session = backend.active_session
    result = backend.execute("load", LoadAdvancedRamImageRequest("connection", "cpu1", 0), object(), None)
    assert result.status is TaskFinalStatus.CANCELLED
    assert result.completion_action is TaskCompletionAction.NONE
    assert backend.active_session is session


def test_current_behavior_ram_cache_retains_full_image_across_disconnect(tmp_path) -> None:
    # Migration baseline only: Runtime V2 will remove this full-image cache.
    backend, path, _ = connected_backend(tmp_path)
    cpu1 = backend.prepared_ram_image_cache("cpu1")
    assert isinstance(cpu1[0], PreparedRamImage)
    backend.invalidate_prepared_ram_image("cpu2", 1)
    backend._clear_active()
    assert backend.prepared_ram_image_cache("cpu1") == cpu1
    assert backend.prepared_ram_image_cache("cpu2") is None
