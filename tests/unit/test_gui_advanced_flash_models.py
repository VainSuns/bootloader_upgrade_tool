import pytest

from bootloader_upgrade_tool.gui.advanced_flash_models import PrepareAdvancedFlashImageRequest


def test_request_supports_both_targets_and_local_plan() -> None:
    for target in ("cpu1", "cpu2"):
        request = PrepareAdvancedFlashImageRequest(target, "app.txt", 2, 3)
        plan = request.create_plan("task")
        assert plan.connection_requirement.name == "NONE"
        assert target.upper() in plan.title


def test_request_rejects_invalid_identity() -> None:
    with pytest.raises(ValueError):
        PrepareAdvancedFlashImageRequest("cpu3", "app.txt", 0, 0)
    with pytest.raises(ValueError):
        PrepareAdvancedFlashImageRequest("cpu1", "app.txt", -1, 0)
