from dataclasses import FrozenInstanceError

import pytest

from bootloader_upgrade_tool.gui.flash_service_models import (
    DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
    FlashServiceResourceState,
    FlashServiceResourceStatus,
    PrepareFlashServiceRequest,
    PreparedFlashServiceSummary,
)
from bootloader_upgrade_tool.gui.image_preparation_models import (
    Hex2000Source,
    ImageSourceKind,
    SourceFileFingerprint,
)


def summary(tmp_path):
    image = tmp_path / "service.txt"; image.write_text("image")
    map_file = tmp_path / "service.map"; map_file.write_text("map")
    fingerprint = lambda path: SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)
    return PreparedFlashServiceSummary(
        "cpu1", "Provider", str(image), str(map_file), DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
        1, 2, ImageSourceKind.TXT, fingerprint(image), fingerprint(map_file),
        0x9000, 0x9010, 0x9020, 8, 1, 3, Hex2000Source.NOT_USED, None,
    )


def test_service_request_contains_revisions_only() -> None:
    request = PrepareFlashServiceRequest(1, 2)
    assert request.resource_revision == 1
    assert not hasattr(request, "service_image_path")
    assert not hasattr(request, "service_map_path")
    assert not hasattr(request, "descriptor_symbol")
    plan = request.create_plan("task")
    assert plan.connection_requirement.name == "NONE"
    assert plan.cancellable is False


def test_service_request_is_cpu1_only() -> None:
    with pytest.raises(ValueError, match="cpu1"):
        PrepareFlashServiceRequest(0, 0, "cpu2")


def test_resource_state_is_frozen_slotted_and_validates_invariants(tmp_path) -> None:
    ready_summary = summary(tmp_path)
    state = FlashServiceResourceState(
        1, "Provider", ready_summary.service_image_path, ready_summary.service_map_path,
        FlashServiceResourceStatus.READY, ready_summary,
    )
    with pytest.raises(FrozenInstanceError):
        state.revision = 2
    assert not hasattr(state, "__dict__")
    with pytest.raises(ValueError):
        FlashServiceResourceState(True, "Provider", None, None, FlashServiceResourceStatus.UNAVAILABLE, error_code="X", error_message="x")
    with pytest.raises(ValueError, match="READY"):
        FlashServiceResourceState(1, "Provider", ready_summary.service_image_path, ready_summary.service_map_path, FlashServiceResourceStatus.READY)
    with pytest.raises(ValueError, match="explicit error"):
        FlashServiceResourceState(1, "Provider", None, None, FlashServiceResourceStatus.UNAVAILABLE)


def test_summary_is_lightweight_and_strict(tmp_path) -> None:
    value = summary(tmp_path)
    assert value.descriptor_symbol == DEFAULT_SERVICE_DESCRIPTOR_SYMBOL
    assert not hasattr(value, "image")
    assert not hasattr(value, "generated_sci8_txt")
    with pytest.raises(ValueError, match="canonical"):
        PreparedFlashServiceSummary(
            "cpu1", "Provider", value.service_image_path, value.service_map_path, "other",
            1, 2, value.image_source_kind, value.image_fingerprint, value.map_fingerprint,
            1, 2, 3, 8, 4, 3, value.hex2000_source, None,
        )
