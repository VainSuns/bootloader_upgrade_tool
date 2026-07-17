from __future__ import annotations

from pathlib import Path
from threading import Barrier, Event, Thread

import pytest

from bootloader_upgrade_tool.firmware import Hex2000Error
from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.image_preparation_models import (
    Hex2000Source,
    ImageSourceKind,
    PrepareFlashImageRequest,
    SourceFileFingerprint,
)
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import TaskFinalStatus
from bootloader_upgrade_tool.gui.runtime_ports import CancellationToken, TaskWorkerJob
from bootloader_upgrade_tool.gui.workers import TaskWorker
from bootloader_upgrade_tool.images.models import ImageIdentity, PreparedFlashImage, load_firmware_image


def _sci8_text() -> str:
    words = [
        0x08AA,
        *([0] * 8),
        0x0008,
        0x2400,
        8,
        0x0008,
        0x2400,
        *range(8),
        0,
    ]
    return "\n".join(f"{word:04X}" for word in words)


def _prepared() -> PreparedFlashImage:
    image = FirmwareImage(
        source_out_file="app.out",
        generated_hex_file="app.txt",
        entry_point=0x082400,
        blocks=[FirmwareBlock(0x082400, range(8))],
        file_checksum="test",
        format_info={"format": "test"},
    )
    return PreparedFlashImage(image, ImageIdentity(0x082400, 8, 0x12345678, 0x082408), 0x2)


def test_default_out_materialization_is_unique_and_cleaned(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.out"
    source.write_bytes(b"out")
    root = tmp_path / "workspace-root"
    outputs = []

    def convert(_source, output, **_kwargs):
        outputs.append(Path(output))
        Path(output).write_text(_sci8_text(), encoding="ascii")

    monkeypatch.setattr("bootloader_upgrade_tool.images.models.run_hex2000", convert)
    first, generated = load_firmware_image(source, work_dir=root)
    second, generated_again = load_firmware_image(source, work_dir=root)

    assert first.entry_point == second.entry_point == 0x082400
    assert generated is generated_again is None
    assert outputs[0] != outputs[1]
    assert outputs[0].parent.parent == outputs[1].parent.parent == root
    assert list(root.iterdir()) == []


def test_default_out_materialization_cleans_conversion_and_parse_exceptions(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.out"
    source.write_bytes(b"out")
    root = tmp_path / "workspace-root"
    monkeypatch.setattr(
        "bootloader_upgrade_tool.images.models.run_hex2000",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cancelled")),
    )
    with pytest.raises(RuntimeError, match="cancelled"):
        load_firmware_image(source, work_dir=root)
    assert list(root.iterdir()) == []

    monkeypatch.setattr(
        "bootloader_upgrade_tool.images.models.run_hex2000",
        lambda _source, output, **_kwargs: Path(output).write_text("invalid", encoding="ascii"),
    )
    with pytest.raises(Exception):
        load_firmware_image(source, work_dir=root)
    assert list(root.iterdir()) == []


def test_concurrent_same_stem_materializations_never_share_output(tmp_path: Path, monkeypatch) -> None:
    sources = [tmp_path / name / "app.out" for name in ("one", "two")]
    for source in sources:
        source.parent.mkdir()
        source.write_bytes(b"out")
    root = tmp_path / "workspace-root"
    barrier = Barrier(2)
    outputs = []

    def convert(_source, output, **_kwargs):
        outputs.append(Path(output))
        Path(output).write_text(_sci8_text(), encoding="ascii")
        barrier.wait()

    monkeypatch.setattr("bootloader_upgrade_tool.images.models.run_hex2000", convert)
    failures = []
    threads = [Thread(target=lambda path=source: _load_or_record(path, root, failures)) for source in sources]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    assert len(set(outputs)) == 2
    assert list(root.iterdir()) == []


def _load_or_record(source: Path, root: Path, failures: list[Exception]) -> None:
    try:
        load_firmware_image(source, work_dir=root)
    except Exception as exc:
        failures.append(exc)


def test_txt_preparation_does_not_inspect_hex2000(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")
    monkeypatch.setenv("C2000_CG_ROOT", str(tmp_path / "missing"))
    backend = RuntimeBackend(hex2000_executable_path=str(tmp_path / "invalid.exe"))

    result = backend.execute("task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert result.payload.source_kind is ImageSourceKind.TXT
    assert result.payload.hex2000_source is Hex2000Source.NOT_USED
    assert result.payload.hex2000_executable is None
    assert backend.prepared_flash_image is not None


def test_out_preparation_uses_configured_hex2000_before_environment(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.out"
    source.write_bytes(b"out")
    configured = tmp_path / "configured.exe"
    configured.touch()
    environment = tmp_path / "compiler" / "bin" / "hex2000.exe"
    environment.parent.mkdir(parents=True)
    environment.touch()
    observed: list[Path | None] = []
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000",
        lambda configured_path, *, environ: (observed.append(Path(configured_path)), configured)[1],
    )
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image",
        lambda *args, **kwargs: _prepared(),
    )

    backend = RuntimeBackend(hex2000_executable_path=configured)
    result = backend.execute("task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert observed == [configured]
    assert result.payload.hex2000_source is Hex2000Source.GLOBAL_SETTINGS
    assert result.payload.hex2000_executable == str(configured)


def test_output_directory_is_used_for_temporary_conversion(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.out"
    source.write_bytes(b"out")
    executable = tmp_path / "hex2000.exe"
    executable.touch()
    output = tmp_path / "cache"
    observed = []
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.locate_hex2000", lambda *_a, **_k: executable)

    def prepare(*_args, **kwargs):
        observed.append(kwargs["work_dir"])
        return _prepared()

    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", prepare)
    result = RuntimeBackend(hex2000_executable_path=executable, sci8_temp_dir=output).execute(
        "task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert observed == [str(output)]


def test_invalid_configured_hex2000_does_not_fall_back(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.out"
    source.write_bytes(b"out")
    root = tmp_path / "compiler"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "hex2000.exe").touch()
    monkeypatch.setenv("C2000_CG_ROOT", str(root))
    backend = RuntimeBackend(hex2000_executable_path=str(tmp_path / "missing.exe"))

    result = backend.execute("task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None)

    assert result.status is TaskFinalStatus.FAILED
    assert result.error.code == "HEX2000_CONFIGURATION_INVALID"


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (Hex2000Error("tool failed"), "IMAGE_CONVERSION_FAILED"),
        (ValueError("invalid app"), "IMAGE_VALIDATION_FAILED"),
    ],
)
def test_preparation_maps_recoverable_failures(tmp_path: Path, monkeypatch, exception, code) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(exception),
    )

    backend = RuntimeBackend()
    result = backend.execute("task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None)

    assert result.status is TaskFinalStatus.FAILED
    assert result.error.code == code
    assert result.error.stage == "prepare_flash_image"
    assert result.error.recoverable is True
    assert backend.prepared_flash_image is None


def test_file_change_during_preparation_is_rejected(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")

    def prepare(*args, **kwargs):
        source.write_text(_sci8_text() + "\n", encoding="ascii")
        return _prepared()

    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", prepare)
    result = RuntimeBackend().execute(
        "task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None
    )

    assert result.error.code == "IMAGE_CHANGED_DURING_PREPARATION"


def test_stale_selection_revision_cannot_save_cache(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")
    backend = RuntimeBackend()
    backend.invalidate_prepared_image_cache(2)
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image",
        lambda *args, **kwargs: _prepared(),
    )

    result = backend.execute("task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None)

    assert result.error.code == "IMAGE_SELECTION_CHANGED"
    assert backend.prepared_image_summary is None


def test_only_cpu1_requests_are_valid() -> None:
    with pytest.raises(ValueError, match="only target_key 'cpu1'"):
        PrepareFlashImageRequest("cpu2", "app.txt", 0)


def test_empty_image_path_is_recoverable() -> None:
    result = RuntimeBackend().execute(
        "task", PrepareFlashImageRequest("cpu1", "", 0), None, lambda _: None
    )

    assert result.error.code == "INVALID_IMAGE_PATH"


def test_runtime_error_during_path_normalization_is_recoverable(monkeypatch) -> None:
    monkeypatch.setattr(Path, "expanduser", lambda _self: (_ for _ in ()).throw(RuntimeError("bad home")))
    result = RuntimeBackend().execute(
        "task", PrepareFlashImageRequest("cpu1", "~/app.txt", 0), None, lambda _: None
    )
    assert result.error.code == "INVALID_IMAGE_PATH"


def test_success_result_construction_failure_does_not_commit(tmp_path, monkeypatch) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")
    backend = RuntimeBackend()
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", lambda *_a, **_k: _prepared())
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.TaskExecutionResult", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("result bug")))
    with pytest.raises(RuntimeError, match="result bug"):
        backend.execute("task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None)
    assert backend.prepared_image_cache == (None, None)


def _seed_cache(backend: RuntimeBackend, revision: int = 1):
    prepared = _prepared()
    summary = backend._build_image_summary(
        PrepareFlashImageRequest("cpu1", "app.txt", revision),
        prepared,
        ImageSourceKind.TXT,
        SourceFileFingerprint(str(Path("app.txt").resolve()), 1, 1),
        Hex2000Source.NOT_USED,
        None,
    )
    with backend._image_lock:
        backend._image_selection_revision = revision
        backend._prepared_flash_image = prepared
        backend._prepared_image_summary = summary
    return prepared, summary


def test_revision_change_during_preparation_cannot_commit_stale_cache(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")
    started, release = Event(), Event()

    def prepare(*_args, **_kwargs):
        started.set()
        assert release.wait(2)
        return _prepared()

    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", prepare)
    backend = RuntimeBackend()
    results = []
    thread = Thread(
        target=lambda: results.append(
            backend.execute(
                "task",
                PrepareFlashImageRequest("cpu1", source, 1),
                None,
                lambda _: None,
            )
        )
    )
    thread.start()
    assert started.wait(2)
    backend.invalidate_prepared_image_cache(2)
    release.set()
    thread.join(2)

    assert results[0].error.code == "IMAGE_SELECTION_CHANGED"
    assert backend.prepared_image_cache == (None, None)


def test_reprepare_clears_old_cache_before_preparer_runs(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")
    backend = RuntimeBackend()
    _seed_cache(backend)

    def prepare(*_args, **_kwargs):
        assert backend.prepared_image_cache == (None, None)
        return _prepared()

    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", prepare)
    result = backend.execute(
        "task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert all(backend.prepared_image_cache)


def test_unexpected_preparer_exception_leaves_no_old_cache(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")
    backend = RuntimeBackend()
    _seed_cache(backend)
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bug")),
    )

    with pytest.raises(RuntimeError, match="bug"):
        backend.execute(
            "task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None
        )
    assert backend.prepared_image_cache == (None, None)


def test_old_expected_failure_does_not_clear_newer_cache(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")
    started, release = Event(), Event()

    def prepare(*_args, **_kwargs):
        started.set()
        assert release.wait(2)
        raise ValueError("old failure")

    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", prepare)
    backend, results = RuntimeBackend(), []
    thread = Thread(
        target=lambda: results.append(
            backend.execute(
                "task",
                PrepareFlashImageRequest("cpu1", source, 1),
                None,
                lambda _: None,
            )
        )
    )
    thread.start()
    assert started.wait(2)
    backend.invalidate_prepared_image_cache(2)
    newer = _seed_cache(backend, 2)
    release.set()
    thread.join(2)

    assert results[0].error.code == "IMAGE_VALIDATION_FAILED"
    assert backend.prepared_image_cache == newer


def test_current_behavior_program_cache_retains_prepared_image_and_summary() -> None:
    # Migration baseline only: Runtime V2 will remove this full-image cache.
    backend = RuntimeBackend()
    pair = _seed_cache(backend)
    assert backend.prepared_image_cache == pair
    assert isinstance(pair[0], PreparedFlashImage)
    assert pair[1] is not None
    assert backend.prepared_flash_image is pair[0]
    assert backend.prepared_image_summary is pair[1]
    for revision in (-1, True, "1"):
        with pytest.raises(ValueError):
            backend.invalidate_prepared_image_cache(revision)  # type: ignore[arg-type]


def test_unknown_request_is_contract_failure_and_worker_marks_fatal() -> None:
    backend = RuntimeBackend()
    with pytest.raises(NotImplementedError):
        backend.execute("task", object(), None, lambda _: None)

    worker = TaskWorker(
        "task",
        0,
        TaskWorkerJob("task", backend, object()),
        CancellationToken(),
    )
    results = []
    worker.resultReady.connect(results.append)
    worker.run()
    assert results[0].result.error.code == "WORKER_RUNTIME_FATAL"


def test_empty_configuration_uses_c2000_environment(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.out"
    source.write_bytes(b"out")
    executable = tmp_path / "compiler" / "bin" / "hex2000.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("C2000_CG_ROOT", str(executable.parents[1]))
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image",
        lambda *_args, **_kwargs: _prepared(),
    )

    result = RuntimeBackend(hex2000_executable_path="").execute(
        "task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert result.payload.hex2000_source is Hex2000Source.C2000_CG_ROOT
    assert result.payload.hex2000_executable == str(executable.resolve())


def test_global_settings_failure_applies_only_to_out(tmp_path: Path) -> None:
    out = tmp_path / "app.out"
    out.write_bytes(b"out")
    txt = tmp_path / "app.txt"
    txt.write_text(_sci8_text(), encoding="ascii")
    backend = RuntimeBackend(global_settings_error="")

    failed = backend.execute(
        "out", PrepareFlashImageRequest("cpu1", out, 1), None, lambda _: None
    )
    backend.invalidate_prepared_image_cache(2)
    succeeded = backend.execute(
        "txt", PrepareFlashImageRequest("cpu1", txt, 2), None, lambda _: None
    )

    assert failed.error.code == "GLOBAL_SETTINGS_LOAD_FAILED"
    assert succeeded.status is TaskFinalStatus.SUCCEEDED


def test_hex2000_not_found(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "app.out"
    source.write_bytes(b"out")
    monkeypatch.delenv("C2000_CG_ROOT", raising=False)
    result = RuntimeBackend().execute(
        "task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None
    )
    assert result.error.code == "HEX2000_NOT_FOUND"


@pytest.mark.parametrize("contents", (b"not a boot table", b"\xff\xfe"))
def test_malformed_or_non_ascii_sci8_is_parse_failure(tmp_path: Path, contents: bytes) -> None:
    source = tmp_path / "app.txt"
    source.write_bytes(contents)
    result = RuntimeBackend().execute(
        "task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None
    )
    assert result.error.code == "IMAGE_PARSE_FAILED"


@pytest.mark.parametrize(
    ("exception", "code"),
    (
        (FileNotFoundError("deleted"), "IMAGE_CHANGED_DURING_PREPARATION"),
        (OSError("read failed"), "IMAGE_FILE_ACCESS_FAILED"),
    ),
)
def test_source_errors_after_fingerprint_are_mapped(tmp_path: Path, monkeypatch, exception, code) -> None:
    source = tmp_path / "app.txt"
    source.write_text(_sci8_text(), encoding="ascii")
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(exception),
    )
    result = RuntimeBackend().execute(
        "task", PrepareFlashImageRequest("cpu1", source, 1), None, lambda _: None
    )
    assert result.error.code == code
    assert result.error.details["source_path"] == str(source.resolve())
    assert result.error.details["exception_type"] == type(exception).__name__
