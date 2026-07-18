from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from bootloader_upgrade_tool.gui.advanced_ram_models import (
    CheckAdvancedRamCrcRequest,
    AdvancedRamOperationSnapshot,
    AdvancedRamOperationType,
    LoadAdvancedRamImageRequest,
    PrepareRamImageRequest,
    RunAdvancedRamImageRequest,
)
from bootloader_upgrade_tool.images.models import RamImageIdentity
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.gui.runtime_models import TaskConnectionRequirement


IDENTITY = RamImageIdentity(0x8000, 3, 0x12345678)


def test_ram_requests_have_independent_operation_plans(tmp_path: Path) -> None:
    prepare = PrepareRamImageRequest("cpu2", "cpu2.out", 3).create_plan("prepare")
    path = str(tmp_path / "ram.txt")
    load = LoadAdvancedRamImageRequest("connection", "cpu1", path, 4, 2, IDENTITY).create_plan("load")
    check = CheckAdvancedRamCrcRequest("connection", "cpu1", path, 4, 2, IDENTITY).create_plan("check")
    run = RunAdvancedRamImageRequest("connection", "cpu1", 4, IDENTITY).create_plan("run")

    assert prepare.connection_requirement is TaskConnectionRequirement.NONE
    assert [plan.steps[0].step_id for plan in (load, check, run)] == [
        "load_ram_image",
        "check_ram_crc",
        "run_ram_image",
    ]
    assert load.cancellable and not check.cancellable and not run.cancellable


def test_ram_operation_requests_capture_only_immutable_inputs(tmp_path: Path) -> None:
    path = tmp_path / "ram.txt"
    load = LoadAdvancedRamImageRequest("connection", "cpu2", f"  {path}  ", 4, 2, IDENTITY)
    run = RunAdvancedRamImageRequest("connection", "cpu2", 4, IDENTITY)

    assert load.image_source_path == str(path.resolve())
    assert {field.name for field in fields(run)} == {
        "connection_id", "target_key", "selection_revision", "expected_image_identity"
    }
    assert not hasattr(load, "image") and not hasattr(run, "image_source_path")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        run.selection_revision = 5


def test_ram_operation_snapshot_is_lightweight() -> None:
    result = OperationResult(True, "run_ram_image", "CPU1", "RUN_RAM", {})
    snapshot = AdvancedRamOperationSnapshot(
        "connection", "cpu1", 4, IDENTITY, AdvancedRamOperationType.RUN, result
    )

    assert snapshot.image_identity is IDENTITY
    assert not hasattr(snapshot, "image")


@pytest.mark.parametrize("value", [True, -1])
def test_ram_operation_requests_reject_invalid_revisions(tmp_path: Path, value) -> None:
    with pytest.raises(ValueError):
        LoadAdvancedRamImageRequest("connection", "cpu1", str(tmp_path / "ram.txt"), value, 0, IDENTITY)


def test_ram_operation_requests_require_exact_positive_identity(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        RunAdvancedRamImageRequest("connection", "cpu1", 0, object())
    with pytest.raises(ValueError):
        CheckAdvancedRamCrcRequest(
            "connection", "cpu1", str(tmp_path / "ram.txt"), 0, 0,
            RamImageIdentity(0x8000, 0, 0),
        )


@pytest.mark.parametrize("target", ["", "cpu3"])
def test_ram_requests_reject_unknown_targets(target) -> None:
    with pytest.raises(ValueError):
        PrepareRamImageRequest(target, "image.out", 0)
