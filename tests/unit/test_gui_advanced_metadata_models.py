from dataclasses import FrozenInstanceError
import pytest

from bootloader_upgrade_tool.gui.advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
    AdvancedMetadataOperationType,
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from bootloader_upgrade_tool.gui.runtime_models import CompletionPolicy, TaskConnectionRequirement
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.images import ImageIdentity
from bootloader_upgrade_tool.gui.runtime_v2_models import ConnectionGeneration, RuntimeCpuId, VerifyEvidence
from bootloader_upgrade_tool.gui.flash_service_models import DEFAULT_SERVICE_DESCRIPTOR_SYMBOL, PreparedFlashServiceSummary
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataStatusSnapshot
from bootloader_upgrade_tool.protocol.models import MetadataSummary


IDENTITY = ("connection", "cpu1", 1, 2, 3, 2)
METADATA_IDENTITY = ("connection", "cpu1", None, None, 3, 2)
SERVICE = PreparedFlashServiceSummary(
    "cpu1", "Provider", "service.txt", "service.map",
    DEFAULT_SERVICE_DESCRIPTOR_SYMBOL, 3, 2, ImageSourceKind.TXT,
    SourceFileFingerprint("service.txt", 1, 1), SourceFileFingerprint("service.map", 1, 1),
    0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF, Hex2000Source.NOT_USED, None,
)
RAW = MetadataSummary(
    1, 1, 1, 1, 0, 3, 1, 0, 0, 0, 0x82000, 0x1234,
    1, 1, 0, 0, 1, 1, 8, 0x377D, 1,
)
STATUS_RESULT = OperationResult(True, "get_metadata_summary", "cpu1", "read", {})
METADATA = MetadataStatusSnapshot(
    "connection", "cpu1", STATUS_RESULT, RAW, True, True, True, True, False,
    False, LoadedImageMatch.MATCH, False,
)
IMAGE_IDENTITY = ImageIdentity(0x82000, 8, 0x1234, 0x82008)
COMMON = dict(
    connection_id="connection", target_key="cpu1",
    service_configuration_revision=3, service_tool_configuration_revision=2,
    expected_connection_generation=ConnectionGeneration(1), expected_service_summary=SERVICE,
)
IMAGE = dict(
    image_source_path="app.txt", image_selection_revision=1,
    image_tool_configuration_revision=2, expected_image_identity=IMAGE_IDENTITY,
    expected_effective_sector_mask=0x2,
)
EVIDENCE = VerifyEvidence(RuntimeCpuId.CPU1, ConnectionGeneration(1), IMAGE_IDENTITY, "verify")


@pytest.mark.parametrize(
    "metadata_request",
    [
        WriteAdvancedImageValidRequest(**COMMON, **IMAGE, expected_metadata_snapshot=None, expected_verify_evidence=EVIDENCE),
        WriteAdvancedBootAttemptRequest(**COMMON, expected_metadata_snapshot=METADATA),
        WriteAdvancedAppConfirmedRequest(**COMMON, expected_metadata_snapshot=METADATA),
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
        {"service_configuration_revision": True},
        {"service_tool_configuration_revision": -1},
    ],
)
def test_request_identity_validation(args) -> None:
    values = {**COMMON, "expected_metadata_snapshot": METADATA}
    values.update(args)
    with pytest.raises(ValueError):
        WriteAdvancedBootAttemptRequest(**values)


def test_only_image_valid_accepts_matching_exact_cpu1_evidence() -> None:
    with pytest.raises(TypeError):
        WriteAdvancedImageValidRequest(**COMMON, **IMAGE, expected_metadata_snapshot=None, expected_verify_evidence=object())
    with pytest.raises(ValueError):
        WriteAdvancedImageValidRequest(**COMMON, **IMAGE, expected_metadata_snapshot=None,
            expected_verify_evidence=VerifyEvidence(RuntimeCpuId.CPU2, ConnectionGeneration(1), IMAGE_IDENTITY, "verify"))
    with pytest.raises(ValueError):
        WriteAdvancedImageValidRequest(**COMMON, **IMAGE, expected_metadata_snapshot=None,
            expected_verify_evidence=VerifyEvidence(
                RuntimeCpuId.CPU1,
                ConnectionGeneration(1),
                ImageIdentity(1, 8, 2, 9),
                "verify",
            ))


def test_snapshot_recursively_freezes_and_thaws_serialized_results() -> None:
    result = OperationResult(True, "append", "cpu1", "METADATA", {"written": True})
    source = {"nested": {"items": [1, {"value": 2}]}}
    snapshot = AdvancedMetadataOperationSnapshot(
        *IDENTITY,
        AdvancedMetadataOperationType.WRITE_IMAGE_VALID,
        EVIDENCE,
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
            *METADATA_IDENTITY,
            AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT,
            None,
            1,
            8,
            2,
            None,
            result,
            {"value": value},
        )
