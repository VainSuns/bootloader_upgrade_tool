import pytest

from bootloader_upgrade_tool.gui.advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    AdvancedFlashOperationSnapshot,
    AdvancedFlashOperationType,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
)
from bootloader_upgrade_tool.gui.runtime_models import CompletionPolicy, TaskConnectionRequirement
from bootloader_upgrade_tool.operations import OperationResult


IDENTITY = ("connection", "cpu1", 1, 2, 3, 2)


@pytest.mark.parametrize("request_type", [ProgramAdvancedFlashRequest, VerifyAdvancedFlashRequest])
def test_flash_operation_requests_create_connected_cancellable_acknowledged_plans(request_type) -> None:
    request = request_type(*IDENTITY)
    plan = request.create_plan("task")
    assert plan.connection_requirement is TaskConnectionRequirement.CONNECTED
    assert plan.cancellable
    assert plan.completion_policy is CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT
    assert len(plan.steps) == 1


def test_erase_scope_and_identity_validation() -> None:
    required = EraseAdvancedFlashRequest(
        *IDENTITY, AdvancedFlashEraseScope.REQUIRED_APP_SECTORS, 0x10
    )
    assert required.custom_sector_mask == 0
    custom = EraseAdvancedFlashRequest(
        *IDENTITY, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, 0x6
    )
    assert custom.custom_sector_mask == 0x6
    assert custom.create_plan("task").cancellable

    with pytest.raises(ValueError):
        ProgramAdvancedFlashRequest("", "cpu1", 0, 0, 0, 0)
    with pytest.raises(ValueError):
        ProgramAdvancedFlashRequest("c", "cpu2", 0, 0, 0, 0)
    with pytest.raises(ValueError):
        ProgramAdvancedFlashRequest("c", "cpu1", True, 0, 0, 0)
    with pytest.raises(ValueError):
        EraseAdvancedFlashRequest(*IDENTITY, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, 0)
    with pytest.raises(ValueError):
        EraseAdvancedFlashRequest(*IDENTITY, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, -1)


def test_result_snapshot_requires_typed_operation_and_erase_context() -> None:
    result = OperationResult(True, "erase_sector_mask", "CPU1", "ERASE", {})
    snapshot = AdvancedFlashOperationSnapshot(
        *IDENTITY,
        AdvancedFlashOperationType.ERASE,
        result,
        AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK,
        0x6,
    )
    assert snapshot.operation_result is result
    with pytest.raises(ValueError):
        AdvancedFlashOperationSnapshot(
            *IDENTITY,
            AdvancedFlashOperationType.PROGRAM_ONLY,
            result,
            AdvancedFlashEraseScope.REQUIRED_APP_SECTORS,
            0x2,
        )
