import pytest

from bootloader_upgrade_tool.gui.flash_service_models import PrepareFlashServiceRequest


def test_service_request_preserves_empty_default_symbol() -> None:
    request = PrepareFlashServiceRequest("service.out", "service.map", "  ", 1, 2)
    assert request.descriptor_symbol == ""
    assert request.create_plan("task").connection_requirement.name == "NONE"


def test_service_request_is_cpu1_only() -> None:
    with pytest.raises(ValueError, match="cpu1"):
        PrepareFlashServiceRequest("service.out", "service.map", "symbol", 0, 0, "cpu2")
