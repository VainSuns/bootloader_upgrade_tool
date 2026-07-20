from dataclasses import FrozenInstanceError, replace

import pytest

from bootloader_upgrade_tool.gui.advanced_flash_operation_models import AdvancedFlashEraseScope
from bootloader_upgrade_tool.gui.flash_service_models import DEFAULT_SERVICE_DESCRIPTOR_SYMBOL, PreparedFlashServiceSummary
from bootloader_upgrade_tool.gui.flash_write_models import FlashWriteOperationType, FlashWritePlan
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.runtime_v2_models import ConnectionGeneration, RuntimeCpuId, VerifyEvidence
from bootloader_upgrade_tool.gui.status_models import LoadedImageMatch, MetadataStatusSnapshot
from bootloader_upgrade_tool.images import ImageIdentity
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.protocol.models import MetadataSummary


IDENTITY = ImageIdentity(0x82400, 8, 0x12345678, 0x82408)
SERVICE = PreparedFlashServiceSummary(
    "cpu1", "Provider", "service.txt", "service.map", DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
    3, 2, ImageSourceKind.TXT, SourceFileFingerprint("service.txt", 1, 1),
    SourceFileFingerprint("service.map", 1, 1), 0x10000, 0x10020, 0x10030,
    8, 0x5678, 0xF, Hex2000Source.NOT_USED, None,
)
RAW = MetadataSummary(
    1, 1, 1, 2, 0, 3, 1, 0, 0, 0, IDENTITY.entry_point,
    IDENTITY.image_crc32, 1, 1, 0, 0, 1, 1, IDENTITY.image_size_words, 0x377D, 1,
)
RESULT = OperationResult(True, "metadata", "cpu1", "read", {})
METADATA = MetadataStatusSnapshot(
    "connection", "cpu1", RESULT, RAW, True, True, True, True, False, False,
    LoadedImageMatch.MATCH, False,
)
EVIDENCE = VerifyEvidence(RuntimeCpuId.CPU1, ConnectionGeneration(1), IDENTITY, "verify")


def plan(operation_type, **overrides):
    values = dict(
        plan_id="plan", operation_type=operation_type, cpu_id=RuntimeCpuId.CPU1,
        connection_id="connection", connection_generation=ConnectionGeneration(1),
        transport_label="SCI", endpoint_label="COM3", image_source_path="app.txt",
        image_selection_revision=1, image_tool_configuration_revision=2,
        image_identity=IDENTITY, effective_sector_mask=0x2,
        service_configuration_revision=3, service_tool_configuration_revision=2,
        service_summary=SERVICE,
    )
    if operation_type is FlashWriteOperationType.ERASE:
        values.update(erase_scope=AdvancedFlashEraseScope.REQUIRED_APP_SECTORS, erase_sector_mask=0x2)
    elif operation_type is FlashWriteOperationType.WRITE_IMAGE_VALID:
        values["verify_evidence"] = EVIDENCE
    elif operation_type in {FlashWriteOperationType.WRITE_BOOT_ATTEMPT, FlashWriteOperationType.WRITE_APP_CONFIRMED}:
        values.update(
            image_source_path=None, image_selection_revision=None,
            image_tool_configuration_revision=None, image_identity=None,
            effective_sector_mask=None, metadata_snapshot=METADATA,
        )
    values.update(overrides)
    return FlashWritePlan(**values)


@pytest.mark.parametrize("operation_type", list(FlashWriteOperationType))
def test_all_operation_types_are_immutable_and_normalize_path(operation_type) -> None:
    item = plan(operation_type)
    if operation_type in {FlashWriteOperationType.WRITE_BOOT_ATTEMPT, FlashWriteOperationType.WRITE_APP_CONFIRMED}:
        assert item.image_source_path is item.image_identity is None
    else:
        assert item.image_source_path.endswith("app.txt")
    with pytest.raises(FrozenInstanceError):
        item.plan_id = "other"


def test_common_and_service_invariants() -> None:
    with pytest.raises(ValueError):
        plan(FlashWriteOperationType.PROGRAM_ONLY, cpu_id=RuntimeCpuId.CPU2)
    with pytest.raises(ValueError):
        plan(FlashWriteOperationType.PROGRAM_ONLY, connection_id="")
    with pytest.raises(TypeError):
        plan(FlashWriteOperationType.PROGRAM_ONLY, connection_generation=1)
    with pytest.raises(TypeError):
        plan(FlashWriteOperationType.PROGRAM_ONLY, image_identity=object())
    with pytest.raises(ValueError):
        plan(FlashWriteOperationType.PROGRAM_ONLY, service_configuration_revision=4)


def test_operation_specific_invariants_and_display_values() -> None:
    with pytest.raises(TypeError):
        plan(FlashWriteOperationType.ERASE, erase_scope=None)
    with pytest.raises(ValueError):
        plan(FlashWriteOperationType.ERASE, erase_sector_mask=0)
    with pytest.raises(ValueError):
        plan(FlashWriteOperationType.PROGRAM_ONLY, erase_sector_mask=2)
    with pytest.raises(TypeError):
        plan(FlashWriteOperationType.WRITE_IMAGE_VALID, verify_evidence=object())
    with pytest.raises(ValueError):
        plan(FlashWriteOperationType.WRITE_IMAGE_VALID, metadata_snapshot=METADATA)
    with pytest.raises(TypeError):
        plan(FlashWriteOperationType.WRITE_BOOT_ATTEMPT, metadata_snapshot=None)
    with pytest.raises(ValueError):
        plan(
            FlashWriteOperationType.WRITE_APP_CONFIRMED,
            metadata_snapshot=replace(METADATA, connection_id="other"),
        )
    item = plan(FlashWriteOperationType.WRITE_BOOT_ATTEMPT)
    assert item.operation_display_name == "Write BOOT_ATTEMPT"
    assert item.metadata_record_name == "BOOT_ATTEMPT"
    assert item.boot_attempt_count_before == 2
    assert item.app_confirmed_before is False
