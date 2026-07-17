from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread

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
from bootloader_upgrade_tool.gui.runtime_v2_models import ImageParseStatus, RuntimeCpuId
from bootloader_upgrade_tool.gui.runtime_v2_events import RamImageChanged


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
    assert backend.prepared_ram_image_cache("cpu1") is None


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
    assert backend.prepared_ram_image_cache("cpu1") is None


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
    assert backend.prepared_ram_image_cache("cpu1") is None


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
    assert backend.prepared_ram_image_cache("cpu1")[1] == result.payload

    assert backend.set_ram_image_path("cpu1", f"  {path}  ") == 2
    assert backend.prepared_ram_image_cache("cpu1") is None
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
    txt_cache = backend.prepared_ram_image_cache("cpu2")

    backend.set_image_tool_paths(str(tmp_path / "new.exe"), str(tmp_path / "work"))

    cpu1 = backend.target_resources[RuntimeCpuId.CPU1]
    assert cpu1.ram_image_path == f"  {out}  "
    assert cpu1.ram_image_parse_status is ImageParseStatus.EMPTY
    assert backend.ram_image_revision("cpu1") == 2
    assert backend.prepared_ram_image_cache("cpu1") is None
    assert backend.target_resources[RuntimeCpuId.CPU2] == txt_state
    assert backend.ram_image_revision("cpu2") == 1
    assert backend.prepared_ram_image_cache("cpu2") == txt_cache


def test_session_change_resets_ram_revisions_resources_and_caches(tmp_path) -> None:
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
        and backend.prepared_ram_image_cache(cpu.value) is None
        for cpu in RuntimeCpuId
    )


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
    backend.set_ram_image_path("cpu1", str(path))
    assert backend.execute("x", LoadAdvancedRamImageRequest("connection", "cpu1", 1), None, None).error.code == "PREPARED_RAM_IMAGE_REQUIRED"
    backend.begin_ram_image_parse("cpu1", str(path), 1)
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
    backend.set_ram_image_path("cpu2", str(path))
    backend.begin_ram_image_parse("cpu2", str(path), 1)
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
    backend.set_ram_image_path("cpu2", str(path))
    backend._clear_active()
    assert backend.prepared_ram_image_cache("cpu1") == cpu1
    assert backend.prepared_ram_image_cache("cpu2") is None


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
    assert backend.prepared_ram_image_cache("cpu1")[0].generated_sci8_txt is None
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


def test_default_out_ram_cache_drops_deleted_materialization_path(tmp_path, monkeypatch) -> None:
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
    cached, summary = backend.prepared_ram_image_cache("cpu1")
    assert generated and not generated[0].parent.exists()
    assert list(root.iterdir()) == []
    assert cached.generated_sci8_txt is None
    assert (cached.entry_point, cached.total_words, cached.image_crc32) == (
        summary.entry_point,
        summary.image_size_words,
        summary.image_crc32,
    )


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
    cached, _summary = backend.prepared_ram_image_cache("cpu1")
    assert cached.generated_sci8_txt == str(source.resolve())
    assert source.read_bytes() == original
    assert not root.exists()


def test_out_ram_cache_preserves_unrelated_compatibility_path(tmp_path, monkeypatch) -> None:
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
    cached, _summary = backend.prepared_ram_image_cache("cpu1")
    assert cached.generated_sci8_txt == unrelated
    assert unrelated.exists()
