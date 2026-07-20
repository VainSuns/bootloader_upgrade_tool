"""Immutable requests and snapshots for Advanced Metadata operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from ..images import ImageIdentity
from ..operations import OperationResult
from .advanced_flash_operation_models import _freeze_result_data, _thaw_result_data
from .advanced_ram_models import _revision
from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)
from .status_models import MetadataStatusSnapshot
from .flash_service_models import PreparedFlashServiceSummary
from .runtime_v2_models import ConnectionGeneration, RuntimeCpuId, VerifyEvidence


class AdvancedMetadataOperationType(Enum):
    WRITE_IMAGE_VALID = auto()
    WRITE_BOOT_ATTEMPT = auto()
    WRITE_APP_CONFIRMED = auto()


def _validate_request_context(connection_id, target_key, *revisions) -> None:
    if not isinstance(connection_id, str) or not connection_id.strip():
        raise ValueError("connection_id must not be empty")
    if target_key != "cpu1":
        raise ValueError("only target_key 'cpu1' is supported")
    for value in revisions:
        _revision(value)


@dataclass(frozen=True, slots=True)
class _AdvancedMetadataRequest:
    connection_id: str
    target_key: str
    service_configuration_revision: int
    service_tool_configuration_revision: int
    expected_connection_generation: ConnectionGeneration
    expected_service_summary: PreparedFlashServiceSummary
    expected_metadata_snapshot: MetadataStatusSnapshot | None

    title = "Advanced Metadata Operation"
    step_id = "append_metadata"

    def __post_init__(self) -> None:
        _validate_request_context(
            self.connection_id,
            self.target_key,
            self.service_configuration_revision,
            self.service_tool_configuration_revision,
        )
        if type(self.expected_connection_generation) is not ConnectionGeneration:
            raise TypeError("expected_connection_generation must be ConnectionGeneration")
        if type(self.expected_service_summary) is not PreparedFlashServiceSummary:
            raise TypeError("expected_service_summary must be PreparedFlashServiceSummary")
        if (
            self.expected_service_summary.target_key != self.target_key
            or self.expected_service_summary.resource_revision
            != self.service_configuration_revision
            or self.expected_service_summary.tool_configuration_revision
            != self.service_tool_configuration_revision
        ):
            raise ValueError("expected_service_summary revisions must match the request")

    def create_plan(self, task_id: str) -> TaskPlan:
        return TaskPlan(
            task_id,
            self.title,
            (
                TaskStepPlan(self.step_id, self.title, ProgressMode.INDETERMINATE),
                TaskStepPlan(
                    "read_metadata_summary",
                    "Read Metadata Summary",
                    ProgressMode.INDETERMINATE,
                ),
            ),
            TaskConnectionRequirement.CONNECTED,
            True,
            CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT,
        )


@dataclass(frozen=True, slots=True)
class WriteAdvancedImageValidRequest(_AdvancedMetadataRequest):
    image_source_path: str
    image_selection_revision: int
    image_tool_configuration_revision: int
    expected_image_identity: ImageIdentity
    expected_effective_sector_mask: int
    expected_verify_evidence: VerifyEvidence

    title = "Write IMAGE_VALID"
    step_id = "write_image_valid"

    def __post_init__(self) -> None:
        _AdvancedMetadataRequest.__post_init__(self)
        _validate_request_context(
            self.connection_id,
            self.target_key,
            self.image_selection_revision,
            self.image_tool_configuration_revision,
        )
        if type(self.image_source_path) is not str or not self.image_source_path.strip():
            raise ValueError("image_source_path must not be empty")
        object.__setattr__(
            self,
            "image_source_path",
            str(Path(self.image_source_path.strip()).expanduser().resolve(strict=False)),
        )
        if type(self.expected_image_identity) is not ImageIdentity:
            raise TypeError("expected_image_identity must be the canonical ImageIdentity")
        if type(self.expected_effective_sector_mask) is not int or self.expected_effective_sector_mask <= 0:
            raise ValueError("expected_effective_sector_mask must be a positive integer")
        if type(self.expected_verify_evidence) is not VerifyEvidence:
            raise TypeError("expected_verify_evidence must be the canonical VerifyEvidence")
        if self.expected_verify_evidence.cpu_id is not RuntimeCpuId.CPU1:
            raise ValueError("IMAGE_VALID VerifyEvidence must belong to CPU1")
        if self.expected_verify_evidence.image_identity != self.expected_image_identity:
            raise ValueError("VerifyEvidence identity must match expected_image_identity")
        if self.expected_metadata_snapshot is not None:
            raise ValueError("IMAGE_VALID must not carry a Metadata snapshot")


@dataclass(frozen=True, slots=True)
class WriteAdvancedBootAttemptRequest(_AdvancedMetadataRequest):
    title = "Write BOOT_ATTEMPT"
    step_id = "write_boot_attempt"

    def __post_init__(self) -> None:
        _AdvancedMetadataRequest.__post_init__(self)
        _validate_metadata_snapshot(self)


@dataclass(frozen=True, slots=True)
class WriteAdvancedAppConfirmedRequest(_AdvancedMetadataRequest):
    title = "Write APP_CONFIRMED"
    step_id = "write_app_confirmed"

    def __post_init__(self) -> None:
        _AdvancedMetadataRequest.__post_init__(self)
        _validate_metadata_snapshot(self)


def _validate_metadata_snapshot(request: _AdvancedMetadataRequest) -> None:
    if type(request.expected_metadata_snapshot) is not MetadataStatusSnapshot:
        raise TypeError("expected_metadata_snapshot must be MetadataStatusSnapshot")
    snapshot = request.expected_metadata_snapshot
    if (
        snapshot.connection_id != request.connection_id
        or snapshot.target_key != request.target_key
        or not snapshot.metadata_valid
        or not snapshot.image_valid
    ):
        raise ValueError("expected_metadata_snapshot must contain the current valid image")


@dataclass(frozen=True, slots=True)
class AdvancedMetadataOperationSnapshot:
    connection_id: str
    target_key: str
    image_selection_revision: int | None
    image_tool_configuration_revision: int | None
    service_configuration_revision: int
    service_tool_configuration_revision: int
    operation_type: AdvancedMetadataOperationType
    verify_evidence: VerifyEvidence | None
    entry_point: int
    image_size_words: int
    image_crc32: int
    app_end: int | None
    primary_result: OperationResult
    primary_result_data: Mapping[str, object]
    readback_result: OperationResult | None = None
    readback_result_data: Mapping[str, object] | None = None
    metadata_snapshot: MetadataStatusSnapshot | None = None

    def __post_init__(self) -> None:
        _validate_request_context(
            self.connection_id, self.target_key,
            self.service_configuration_revision, self.service_tool_configuration_revision,
        )
        if not isinstance(self.operation_type, AdvancedMetadataOperationType):
            raise TypeError("operation_type must be AdvancedMetadataOperationType")
        if self.operation_type is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            _revision(self.image_selection_revision)
            _revision(self.image_tool_configuration_revision)
            if type(self.verify_evidence) is not VerifyEvidence:
                raise ValueError("IMAGE_VALID snapshot requires exact VerifyEvidence")
            if self.verify_evidence.cpu_id is not RuntimeCpuId.CPU1:
                raise ValueError("IMAGE_VALID VerifyEvidence must belong to CPU1")
            identity = self.verify_evidence.image_identity
            if (
                identity.entry_point,
                identity.image_size_words,
                identity.image_crc32,
                identity.app_end,
            ) != (self.entry_point, self.image_size_words, self.image_crc32, self.app_end):
                raise ValueError("VerifyEvidence identity must match snapshot image identity")
            if type(self.app_end) is not int or self.app_end < 0:
                raise ValueError("IMAGE_VALID snapshot requires app_end")
        elif (
            self.verify_evidence is not None
            or self.image_selection_revision is not None
            or self.image_tool_configuration_revision is not None
            or self.app_end is not None
        ):
            raise ValueError("Metadata-only snapshots cannot carry Program Image fields")
        for name in ("entry_point", "image_size_words", "image_crc32"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.primary_result, OperationResult):
            raise TypeError("primary_result must be OperationResult")
        if type(self.primary_result_data) is not dict:
            raise TypeError("primary_result_data must be dict")
        object.__setattr__(self, "primary_result_data", _freeze_result_data(self.primary_result_data))
        if self.readback_result is None:
            if self.readback_result_data is not None or self.metadata_snapshot is not None:
                raise ValueError("readback data requires readback_result")
        else:
            if not isinstance(self.readback_result, OperationResult):
                raise TypeError("readback_result must be OperationResult")
            if type(self.readback_result_data) is not dict:
                raise TypeError("readback_result_data must be dict")
            object.__setattr__(
                self, "readback_result_data", _freeze_result_data(self.readback_result_data)
            )
            if self.metadata_snapshot is not None and type(self.metadata_snapshot) is not MetadataStatusSnapshot:
                raise TypeError("metadata_snapshot must be MetadataStatusSnapshot")

    def primary_result_dict(self) -> dict[str, object]:
        return dict(_thaw_result_data(self.primary_result_data))

    def readback_result_dict(self) -> dict[str, object] | None:
        if self.readback_result_data is None:
            return None
        return dict(_thaw_result_data(self.readback_result_data))


__all__ = [
    "AdvancedMetadataOperationSnapshot",
    "AdvancedMetadataOperationType",
    "WriteAdvancedAppConfirmedRequest",
    "WriteAdvancedBootAttemptRequest",
    "WriteAdvancedImageValidRequest",
]
