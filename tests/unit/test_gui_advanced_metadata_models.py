from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from bootloader_upgrade_tool.gui.advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
    AdvancedMetadataOperationType,
    CleanVerifyCredential,
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from bootloader_upgrade_tool.gui.image_preparation_models import SourceFileFingerprint
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


@pytest.mark.parametrize(
    "metadata_request",
    [
        WriteAdvancedImageValidRequest(*REQUEST, "token"),
        WriteAdvancedBootAttemptRequest(*REQUEST),
        WriteAdvancedAppConfirmedRequest(*REQUEST),
    ],
)
def test_requests_create_two_step_connected_cancellable_acknowledged_plans(metadata_request) -> None:
    plan = metadata_request.create_plan("task")
    assert plan.connection_requirement is TaskConnectionRequirement.CONNECTED
    assert plan.cancellable
    assert plan.completion_policy is CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT
    assert [step.step_id for step in plan.steps] == [metadata_request.step_id, "read_metadata_summary"]


@pytest.mark.parametrize(
    "args",
    [
        {"connection_id": ""},
        {"target_key": "cpu2"},
        {"image_selection_revision": True},
        {"image_tool_configuration_revision": -1},
    ],
)
def test_request_identity_validation(args) -> None:
    values = dict(zip(REQUEST_FIELDS, REQUEST))
    values.update(args)
    with pytest.raises(ValueError):
        WriteAdvancedBootAttemptRequest(**values)


def test_only_image_valid_accepts_a_nonempty_token() -> None:
    with pytest.raises(ValueError):
        WriteAdvancedImageValidRequest(*REQUEST, "")
    with pytest.raises(TypeError):
        WriteAdvancedBootAttemptRequest(*REQUEST, "token")
    with pytest.raises(TypeError):
        WriteAdvancedAppConfirmedRequest(*REQUEST, "token")


def test_clean_verify_credential_is_frozen_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "app.txt"
    path.write_text("app")
    fingerprint = SourceFileFingerprint(str(path.resolve()), 3, path.stat().st_mtime_ns)
    credential = CleanVerifyCredential(
        "token", "connection", "cpu1", 1, 2, fingerprint, 0x82000, 8, 0x1234, 0x82008
    )
    with pytest.raises(FrozenInstanceError):
        credential.token = "changed"
    with pytest.raises(ValueError):
        CleanVerifyCredential("", "connection", "cpu1", 1, 2, fingerprint, 1, 8, 1, 9)


def test_snapshot_recursively_freezes_and_thaws_serialized_results() -> None:
    result = OperationResult(True, "append", "cpu1", "METADATA", {"written": True})
    source = {"nested": {"items": [1, {"value": 2}]}}
    snapshot = AdvancedMetadataOperationSnapshot(
        *IDENTITY,
        AdvancedMetadataOperationType.WRITE_IMAGE_VALID,
        "token",
        0x82000,
        8,
        0x1234,
        0x82008,
        result,
        source,
    )
    source["nested"]["items"][1]["value"] = 9
    first = snapshot.primary_result_dict()
    second = snapshot.primary_result_dict()
    assert first == second == {"nested": {"items": [1, {"value": 2}]}}
    assert first is not second and first["nested"] is not second["nested"]
    first["nested"]["items"].append(3)
    assert snapshot.primary_result_dict() == second
    with pytest.raises(FrozenInstanceError):
        snapshot.primary_result_data = {}


@pytest.mark.parametrize("value", [b"bytes", {1, 2}, object(), {1: "bad"}])
def test_snapshot_rejects_non_json_result_data(value) -> None:
    result = OperationResult(True, "append", "cpu1", "METADATA", {})
    with pytest.raises(TypeError):
        AdvancedMetadataOperationSnapshot(
            *IDENTITY,
            AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT,
            None,
            1,
            8,
            2,
            9,
            result,
            {"value": value},
        )
