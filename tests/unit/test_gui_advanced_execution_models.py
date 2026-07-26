from dataclasses import replace

import pytest

from bootloader_upgrade_tool.gui.advanced_execution_models import (
    AdvancedFlashAppRunSnapshot,
    RunAdvancedFlashAppRequest,
)
from bootloader_upgrade_tool.gui.runtime_models import (
    CompletionPolicy,
    TaskConnectionRequirement,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import ConnectionGeneration
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataStatusSnapshot
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.protocol.models import MetadataSummary


def metadata() -> MetadataStatusSnapshot:
    raw = MetadataSummary(
        1, 1, 1, 0, 0, 3, 1, 0, 0, 0, 0x82400, 0x1234,
        1, 1, 0, 0, 1, 1, 8, 0x377D, 1,
    )
    result = OperationResult(True, "get_metadata_summary", "CPU1", "GET_METADATA_SUMMARY", {})
    return MetadataStatusSnapshot(
        "connection", "cpu1", result, raw, True, True, True,
        False, False, False, LoadedImageMatch.NO_PREPARED_IMAGE, False,
    )


def request(**changes) -> RunAdvancedFlashAppRequest:
    values = dict(
        connection_id="connection",
        target_key="cpu1",
        expected_connection_generation=ConnectionGeneration(1),
        expected_metadata_snapshot=metadata(),
        entry_point=0x82400,
    )
    values.update(changes)
    return RunAdvancedFlashAppRequest(**values)


def test_request_and_snapshot_require_only_valid_image_metadata() -> None:
    value = request()
    plan = value.create_plan("task")
    result = OperationResult(True, "run_flash_app", "CPU1", "RUN", {})
    snapshot = AdvancedFlashAppRunSnapshot(
        value.connection_id,
        value.target_key,
        value.expected_connection_generation,
        value.expected_metadata_snapshot,
        value.entry_point,
        result,
    )

    assert plan.connection_requirement is TaskConnectionRequirement.CONNECTED
    assert plan.completion_policy is CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT
    assert not plan.cancellable and len(plan.steps) == 1
    assert snapshot.operation_result is result


@pytest.mark.parametrize(
    "changes",
    (
        {"target_key": "cpu2"},
        {"connection_id": "other"},
        {"expected_connection_generation": 1},
        {"expected_metadata_snapshot": object()},
        {"entry_point": -1},
        {"entry_point": True},
        {"entry_point": 0x82402},
    ),
)
def test_request_rejects_invalid_frozen_context(changes) -> None:
    with pytest.raises((TypeError, ValueError)):
        request(**changes)


@pytest.mark.parametrize("field", ("metadata_valid", "image_valid", "entry_point_valid"))
def test_request_rejects_invalid_image_valid_flags(field) -> None:
    with pytest.raises(ValueError):
        request(expected_metadata_snapshot=replace(metadata(), **{field: False}))


def test_request_rejects_metadata_target_mismatch() -> None:
    with pytest.raises(ValueError):
        request(expected_metadata_snapshot=replace(metadata(), target_key="cpu2"))
