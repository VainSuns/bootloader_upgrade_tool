from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread

import pytest

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
from bootloader_upgrade_tool.images import PreparedRamImage, RamImageIdentity
from bootloader_upgrade_tool.operations import (
    OperationCancellationInfo,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
    ProgressEvent,
)
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE
from bootloader_upgrade_tool.gui.runtime_v2_models import ImageParseStatus, RuntimeCpuId
from bootloader_upgrade_tool.gui.runtime_v2_events import ConnectionOpened, OperationStarted, RamImageChanged


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


def _out_backend(tmp_path, monkeypatch):
    executable = tmp_path / "hex2000.exe"
    executable.touch()
    source = tmp_path / "ram.out"
    source.write_bytes(b"out")
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000",
        lambda *_a, **_k: executable,
    )
    backend = RuntimeBackend(
        hex2000_executable_path=executable,
        prepare_ram_operation=lambda *_a, **_k: prepared(),
    )
    revision = backend.set_ram_image_path("cpu1", f"  {source}  ")
    return backend, source, revision


def _pause_ram_dispatch(backend, monkeypatch, status):
    entered, release = Event(), Event()
    original = backend._runtime_v2_dispatcher.dispatch

    def dispatch(event):
        if isinstance(event, RamImageChanged) and event.parse_status is status:
            entered.set()
            assert release.wait(5)
        return original(event)

    monkeypatch.setattr(backend._runtime_v2_dispatcher, "dispatch", dispatch)
    return entered, release


def _start_waiting_tool_change(backend, tmp_path):
    done = Event()
    thread = Thread(
        target=lambda: (
            backend.set_image_tool_paths(str(tmp_path / "new.exe"), str(tmp_path / "work")),
            done.set(),
        )
    )
    thread.start()
    return thread, done


def test_ready_commit_serializes_before_out_tool_invalidation(tmp_path, monkeypatch) -> None:
    backend, source, revision = _out_backend(tmp_path, monkeypatch)
    backend.begin_ram_image_parse("cpu1", str(source), revision)
    entered, release = _pause_ram_dispatch(backend, monkeypatch, ImageParseStatus.READY)
    parse = Thread(
        target=lambda: backend.execute(
            "prepare", PrepareRamImageRequest("cpu1", str(source), revision), None, None
        )
    )
    parse.start()
    assert entered.wait(5)
    tool, tool_done = _start_waiting_tool_change(backend, tmp_path)
    assert not tool_done.wait(0.05)

    release.set()
    parse.join(5)
    tool.join(5)

    state = backend.target_resources[RuntimeCpuId.CPU1]
    assert tool_done.is_set() and state.ram_image_parse_status is ImageParseStatus.EMPTY
    assert state.ram_image_path == f"  {source}  "
    assert state.ram_image_summary is None and state.ram_image_parse_error is None
    assert not hasattr(backend, "_prepared_ram_images")


def test_error_commit_serializes_before_out_tool_invalidation(tmp_path, monkeypatch) -> None:
    backend, source, revision = _out_backend(tmp_path, monkeypatch)
    backend.begin_ram_image_parse("cpu1", str(source), revision)
    entered, release = _pause_ram_dispatch(backend, monkeypatch, ImageParseStatus.ERROR)
    failure = Thread(
        target=lambda: backend.fail_ram_image_parse(
            "cpu1", str(source), revision, "PARSE", "bad image"
        )
    )
    failure.start()
    assert entered.wait(5)
    tool, tool_done = _start_waiting_tool_change(backend, tmp_path)
    assert not tool_done.wait(0.05)

    release.set()
    failure.join(5)
    tool.join(5)

    state = backend.target_resources[RuntimeCpuId.CPU1]
    assert tool_done.is_set() and state.ram_image_parse_status is ImageParseStatus.EMPTY
    assert state.ram_image_parse_error is None
    assert not hasattr(backend, "prepared_ram_image_cache")


def test_begin_commit_serializes_before_out_tool_invalidation(tmp_path, monkeypatch) -> None:
    backend, source, revision = _out_backend(tmp_path, monkeypatch)
    entered, release = _pause_ram_dispatch(backend, monkeypatch, ImageParseStatus.PARSING)
    begin = Thread(
        target=lambda: backend.begin_ram_image_parse("cpu1", str(source), revision)
    )
    begin.start()
    assert entered.wait(5)
    tool, tool_done = _start_waiting_tool_change(backend, tmp_path)
    assert not tool_done.wait(0.05)

    release.set()
    begin.join(5)
    tool.join(5)

    state = backend.target_resources[RuntimeCpuId.CPU1]
    assert tool_done.is_set() and state.ram_image_parse_status is ImageParseStatus.EMPTY
    assert not hasattr(backend, "_prepared_ram_images")


def test_backend_owns_independent_ram_selection_parse_and_error_state(tmp_path) -> None:
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    backend = RuntimeBackend(prepare_ram_operation=lambda *_a, **_k: prepared())

    assert backend.set_ram_image_path("cpu1", f"  {path}  ") == 1
    assert backend.ram_image_revision("cpu1") == 1
    assert backend.ram_image_revision("cpu2") == 0
    cpu1 = backend.target_resources[RuntimeCpuId.CPU1]
    assert cpu1.ram_image_path == f"  {path}  "
    assert cpu1.ram_image_parse_status is ImageParseStatus.EMPTY

    backend.begin_ram_image_parse("cpu1", str(path), 1)
    assert backend.target_resources[RuntimeCpuId.CPU1].ram_image_parse_status is ImageParseStatus.PARSING
    result = backend.execute(
        "prepare", PrepareRamImageRequest("cpu1", str(path), 1), None, None
    )
    ready = backend.target_resources[RuntimeCpuId.CPU1]
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert ready.ram_image_parse_status is ImageParseStatus.READY
    assert ready.ram_image_summary.identity.entry_point == prepared().entry_point
    assert not hasattr(backend, "prepared_ram_image_cache")

    assert backend.set_ram_image_path("cpu1", f"  {path}  ") == 2
    assert backend.fail_ram_image_parse("cpu1", str(path), 1, "OLD", "stale") is None
    backend.begin_ram_image_parse("cpu1", str(path), 2)
    backend.fail_ram_image_parse("cpu1", str(path), 2, "PARSE", "bad image")
    failed = backend.target_resources[RuntimeCpuId.CPU1]
    assert failed.ram_image_parse_status is ImageParseStatus.ERROR
    assert failed.ram_image_parse_error == "Code: PARSE\nbad image"
    assert backend.target_resources[RuntimeCpuId.CPU2].ram_image_parse_status is ImageParseStatus.EMPTY


def test_ram_tool_change_invalidates_out_but_preserves_txt(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "hex2000.exe"
    executable.touch()
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000",
        lambda *_a, **_k: executable,
    )
    out = tmp_path / "cpu1.OUT"
    txt = tmp_path / "cpu2.TXT"
    out.write_bytes(b"out")
    txt.write_text("txt", encoding="ascii")
    backend = RuntimeBackend(
        hex2000_executable_path=executable,
        prepare_ram_operation=lambda *_a, **_k: prepared(),
    )
    for target, path in (("cpu1", out), ("cpu2", txt)):
        revision = backend.set_ram_image_path(target, f"  {path}  ")
        backend.begin_ram_image_parse(target, str(path), revision)
        assert backend.execute(
            target, PrepareRamImageRequest(target, str(path), revision), None, None
        ).status is TaskFinalStatus.SUCCEEDED
    txt_state = backend.target_resources[RuntimeCpuId.CPU2]

    backend.set_image_tool_paths(str(tmp_path / "new.exe"), str(tmp_path / "work"))

    cpu1 = backend.target_resources[RuntimeCpuId.CPU1]
    assert cpu1.ram_image_path == f"  {out}  "
    assert cpu1.ram_image_parse_status is ImageParseStatus.EMPTY
    assert backend.ram_image_revision("cpu1") == 2
    assert backend.target_resources[RuntimeCpuId.CPU2] == txt_state
    assert backend.ram_image_revision("cpu2") == 1
    assert not hasattr(backend, "_prepared_ram_images")


def test_session_change_resets_ram_revisions_and_resources(tmp_path) -> None:
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    backend = RuntimeBackend(prepare_ram_operation=lambda *_a, **_k: prepared())
    revision = backend.set_ram_image_path("cpu1", str(path))
    backend.begin_ram_image_parse("cpu1", str(path), revision)
    backend.execute("prepare", PrepareRamImageRequest("cpu1", str(path), revision), None, None)

    backend.apply_session_change()

    assert all(backend.ram_image_revision(cpu.value) == 0 for cpu in RuntimeCpuId)
    assert all(
        backend.target_resources[cpu].ram_image_parse_status is ImageParseStatus.EMPTY
        and not backend.target_resources[cpu].ram_image_path
        for cpu in RuntimeCpuId
    )
    assert not hasattr(backend, "_prepared_ram_images")


def _ram_sci8_text() -> str:
    words = [
        0x08AA,
        *([0] * 8),
        0x0000,
        0x8000,
        8,
        0x0000,
        0x8000,
        *range(8),
        0,
    ]
    return "\n".join(f"{word:04X}" for word in words)


def connected_backend(tmp_path: Path, **operations):
    calls = []

    def prepare_image(path, **kwargs):
        calls.append(("prepare", str(path), kwargs["target"]))
        return prepared()

    backend = RuntimeBackend(prepare_ram_operation=prepare_image, **operations)
    connect_backend(backend)
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    result = backend.execute("prepare", PrepareRamImageRequest("cpu1", str(path), 0), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    return backend, path, calls


def connect_backend(backend, *, connection_id="connection", target="cpu1"):
    profile = CPU1_PROFILE if target == "cpu1" else CPU2_PROFILE
    backend._session = object()
    backend._target = profile
    backend._connection_info = ConnectionInfo(connection_id, "SCI", "COM3", datetime.now(timezone.utc), target)
    backend._runtime_v2_dispatcher.dispatch(ConnectionOpened(backend._connection_info))
    return backend


def ram_request(backend, path, request_type, *, connection="connection", target="cpu1", revision=0):
    identity = backend.target_resources[RuntimeCpuId.from_target_key(target)].ram_image_summary
    expected = identity.identity if identity is not None else RamImageIdentity(0x8000, 3, 0x12345678)
    if request_type is RunAdvancedRamImageRequest:
        return request_type(connection, target, revision, expected)
    return request_type(
        connection,
        target,
        str(Path(path).resolve()),
        revision,
        backend.configuration_revision,
        expected,
    )


def ok(name, calls, *, progress=False):
    def operation(ctx, request):
        calls.append((name, ctx, request))
        if progress:
            ctx.progress(ProgressEvent(name, ctx.target.name, "RAM_LOAD_DATA", "loaded", 3, 3, 3, cancellation_supported=True))
        return OperationResult(True, name, ctx.target.name, name.upper(), {})
    return operation


def test_ram_load_materializes_once_per_task_and_uses_distinct_images(tmp_path) -> None:
    received = []
    backend, path, preparations = connected_backend(
        tmp_path, load_ram_operation=lambda _ctx, request: received.append(request.image)
        or OperationResult(True, "load_ram_image", "CPU1", "RAM_LOAD_END", {})
    )

    for task_id in ("load-1", "load-2"):
        result = backend.execute(
            task_id,
            ram_request(backend, path, LoadAdvancedRamImageRequest),
            None,
            None,
        )
        assert result.status is TaskFinalStatus.SUCCEEDED

    assert len(preparations) == 3  # one automatic parse plus one per Load task
    assert len(received) == 2 and received[0] is not received[1]


def test_ram_crc_materializes_once_per_task_and_uses_distinct_images(tmp_path) -> None:
    received = []
    backend, path, preparations = connected_backend(
        tmp_path, check_ram_crc_operation=lambda _ctx, request: received.append(request.image)
        or OperationResult(True, "check_ram_crc", "CPU1", "RAM_CHECK_CRC", {})
    )

    for task_id in ("crc-1", "crc-2"):
        result = backend.execute(
            task_id,
            ram_request(backend, path, CheckAdvancedRamCrcRequest),
            None,
            None,
        )
        assert result.status is TaskFinalStatus.SUCCEEDED

    assert len(preparations) == 3  # one automatic parse plus one per CRC task
    assert len(received) == 2 and received[0] is not received[1]


def test_ram_run_materializes_zero_times_and_reads_no_source(tmp_path, monkeypatch) -> None:
    received = []
    backend, path, preparations = connected_backend(
        tmp_path,
        run_ram_operation=lambda _ctx, request: received.append(request.entry_point)
        or OperationResult(True, "run_ram_image", "CPU1", "RUN_RAM", {}),
    )
    request = ram_request(backend, path, RunAdvancedRamImageRequest)
    path.unlink()
    trap = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Run accessed RAM source"))
    monkeypatch.setattr(backend, "_materialize_ram_app", trap)
    monkeypatch.setattr(backend, "_resolve_local_image", trap)
    monkeypatch.setattr(backend, "_fingerprint", trap)
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000", trap)
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.ImageMaterializationWorkspace",
        trap,
    )

    result = backend.execute("run", request, None, None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(preparations) == 1 and received == [request.expected_image_identity.entry_point]
    assert result.completion_action is TaskCompletionAction.RELEASE_CONNECTION


def test_ram_load_crc_publish_operation_started_with_task_cpu_and_generation(tmp_path) -> None:
    backend, path, _ = connected_backend(
        tmp_path,
        load_ram_operation=ok("load", []),
        check_ram_crc_operation=ok("crc", []),
    )
    transitions = []
    backend.subscribe_runtime_v2(transitions.append)

    backend.execute("load-event", ram_request(backend, path, LoadAdvancedRamImageRequest), None, None)
    backend.execute("crc-event", ram_request(backend, path, CheckAdvancedRamCrcRequest), None, None)

    events = [item.source_event for item in transitions if isinstance(item.source_event, OperationStarted)]
    assert events == [
        OperationStarted("load-event", RuntimeCpuId.CPU1, backend.connection_generation),
        OperationStarted("crc-event", RuntimeCpuId.CPU1, backend.connection_generation),
    ]


def test_ram_operations_are_independent_and_use_batch14c_adapter(tmp_path) -> None:
    calls = []
    backend, path, _ = connected_backend(
        tmp_path,
        load_ram_operation=ok("load", calls, progress=True),
        check_ram_crc_operation=ok("check", calls),
        run_ram_operation=ok("run", calls),
    )
    events = []
    load = backend.execute("load", ram_request(backend, path, LoadAdvancedRamImageRequest), object(), events.append)
    check = backend.execute("check", ram_request(backend, path, CheckAdvancedRamCrcRequest), object(), events.append)
    run = backend.execute("run", ram_request(backend, path, RunAdvancedRamImageRequest), object(), events.append)

    assert [item[0] for item in calls] == ["load", "check", "run"]
    assert calls[0][1].cancellation is not None
    assert calls[1][1].cancellation is None and calls[2][1].cancellation is None
    progress = [event for event in events if event.step_state is TaskStepState.PROGRESS]
    assert len(progress) == 1 and progress[0].raw_event.stage == "RAM_LOAD_DATA"
    assert load.status is check.status is run.status is TaskFinalStatus.SUCCEEDED
    assert run.completion_action is TaskCompletionAction.RELEASE_CONNECTION


def test_same_path_ram_identity_change_rejects_before_domain_operation(tmp_path) -> None:
    backend, path, _ = connected_backend(tmp_path, load_ram_operation=ok("load", []))
    assert backend.execute("x", ram_request(backend, path, LoadAdvancedRamImageRequest, connection="old"), None, None).error.code == "STALE_CONNECTION"
    assert backend.execute("x", ram_request(backend, path, LoadAdvancedRamImageRequest, target="cpu2"), None, None).error.code == "STALE_TARGET"
    expected = backend.target_resources[RuntimeCpuId.CPU1].ram_image_summary.identity
    backend.set_ram_image_path("cpu1", str(path))
    empty_request = LoadAdvancedRamImageRequest("connection", "cpu1", str(path), 1, backend.configuration_revision, expected)
    assert backend.execute("x", empty_request, None, None).error.code == "PREPARED_RAM_IMAGE_REQUIRED"
    backend.begin_ram_image_parse("cpu1", str(path), 1)
    backend.execute("prepare2", PrepareRamImageRequest("cpu1", str(path), 1), None, None)
    path.write_text("changed", encoding="ascii")
    backend._prepare_ram_operation = lambda *_a, **_k: replace(
        prepared(), image_crc32=0x87654321
    )
    assert backend.execute("x", ram_request(backend, path, LoadAdvancedRamImageRequest, revision=1), None, None).error.code == "IMAGE_CHANGED"
    assert backend.target_resources[RuntimeCpuId.CPU1].ram_image_parse_status is ImageParseStatus.ERROR
    assert backend.target_resources[RuntimeCpuId.CPU2].ram_image_parse_status is ImageParseStatus.EMPTY


def test_current_missing_ram_source_marks_only_current_cpu_error_without_revision_change(tmp_path) -> None:
    calls = []
    backend, path, _ = connected_backend(
        tmp_path, load_ram_operation=ok("load", calls)
    )
    request = ram_request(backend, path, LoadAdvancedRamImageRequest)
    revision = backend.ram_image_revision("cpu1")
    cpu2 = backend.target_resources[RuntimeCpuId.CPU2]
    transitions = []
    backend.subscribe_runtime_v2(transitions.append)
    path.unlink()

    result = backend.execute("missing", request, None, None)

    state = backend.target_resources[RuntimeCpuId.CPU1]
    assert result.error.code == "IMAGE_FILE_NOT_FOUND" and calls == []
    assert backend.ram_image_revision("cpu1") == revision
    assert state.ram_image_parse_status is ImageParseStatus.ERROR
    assert state.ram_image_summary is None
    assert state.ram_image_parse_error.startswith("Code: IMAGE_FILE_NOT_FOUND\n")
    assert backend.target_resources[RuntimeCpuId.CPU2] == cpu2
    assert len(
        [item for item in transitions if isinstance(item.source_event, OperationStarted)]
    ) == 1


def test_cpu2_unsupported_capabilities_are_rejected_without_profile_changes(tmp_path) -> None:
    backend, path, _ = connected_backend(tmp_path)
    backend._target = CPU2_PROFILE
    backend._connection_info = ConnectionInfo("cpu2", "SCI", "COM3", datetime.now(timezone.utc), "cpu2")
    backend.set_ram_image_path("cpu2", str(path))
    backend.begin_ram_image_parse("cpu2", str(path), 1)
    assert backend.execute("prep2", PrepareRamImageRequest("cpu2", str(path), 1), None, None).status is TaskFinalStatus.SUCCEEDED
    result = backend.execute("load", ram_request(backend, path, LoadAdvancedRamImageRequest, connection="cpu2", target="cpu2", revision=1), None, None)
    assert result.status is TaskFinalStatus.FAILED and result.error.code == "UNSUPPORTED_OPERATION"
    assert CPU2_PROFILE.command_set.ram_load_begin is None


def test_load_preserves_cancellation_outcomes_and_cleanup_disposition(tmp_path) -> None:
    cancellation = OperationCancellationInfo("RAM_LOAD_END", 3, 3, True, False, False)

    def completed(ctx, request):
        return OperationResult(True, "load_ram_image", ctx.target.name, "RAM_LOAD_END", {}, completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST, cancellation=cancellation)

    backend, path, _ = connected_backend(tmp_path, load_ram_operation=completed)
    result = backend.execute("load", ram_request(backend, path, LoadAdvancedRamImageRequest), object(), None)
    assert result.status is TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST

    uncertain = OperationCancellationInfo("RAM_LOAD_END", 1, 3, False, True, True, recovery_action="RECONNECT_AND_RESTART_RAM_LOAD")

    def failed(ctx, request):
        return OperationResult(False, "load_ram_image", ctx.target.name, "RAM_LOAD_END", {}, error=OperationErrorInfo("CANCELLATION_CLEANUP_FAILED", "cleanup", "RAM_LOAD_END", True), cancellation=uncertain)

    backend._load_ram_operation = failed
    result = backend.execute("failed", ram_request(backend, path, LoadAdvancedRamImageRequest), object(), None)
    assert result.status is TaskFinalStatus.FAILED
    assert result.error.disposition is ErrorDisposition.ASK_DISCONNECT


def test_clean_load_cancellation_preserves_connection(tmp_path) -> None:
    cancellation = OperationCancellationInfo("RAM_LOAD_END", 1, 3, True, False, False, recovery_action="RESTART_RAM_LOAD")

    def cancelled(ctx, request):
        return OperationResult(False, "load_ram_image", ctx.target.name, "RAM_LOAD_END", {}, completion=OperationCompletion.CANCELLED, cancellation=cancellation)

    backend, path, _ = connected_backend(tmp_path, load_ram_operation=cancelled)
    session = backend.active_session
    result = backend.execute("load", ram_request(backend, path, LoadAdvancedRamImageRequest), object(), None)
    assert result.status is TaskFinalStatus.CANCELLED
    assert result.completion_action is TaskCompletionAction.NONE
    assert backend.active_session is session


def test_backend_retains_no_complete_ram_image_across_disconnect(tmp_path) -> None:
    backend, path, _ = connected_backend(tmp_path)
    backend.set_ram_image_path("cpu2", str(path))
    backend._clear_active()
    assert not hasattr(backend, "_prepared_ram_images")
    assert not hasattr(backend, "prepared_ram_image_cache")


def test_out_ram_preparation_uses_scoped_workspace_and_cleans_it(tmp_path, monkeypatch) -> None:
    source = tmp_path / "ram.out"
    source.write_bytes(b"out")
    executable = tmp_path / "hex2000.exe"
    executable.touch()
    root = tmp_path / "sci8-root"
    observed = []

    def prepare_image(path, **kwargs):
        output = Path(kwargs["sci8_txt"])
        observed.append((Path(path), output, output.parent.is_dir()))
        output.write_text("generated", encoding="ascii")
        return replace(prepared(), generated_sci8_txt=output)

    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000", lambda *_a, **_k: executable)
    backend = RuntimeBackend(
        hex2000_executable_path=executable,
        sci8_temp_dir=root,
        prepare_ram_operation=prepare_image,
    )
    result = backend.execute("prepare", PrepareRamImageRequest("cpu1", str(source), 0), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert observed[0][0] == source.resolve() and observed[0][2]
    assert observed[0][1].parent.parent == root
    assert list(root.iterdir()) == []
    assert not hasattr(backend, "_prepared_ram_images")
    assert backend.sci8_temp_dir == str(root)


def test_out_ram_preparation_cleans_workspace_on_failure_and_txt_creates_none(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "hex2000.exe"; executable.touch()
    source = tmp_path / "ram.out"; source.write_bytes(b"out")
    root = tmp_path / "sci8-root"
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000", lambda *_a, **_k: executable)
    backend = RuntimeBackend(
        hex2000_executable_path=executable,
        sci8_temp_dir=root,
        prepare_ram_operation=lambda *_a, **_k: (_ for _ in ()).throw(ValueError("invalid")),
    )
    assert backend.execute("prepare", PrepareRamImageRequest("cpu1", str(source), 0), None, None).status is TaskFinalStatus.FAILED
    assert list(root.iterdir()) == []

    txt = tmp_path / "ram.txt"; txt.write_text("user", encoding="ascii")
    original = txt.read_bytes()
    calls = []
    direct = RuntimeBackend(
        sci8_temp_dir=tmp_path / "unused",
        prepare_ram_operation=lambda path, **kwargs: calls.append((path, kwargs)) or prepared(),
    )
    assert direct.execute("txt", PrepareRamImageRequest("cpu1", str(txt), 0), None, None).status is TaskFinalStatus.SUCCEEDED
    assert "sci8_txt" not in calls[0][1]
    assert txt.read_bytes() == original
    assert not (tmp_path / "unused").exists()


def _connected_out_operation_backend(tmp_path, monkeypatch, **operations):
    executable = tmp_path / "hex2000.exe"
    executable.touch()
    source = tmp_path / "ram.out"
    source.write_bytes(b"out")
    root = tmp_path / "sci8-root"
    prepared_objects = []

    def prepare_image(_path, **kwargs):
        output = Path(kwargs["sci8_txt"])
        output.write_text("generated", encoding="ascii")
        value = replace(prepared(), generated_sci8_txt=output)
        prepared_objects.append(value)
        return value

    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000",
        lambda *_a, **_k: executable,
    )
    backend = connect_backend(
        RuntimeBackend(
            hex2000_executable_path=executable,
            sci8_temp_dir=root,
            prepare_ram_operation=prepare_image,
            **operations,
        )
    )
    result = backend.execute(
        "prepare", PrepareRamImageRequest("cpu1", str(source), 0), None, None
    )
    assert result.status is TaskFinalStatus.SUCCEEDED and list(root.iterdir()) == []
    return backend, source, root, prepared_objects


def test_out_ram_load_success_cleanup(tmp_path, monkeypatch) -> None:
    received = []

    def load(_ctx, request):
        received.append(request.image)
        return OperationResult(True, "load_ram_image", "CPU1", "RAM_LOAD_END", {})

    backend, source, root, prepared_objects = _connected_out_operation_backend(
        tmp_path, monkeypatch, load_ram_operation=load
    )
    result = backend.execute(
        "load", ram_request(backend, source, LoadAdvancedRamImageRequest), None, None
    )
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert list(root.iterdir()) == [] and received[0].generated_sci8_txt is None
    assert received[0] is not prepared_objects[0]


def test_out_ram_load_failure_cancellation_and_exception_cleanup(tmp_path, monkeypatch) -> None:
    backend, source, root, _prepared_objects = _connected_out_operation_backend(
        tmp_path,
        monkeypatch,
        load_ram_operation=ok("load", []),
    )

    backend._load_ram_operation = lambda _ctx, _request: OperationResult(
        False,
        "load_ram_image",
        "CPU1",
        "RAM_LOAD_END",
        {},
        error=OperationErrorInfo("LOAD_FAILED", "failed", "RAM_LOAD_END", False),
    )
    failed = backend.execute(
        "load-failed", ram_request(backend, source, LoadAdvancedRamImageRequest), None, None
    )
    assert failed.status is TaskFinalStatus.FAILED and list(root.iterdir()) == []

    cancellation = OperationCancellationInfo("RAM_LOAD_DATA", 1, 3, True, False, False)
    backend._load_ram_operation = lambda _ctx, _request: OperationResult(
        False,
        "load_ram_image",
        "CPU1",
        "RAM_LOAD_DATA",
        {},
        completion=OperationCompletion.CANCELLED,
        cancellation=cancellation,
    )
    cancelled = backend.execute(
        "load-cancelled", ram_request(backend, source, LoadAdvancedRamImageRequest), object(), None
    )
    assert cancelled.status is TaskFinalStatus.CANCELLED and list(root.iterdir()) == []

    backend._prepare_ram_operation = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("unexpected")
    )
    with pytest.raises(RuntimeError, match="unexpected"):
        backend.execute(
            "load-exception", ram_request(backend, source, LoadAdvancedRamImageRequest), None, None
        )
    assert list(root.iterdir()) == []


def test_out_ram_crc_cleanup(tmp_path, monkeypatch) -> None:
    received = []
    backend, source, root, _prepared_objects = _connected_out_operation_backend(
        tmp_path,
        monkeypatch,
        check_ram_crc_operation=lambda _ctx, request: received.append(request.image)
        or OperationResult(True, "check_ram_crc", "CPU1", "RAM_CHECK_CRC", {}),
    )

    result = backend.execute(
        "crc", ram_request(backend, source, CheckAdvancedRamCrcRequest), None, None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert list(root.iterdir()) == [] and received[0].generated_sci8_txt is None


def test_txt_ram_operation_is_read_only_and_creates_no_workspace(tmp_path) -> None:
    backend, source, _ = connected_backend(
        tmp_path, load_ram_operation=ok("load", [])
    )
    original = source.read_bytes()
    root = tmp_path / "unused"
    backend._sci8_temp_dir = str(root)

    result = backend.execute(
        "load", ram_request(backend, source, LoadAdvancedRamImageRequest), None, None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert source.read_bytes() == original and not root.exists()


def test_txt_ram_operation_ignores_unrelated_tool_revision_change(tmp_path) -> None:
    calls = []
    backend, source, preparations = connected_backend(
        tmp_path, load_ram_operation=ok("load", calls)
    )
    request = replace(
        ram_request(backend, source, LoadAdvancedRamImageRequest),
        image_tool_configuration_revision=backend.configuration_revision + 10,
    )

    result = backend.execute("load", request, None, None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert len(preparations) == 2 and [item[0] for item in calls] == ["load"]


def test_out_ram_operation_rejects_tool_revision_before_materialization(tmp_path, monkeypatch) -> None:
    calls = []
    backend, source, _root, prepared_objects = _connected_out_operation_backend(
        tmp_path, monkeypatch, load_ram_operation=ok("load", calls)
    )
    request = replace(
        ram_request(backend, source, LoadAdvancedRamImageRequest),
        image_tool_configuration_revision=backend.configuration_revision + 1,
    )
    transitions = []
    backend.subscribe_runtime_v2(transitions.append)

    result = backend.execute("load", request, None, None)

    assert result.error.code == "STALE_IMAGE_CONFIGURATION"
    assert len(prepared_objects) == 1 and calls == []
    assert not any(isinstance(item.source_event, OperationStarted) for item in transitions)


def test_default_out_ram_parse_drops_deleted_materialization_path(tmp_path, monkeypatch) -> None:
    source = tmp_path / "ram.out"
    source.write_bytes(b"out")
    executable = tmp_path / "hex2000.exe"
    executable.touch()
    root = tmp_path / "sci8-root"
    generated = []

    def convert(_source, output, **_kwargs):
        output = Path(output)
        output.write_text(_ram_sci8_text(), encoding="ascii")
        assert output.exists()
        generated.append(output)

    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000",
        lambda *_args, **_kwargs: executable,
    )
    monkeypatch.setattr("bootloader_upgrade_tool.images.models.run_hex2000", convert)
    backend = RuntimeBackend(hex2000_executable_path=executable, sci8_temp_dir=root)

    result = backend.execute(
        "prepare", PrepareRamImageRequest("cpu1", str(source), 0), None, None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert generated and not generated[0].parent.exists()
    assert list(root.iterdir()) == []
    assert not hasattr(backend, "_prepared_ram_images")
    assert result.payload.hex2000_executable == str(executable)


def test_default_txt_ram_preparation_preserves_source_and_source_path(tmp_path) -> None:
    source = tmp_path / "ram.txt"
    source.write_text(_ram_sci8_text(), encoding="ascii")
    original = source.read_bytes()
    root = tmp_path / "unused"
    backend = RuntimeBackend(sci8_temp_dir=root)

    result = backend.execute(
        "prepare", PrepareRamImageRequest("cpu1", str(source), 0), None, None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert source.read_bytes() == original
    assert not root.exists()
    assert not hasattr(backend, "_prepared_ram_images")


def test_out_ram_parse_retains_no_unrelated_compatibility_path(tmp_path, monkeypatch) -> None:
    source = tmp_path / "ram.out"
    source.write_bytes(b"out")
    executable = tmp_path / "hex2000.exe"
    executable.touch()
    unrelated = tmp_path / "compatibility.sci8.txt"
    unrelated.write_text("compatibility", encoding="ascii")
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000",
        lambda *_args, **_kwargs: executable,
    )
    backend = RuntimeBackend(
        hex2000_executable_path=executable,
        sci8_temp_dir=tmp_path / "sci8-root",
        prepare_ram_operation=lambda *_args, **_kwargs: replace(
            prepared(), generated_sci8_txt=unrelated
        ),
    )

    result = backend.execute(
        "prepare", PrepareRamImageRequest("cpu1", str(source), 0), None, None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert unrelated.exists()
    assert not hasattr(backend, "_prepared_ram_images")
