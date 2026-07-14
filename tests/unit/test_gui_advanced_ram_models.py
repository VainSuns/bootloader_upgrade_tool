import pytest

from bootloader_upgrade_tool.gui.advanced_ram_models import (
    CheckAdvancedRamCrcRequest,
    LoadAdvancedRamImageRequest,
    PrepareRamImageRequest,
    RunAdvancedRamImageRequest,
)
from bootloader_upgrade_tool.gui.runtime_models import TaskConnectionRequirement


def test_ram_requests_have_independent_operation_plans() -> None:
    prepare = PrepareRamImageRequest("cpu2", "cpu2.out", 3).create_plan("prepare")
    load = LoadAdvancedRamImageRequest("connection", "cpu1", 4).create_plan("load")
    check = CheckAdvancedRamCrcRequest("connection", "cpu1", 4).create_plan("check")
    run = RunAdvancedRamImageRequest("connection", "cpu1", 4).create_plan("run")

    assert prepare.connection_requirement is TaskConnectionRequirement.NONE
    assert [plan.steps[0].step_id for plan in (load, check, run)] == [
        "load_ram_image",
        "check_ram_crc",
        "run_ram_image",
    ]
    assert load.cancellable and not check.cancellable and not run.cancellable


@pytest.mark.parametrize("target", ["", "cpu3"])
def test_ram_requests_reject_unknown_targets(target) -> None:
    with pytest.raises(ValueError):
        PrepareRamImageRequest(target, "image.out", 0)
