from dataclasses import FrozenInstanceError
from types import MappingProxyType

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
from bootloader_upgrade_tool.images import ImageIdentity


IDENTITY = ("connection", "cpu1", 1, 2, 3, 2)
REQUEST = (
    "connection", "cpu1", "app.txt", 1, 2,
    ImageIdentity(0x82000, 8, 0x1234, 0x82008), 0x2, 3, 2,
)
REQUEST_FIELDS = (
    "connection_id", "target_key", "image_source_path", "image_selection_revision",
    "image_tool_configuration_revision", "expected_image_identity",
    "expected_effective_sector_mask", "service_configuration_revision",
    "service_tool_configuration_revision",
)


def _request(request_type=ProgramAdvancedFlashRequest, **overrides):
    values = dict(zip(REQUEST_FIELDS, REQUEST))
    values.update(overrides)
    return request_type(**values)


@pytest.mark.parametrize("request_type", [ProgramAdvancedFlashRequest, VerifyAdvancedFlashRequest])
def test_flash_operation_requests_create_connected_cancellable_acknowledged_plans(request_type) -> None:
    request = request_type(*REQUEST)
    plan = request.create_plan("task")
    assert plan.connection_requirement is TaskConnectionRequirement.CONNECTED
    assert plan.cancellable
    assert plan.completion_policy is CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT
    assert len(plan.steps) == 1


def test_erase_scope_and_identity_validation() -> None:
    required = EraseAdvancedFlashRequest(
        *REQUEST, AdvancedFlashEraseScope.REQUIRED_APP_SECTORS, 0x10
    )
    assert required.custom_sector_mask == 0
    custom = EraseAdvancedFlashRequest(
        *REQUEST, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, 0x6
    )
    assert custom.custom_sector_mask == 0x6
    assert custom.create_plan("task").cancellable

    with pytest.raises(ValueError):
        _request(connection_id="")
    with pytest.raises(ValueError):
        _request(target_key="cpu2")
    with pytest.raises(ValueError):
        _request(image_selection_revision=True)
    with pytest.raises(ValueError):
        EraseAdvancedFlashRequest(*REQUEST, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, 0)
    with pytest.raises(ValueError):
        EraseAdvancedFlashRequest(*REQUEST, AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK, -1)


def test_result_snapshot_recursively_freezes_and_isolates_input() -> None:
    result = OperationResult(True, "erase_sector_mask", "CPU1", "ERASE", {})
    serialized = {
        "operation": "erase_sector_mask",
        "summary": {"mask": 0x6},
        "items": [{"word": 1}, [2, 3]],
    }
    snapshot = AdvancedFlashOperationSnapshot(
        *IDENTITY,
        AdvancedFlashOperationType.ERASE,
        result,
        serialized,
        AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK,
        0x6,
    )
    assert snapshot.operation_result is result
    serialized["operation"] = "changed"
    serialized["summary"]["mask"] = 0
    serialized["items"][0]["word"] = 9
    serialized["items"][1].append(4)
    serialized["new"] = True
    assert snapshot.operation_result_data["operation"] == "erase_sector_mask"
    assert snapshot.operation_result_data["summary"]["mask"] == 0x6
    assert snapshot.operation_result_data["items"] == (
        MappingProxyType({"word": 1}),
        (2, 3),
    )
    assert "new" not in snapshot.operation_result_data

    with pytest.raises(TypeError):
        snapshot.operation_result_data["new"] = True
    with pytest.raises(TypeError):
        snapshot.operation_result_data["summary"]["mask"] = 0
    with pytest.raises(AttributeError):
        snapshot.operation_result_data["items"].append(4)
    with pytest.raises(FrozenInstanceError):
        snapshot.operation_result_data = {}


def test_operation_result_dict_returns_independent_plain_data() -> None:
    result = OperationResult(True, "program_flash_image", "CPU1", "PROGRAM_END", {})
    snapshot = AdvancedFlashOperationSnapshot(
        *IDENTITY,
        AdvancedFlashOperationType.PROGRAM_ONLY,
        result,
        {"nested": {"value": 1}, "items": [{"word": 2}, (3, 4)]},
    )

    first = snapshot.operation_result_dict()
    second = snapshot.operation_result_dict()
    assert first == second == {
        "nested": {"value": 1},
        "items": [{"word": 2}, [3, 4]],
    }
    assert first is not second
    assert first["nested"] is not second["nested"]
    assert first["items"] is not second["items"]
    assert first["items"][0] is not second["items"][0]

    first["nested"]["value"] = 9
    first["items"][0]["word"] = 8
    first["items"].append(5)
    assert snapshot.operation_result_dict() == second


@pytest.mark.parametrize(
    "value",
    [None, True, 1, 1.5, "text", {"nested": 1}, [1, 2], (1, 2)],
)
def test_result_snapshot_accepts_supported_serialized_values(value) -> None:
    result = OperationResult(True, "program_flash_image", "CPU1", "PROGRAM_END", {})
    snapshot = AdvancedFlashOperationSnapshot(
        *IDENTITY,
        AdvancedFlashOperationType.PROGRAM_ONLY,
        result,
        {"value": value},
    )
    assert "value" in snapshot.operation_result_dict()


@pytest.mark.parametrize("value", [b"bytes", {1, 2}, object()])
def test_result_snapshot_rejects_unsupported_serialized_values(value) -> None:
    result = OperationResult(True, "program_flash_image", "CPU1", "PROGRAM_END", {})
    with pytest.raises(TypeError):
        AdvancedFlashOperationSnapshot(
            *IDENTITY,
            AdvancedFlashOperationType.PROGRAM_ONLY,
            result,
            {"value": value},
        )


def test_result_snapshot_rejects_non_string_keys_and_invalid_erase_context() -> None:
    result = OperationResult(True, "program_flash_image", "CPU1", "PROGRAM_END", {})
    with pytest.raises(TypeError):
        AdvancedFlashOperationSnapshot(
            *IDENTITY,
            AdvancedFlashOperationType.PROGRAM_ONLY,
            result,
            {"nested": {1: "value"}},
        )
    with pytest.raises(TypeError):
        AdvancedFlashOperationSnapshot(
            *IDENTITY, AdvancedFlashOperationType.PROGRAM_ONLY, result, ()
        )
    with pytest.raises(ValueError):
        AdvancedFlashOperationSnapshot(
            *IDENTITY,
            AdvancedFlashOperationType.PROGRAM_ONLY,
            result,
            {},
            AdvancedFlashEraseScope.REQUIRED_APP_SECTORS,
            0x2,
        )
