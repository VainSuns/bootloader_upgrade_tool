from pathlib import Path

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_flash_models import PrepareAdvancedFlashImageRequest
from bootloader_upgrade_tool.gui.flash_service_models import PrepareFlashServiceRequest
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


def test_current_behavior_advanced_caches_retain_full_images_per_target(tmp_path, monkeypatch) -> None:
    # Migration baseline only: Runtime V2 will remove this full-image cache.
    one, two = tmp_path / "one.txt", tmp_path / "two.txt"
    one.write_text("one"); two.write_text("two")
    targets = []
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", lambda *_a, **kw: targets.append(kw["target"]) or _flash())
    backend = RuntimeBackend()
    backend.invalidate_prepared_advanced_flash_image("cpu1", 1)
    backend.invalidate_prepared_advanced_flash_image("cpu2", 1)
    assert backend.execute("one", PrepareAdvancedFlashImageRequest("cpu1", str(one), 1, 0), None, None).status is TaskFinalStatus.SUCCEEDED
    assert backend.execute("two", PrepareAdvancedFlashImageRequest("cpu2", str(two), 1, 0), None, None).status is TaskFinalStatus.SUCCEEDED
    assert targets == [CPU1_PROFILE, CPU2_PROFILE]
    assert isinstance(backend.prepared_advanced_flash_image_cache("cpu1")[0], PreparedFlashImage)
    assert isinstance(backend.prepared_advanced_flash_image_cache("cpu2")[0], PreparedFlashImage)
    assert backend.prepared_image_cache == (None, None)
    assert backend.prepared_ram_image_cache("cpu1") is None

    one.write_text("changed")
    assert backend.prepared_advanced_flash_image_cache("cpu1") is None
    assert backend.prepared_advanced_flash_image_cache("cpu2") is not None
    backend.set_image_tool_paths("hex2000.exe", "temp")
    assert backend.prepared_advanced_flash_image_cache("cpu2") is None


def test_cpu2_validation_failure_is_clean_and_profile_is_unchanged(tmp_path, monkeypatch) -> None:
    source = tmp_path / "cpu2.txt"; source.write_text("cpu2")
    original = CPU2_PROFILE
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_flash_app_image", lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("missing Flash contract")))
    backend = RuntimeBackend(); backend.invalidate_prepared_advanced_flash_image("cpu2", 1)
    result = backend.execute("task", PrepareAdvancedFlashImageRequest("cpu2", str(source), 1, 0), None, None)
    assert result.error.code == "UNSUPPORTED_OR_INVALID_IMAGE"
    assert backend.prepared_advanced_flash_image_cache("cpu2") is None
    assert CPU2_PROFILE is original


def test_current_behavior_service_cache_retains_full_prepared_image(tmp_path, monkeypatch) -> None:
    # Migration baseline only: Runtime V2 will remove this full-image cache.
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image"); map_file.write_text("map")
    calls = []
    prepared = PreparedServiceImage(_image(), 0x9000, 0x9010, 0x9020, 8, 1, 3)
    monkeypatch.setattr("bootloader_upgrade_tool.gui.runtime_backend.prepare_service_image", lambda *a, **kw: calls.append((a, kw)) or prepared)
    backend = RuntimeBackend(); backend.invalidate_prepared_service_image(1)
    result = backend.execute("service", PrepareFlashServiceRequest(str(image), str(map_file), "", 1, 0), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert "descriptor_symbol" not in calls[0][1]
    assert result.payload.descriptor_address == 0x9000
    assert calls[0][1]["target"] is CPU1_PROFILE
    assert calls[0][1]["work_dir"] is None
    assert backend.prepared_service_image_cache[0] is prepared
    assert isinstance(backend.prepared_service_image_cache[0], PreparedServiceImage)
    backend.invalidate_prepared_service_image(2)
    custom = backend.execute(
        "custom",
        PrepareFlashServiceRequest(str(image), str(map_file), "custom_descriptor", 2, 0),
        None,
        None,
    )
    assert custom.status is TaskFinalStatus.SUCCEEDED
    assert calls[1][1]["descriptor_symbol"] == "custom_descriptor"
    backend.set_image_tool_paths("new.exe", "temp")
    assert backend.prepared_service_image_cache is None


def test_service_preparation_receives_injected_workspace_root(tmp_path, monkeypatch) -> None:
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image"); map_file.write_text("map")
    calls = []
    prepared = PreparedServiceImage(_image(), 0x9000, 0x9010, 0x9020, 8, 1, 3)
    monkeypatch.setattr(
        "bootloader_upgrade_tool.gui.runtime_backend.prepare_service_image",
        lambda *args, **kwargs: calls.append(kwargs) or prepared,
    )
    root = tmp_path / "sci8-root"
    backend = RuntimeBackend(sci8_temp_dir=root)
    result = backend.execute(
        "service", PrepareFlashServiceRequest(str(image), str(map_file), "", 0, 0), None, None
    )
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert calls[0]["work_dir"] == str(root)
    assert not root.exists()
