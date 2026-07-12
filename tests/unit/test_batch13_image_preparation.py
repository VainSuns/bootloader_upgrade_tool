from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.firmware import Hex2000Error
from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.image_preparation_models import (
    Hex2000Source,
    ImageSourceKind,
    PrepareFlashImageRequest,
)
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import TaskFinalStatus
from bootloader_upgrade_tool.images.models import ImageIdentity, PreparedFlashImage


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
