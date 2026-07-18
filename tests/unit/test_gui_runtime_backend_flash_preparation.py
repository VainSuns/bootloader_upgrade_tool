from pathlib import Path

import pytest

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_flash_models import PrepareAdvancedFlashImageRequest
from bootloader_upgrade_tool.gui.image_preparation_models import PrepareFlashImageRequest
from bootloader_upgrade_tool.gui.flash_service_models import (
    DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
    FlashServiceResourceState,
    FlashServiceResourceStatus,
    PrepareFlashServiceRequest,
    PreparedFlashServiceSummary,
)
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import TaskFinalStatus
from bootloader_upgrade_tool.images import ImageIdentity, PreparedFlashImage, PreparedServiceImage
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


def _image() -> FirmwareImage:
    return FirmwareImage(
        source_out_file="source",
        generated_hex_file="generated",
        entry_point=0x82400,
        blocks=[FirmwareBlock(0x82400, range(8))],
        file_checksum="sum",
        format_info={},
    )


def _flash() -> PreparedFlashImage:
    return PreparedFlashImage(_image(), ImageIdentity(0x82400, 8, 1, 0x82408), 2)


def test_program_parser_populates_one_compatibility_cache_per_target(tmp_path, monkeypatch) -> None:
    one, two = tmp_path / "one.txt", tmp_path / "two.txt"
    one.write_text("one"); two.write_text("two")
    targets = []
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", lambda *_a, **kw: targets.append(kw["target"]) or _flash())
    backend = RuntimeBackend()
    one_revision = backend.set_program_image_path("cpu1", str(one))
    two_revision = backend.set_program_image_path("cpu2", str(two))
    assert backend.execute("one", PrepareFlashImageRequest("cpu1", str(one.resolve()), one_revision), None, None).status is TaskFinalStatus.SUCCEEDED
    assert backend.execute("two", PrepareFlashImageRequest("cpu2", str(two.resolve()), two_revision), None, None).status is TaskFinalStatus.SUCCEEDED
    assert targets == [CPU1_PROFILE, CPU2_PROFILE]
    assert isinstance(backend.prepared_advanced_flash_image_cache("cpu1")[0], PreparedFlashImage)
    assert isinstance(backend.prepared_advanced_flash_image_cache("cpu2")[0], PreparedFlashImage)
    assert backend.prepared_ram_image_cache("cpu1") is None

    one.write_text("changed")
    assert backend.prepared_advanced_flash_image_cache("cpu1") is None
    assert backend.prepared_advanced_flash_image_cache("cpu2") is not None
    backend.set_image_tool_paths("hex2000.exe", "temp")
    assert backend.prepared_advanced_flash_image_cache("cpu2") is not None

    with pytest.raises(NotImplementedError, match="owned by Program Image"):
        backend.execute("advanced", PrepareAdvancedFlashImageRequest("cpu1", str(one), 1, 0), None, None)


def test_cpu2_validation_failure_is_clean_and_profile_is_unchanged(tmp_path, monkeypatch) -> None:
    source = tmp_path / "cpu2.txt"; source.write_text("cpu2")
    original = CPU2_PROFILE
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("missing Flash contract")))
    backend = RuntimeBackend()
    revision = backend.set_program_image_path("cpu2", str(source))
    result = backend.execute("task", PrepareFlashImageRequest("cpu2", str(source.resolve()), revision), None, None)
    assert result.error.code == "IMAGE_VALIDATION_FAILED"
    assert backend.prepared_advanced_flash_image_cache("cpu2") is None
    assert CPU2_PROFILE is original


class Provider:
    def __init__(self, image, map_file):
        self.image, self.map_file = image, map_file

    def flash_service_image_path(self):
        return self.image

    def flash_service_map_path(self):
        return self.map_file


def test_service_validation_retains_lightweight_state_only(tmp_path) -> None:
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image"); map_file.write_text("map")
    calls = []
    prepared = PreparedServiceImage(_image(), 0x9000, 0x9010, 0x9020, 8, 1, 3)
    backend = RuntimeBackend(
        app_resource_provider=Provider(image, map_file),
        prepare_service_operation=lambda *a, **kw: calls.append((a, kw)) or prepared,
    )
    revision = backend.service_configuration_revision
    result = backend.execute("service", PrepareFlashServiceRequest(revision, 0), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert calls[0][1]["descriptor_symbol"] == "g_boot_flash_service_descriptor"
    assert result.payload.descriptor_address == 0x9000
    assert calls[0][1]["target"] is CPU1_PROFILE
    assert calls[0][1]["work_dir"] is None
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.READY
    assert backend.flash_service_resource_state.summary == result.payload
    for name in (
        "_prepared_service_image", "_prepared_service_summary", "prepared_service_image_cache",
        "prepared_service_image", "prepared_service_summary", "invalidate_prepared_service_image",
    ):
        assert not hasattr(backend, name)
    assert all(not isinstance(value, PreparedServiceImage) for value in vars(backend).values())


def test_service_preparation_receives_injected_workspace_root(tmp_path) -> None:
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image"); map_file.write_text("map")
    calls = []
    prepared = PreparedServiceImage(_image(), 0x9000, 0x9010, 0x9020, 8, 1, 3)
    root = tmp_path / "sci8-root"
    backend = RuntimeBackend(
        sci8_temp_dir=root,
        app_resource_provider=Provider(image, map_file),
        prepare_service_operation=lambda *args, **kwargs: calls.append(kwargs) or prepared,
    )
    result = backend.execute(
        "service", PrepareFlashServiceRequest(backend.service_configuration_revision, 0), None, None
    )
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert calls[0]["work_dir"] == str(root)
    assert not root.exists()


def test_provider_configuration_is_one_time_and_exact_object(tmp_path) -> None:
    image = tmp_path / "service.txt"; image.write_text("image")
    map_file = tmp_path / "service.map"; map_file.write_text("map")
    one = Provider(image, map_file)
    backend = RuntimeBackend()
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.UNAVAILABLE
    backend.configure_app_resource_provider(one)
    state = backend.flash_service_resource_state
    backend.configure_app_resource_provider(one)
    assert backend.app_resource_provider is one
    assert backend.flash_service_resource_state is state
    with pytest.raises(RuntimeError, match="cannot be replaced"):
        backend.configure_app_resource_provider(Provider(image, map_file))


def test_forged_prepare_without_provider_returns_structured_failure() -> None:
    backend = RuntimeBackend()
    before = backend.flash_service_resource_state
    result = backend.execute("task", PrepareFlashServiceRequest(0, 0), None, None)
    assert result.status is TaskFinalStatus.FAILED
    assert result.error.code == "APP_RESOURCE_PROVIDER_REQUIRED"
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.UNAVAILABLE
    assert backend.flash_service_resource_state.revision == before.revision + 1


def test_session_and_txt_tool_change_preserve_ready_service_state(tmp_path) -> None:
    image = tmp_path / "service.txt"; image.write_text("image")
    map_file = tmp_path / "service.map"; map_file.write_text("map")
    prepared = PreparedServiceImage(_image(), 0x9000, 0x9010, 0x9020, 8, 1, 3)
    backend = RuntimeBackend(
        app_resource_provider=Provider(image, map_file),
        prepare_service_operation=lambda *_a, **_kw: prepared,
    )
    request = PrepareFlashServiceRequest(backend.service_configuration_revision, 0)
    assert backend.execute("prepare", request, None, None).status is TaskFinalStatus.SUCCEEDED
    ready = backend.flash_service_resource_state
    backend.apply_session_change()
    assert backend.flash_service_resource_state is ready
    backend.set_image_tool_paths("new.exe", "new-root")
    assert backend.flash_service_resource_state is ready


def test_txt_stale_tool_prepare_preserves_current_ready_state(tmp_path) -> None:
    image = tmp_path / "service.txt"; image.write_text("image")
    map_file = tmp_path / "service.map"; map_file.write_text("map")
    prepared = PreparedServiceImage(_image(), 0x9000, 0x9010, 0x9020, 8, 1, 3)
    backend = RuntimeBackend(
        app_resource_provider=Provider(image, map_file),
        prepare_service_operation=lambda *_a, **_kw: prepared,
    )
    request = PrepareFlashServiceRequest(backend.service_configuration_revision, 0)
    assert backend.execute("prepare", request, None, None).status is TaskFinalStatus.SUCCEEDED
    ready = backend.flash_service_resource_state
    backend.set_image_tool_paths("new.exe", "new-root")

    result = backend.execute("stale", request, None, None)

    assert result.status is TaskFinalStatus.FAILED
    assert result.error.code == "SERVICE_CONFIGURATION_CHANGED"
    assert backend.flash_service_resource_state is ready


def test_stale_resource_prepare_preserves_newer_state(tmp_path) -> None:
    image = tmp_path / "service.txt"; image.write_text("image")
    map_file = tmp_path / "service.map"; map_file.write_text("map")
    backend = RuntimeBackend(app_resource_provider=Provider(image, map_file))
    old_revision = backend.service_configuration_revision
    replacement = tmp_path / "replacement.txt"; replacement.write_text("replacement")
    backend.app_resource_provider.image = replacement
    newer = backend.refresh_flash_service_resources()

    result = backend.execute(
        "stale", PrepareFlashServiceRequest(old_revision, 0), None, None
    )

    assert result.error.code == "SERVICE_CONFIGURATION_CHANGED"
    assert backend.flash_service_resource_state is newer


def test_reload_changed_same_path_identity_increments_resource_revision(tmp_path) -> None:
    image = tmp_path / "service.txt"; image.write_text("image")
    map_file = tmp_path / "service.map"; map_file.write_text("map")
    prepared = PreparedServiceImage(_image(), 0x9000, 0x9010, 0x9020, 8, 1, 3)
    backend = RuntimeBackend(
        app_resource_provider=Provider(image, map_file),
        prepare_service_operation=lambda *_a, **_kw: prepared,
    )
    first = backend.execute(
        "first", PrepareFlashServiceRequest(backend.service_configuration_revision, 0), None, None
    )
    image.write_text("changed image")
    second = backend.execute(
        "second", PrepareFlashServiceRequest(backend.service_configuration_revision, 0), None, None
    )
    assert second.status is TaskFinalStatus.SUCCEEDED
    assert second.payload.resource_revision == first.payload.resource_revision + 1


def test_out_tool_change_invalidates_only_lightweight_state(tmp_path) -> None:
    image = tmp_path / "service.out"; image.write_text("image")
    map_file = tmp_path / "service.map"; map_file.write_text("map")
    provider = Provider(image, map_file)
    backend = RuntimeBackend(app_resource_provider=provider)
    fingerprint = lambda path: SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)
    summary = PreparedFlashServiceSummary(
        "cpu1", "Provider", str(image), str(map_file), DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
        backend.service_configuration_revision, 0, ImageSourceKind.OUT,
        fingerprint(image), fingerprint(map_file), 0x9000, 0x9010, 0x9020,
        8, 1, 3, Hex2000Source.GLOBAL_SETTINGS, str(tmp_path / "hex2000.exe"),
    )
    backend._flash_service_resource_state = FlashServiceResourceState(
        summary.resource_revision, "Provider", str(image), str(map_file),
        FlashServiceResourceStatus.READY, summary,
    )
    backend.set_image_tool_paths("changed.exe", "changed-root")
    state = backend.flash_service_resource_state
    assert state.revision == summary.resource_revision + 1
    assert state.status is FlashServiceResourceStatus.UNVALIDATED
    assert state.summary is None
    assert (state.image_path, state.map_path) == (str(image.resolve()), str(map_file.resolve()))
