"""Immutable requests and snapshots for Advanced Flash operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType
from pathlib import Path

from ..images import ImageIdentity
from ..operations import OperationCompletion, OperationResult
from .advanced_ram_models import _revision
from .flash_service_models import PreparedFlashServiceSummary
from .runtime_v2_models import ConnectionGeneration
from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)
from .status_models import MetadataStatusSnapshot


class AdvancedFlashEraseScope(Enum):
    REQUIRED_APP_SECTORS = auto()
    ENTIRE_APPLICATION_REGION = auto()
    CUSTOM_SECTOR_MASK = auto()


class AdvancedFlashOperationType(Enum):
    ERASE = auto()
    PROGRAM_ONLY = auto()
    VERIFY_ONLY = auto()


def _freeze_result_data(value: object) -> object:
    if value is None or type(value) in (bool, int, float, str):
        return value
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("operation_result_data dictionary keys must be strings")
        return MappingProxyType(
            {key: _freeze_result_data(item) for key, item in value.items()}
        )
    if type(value) in (list, tuple):
        return tuple(_freeze_result_data(item) for item in value)
    raise TypeError(f"unsupported operation_result_data value: {type(value).__name__}")


def _thaw_result_data(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_result_data(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_result_data(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class _AdvancedFlashOperationRequest:
    connection_id: str
    target_key: str
    image_source_path: str
    image_selection_revision: int
    image_tool_configuration_revision: int
    expected_image_identity: ImageIdentity
    expected_effective_sector_mask: int
    service_configuration_revision: int
    service_tool_configuration_revision: int
    expected_connection_generation: ConnectionGeneration
    expected_service_summary: PreparedFlashServiceSummary

    title = "Advanced Flash Operation"
    step_id = "advanced_flash_operation"

    def __post_init__(self) -> None:
        if not isinstance(self.connection_id, str) or not self.connection_id.strip():
            raise ValueError("connection_id must not be empty")
        if self.target_key != "cpu1":
            raise ValueError("only target_key 'cpu1' is supported")
        if type(self.image_source_path) is not str or not self.image_source_path.strip():
            raise ValueError("image_source_path must not be empty")
        object.__setattr__(
            self,
            "image_source_path",
            str(Path(self.image_source_path.strip()).expanduser().resolve(strict=False)),
        )
        if type(self.expected_image_identity) is not ImageIdentity:
            raise TypeError("expected_image_identity must be the canonical ImageIdentity")
        if (
            type(self.expected_effective_sector_mask) is not int
            or self.expected_effective_sector_mask <= 0
        ):
            raise ValueError("expected_effective_sector_mask must be a positive integer")
        for value in (
            self.image_selection_revision,
            self.image_tool_configuration_revision,
            self.service_configuration_revision,
            self.service_tool_configuration_revision,
        ):
            _revision(value)
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
        steps = [TaskStepPlan(self.step_id, self.title, ProgressMode.INDETERMINATE)]
        if not isinstance(self, VerifyAdvancedFlashRequest):
            steps.append(
                TaskStepPlan(
                    "read_metadata_summary",
                    "Read Metadata Summary",
                    ProgressMode.INDETERMINATE,
                )
            )
        return TaskPlan(
            task_id,
            self.title,
            tuple(steps),
            TaskConnectionRequirement.CONNECTED,
            True,
            CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT,
        )


@dataclass(frozen=True, slots=True)
class EraseAdvancedFlashRequest(_AdvancedFlashOperationRequest):
    erase_scope: AdvancedFlashEraseScope
    custom_sector_mask: int = 0

    title = "Erase"
    step_id = "erase_advanced_flash"

    def __post_init__(self) -> None:
        _AdvancedFlashOperationRequest.__post_init__(self)
        if not isinstance(self.erase_scope, AdvancedFlashEraseScope):
            raise TypeError("erase_scope must be AdvancedFlashEraseScope")
        if type(self.custom_sector_mask) is not int or self.custom_sector_mask < 0:
            raise ValueError("custom_sector_mask must be a non-negative integer")
        if self.erase_scope is AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK:
            if self.custom_sector_mask == 0:
                raise ValueError("custom erase scope requires a nonzero sector mask")
        else:
            object.__setattr__(self, "custom_sector_mask", 0)


@dataclass(frozen=True, slots=True)
class ProgramAdvancedFlashRequest(_AdvancedFlashOperationRequest):
    title = "Program Only"
    step_id = "program_advanced_flash"


@dataclass(frozen=True, slots=True)
class VerifyAdvancedFlashRequest(_AdvancedFlashOperationRequest):
    title = "Verify Only"
    step_id = "verify_advanced_flash"


@dataclass(frozen=True, slots=True)
class AdvancedFlashOperationSnapshot:
    connection_id: str
    target_key: str
    image_selection_revision: int
    image_tool_configuration_revision: int
    service_configuration_revision: int
    service_tool_configuration_revision: int
    operation_type: AdvancedFlashOperationType
    operation_result: OperationResult
    operation_result_data: Mapping[str, object]
    erase_scope: AdvancedFlashEraseScope | None = None
    erase_sector_mask: int | None = None
    metadata_refresh_result: OperationResult | None = None
    metadata_refresh_result_data: Mapping[str, object] | None = None
    metadata_snapshot: MetadataStatusSnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.connection_id, str) or not self.connection_id.strip():
            raise ValueError("connection_id must not be empty")
        if self.target_key != "cpu1":
            raise ValueError("only target_key 'cpu1' is supported")
        for value in (
            self.image_selection_revision,
            self.image_tool_configuration_revision,
            self.service_configuration_revision,
            self.service_tool_configuration_revision,
        ):
            _revision(value)
        if not isinstance(self.operation_type, AdvancedFlashOperationType):
            raise TypeError("operation_type must be AdvancedFlashOperationType")
        if not isinstance(self.operation_result, OperationResult):
            raise TypeError("operation_result must be OperationResult")
        if type(self.operation_result_data) is not dict:
            raise TypeError("operation_result_data must be dict")
        object.__setattr__(
            self, "operation_result_data", _freeze_result_data(self.operation_result_data)
        )
        if self.operation_result.completion not in {
            OperationCompletion.SUCCEEDED,
            OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        } and (
            self.metadata_refresh_result is not None
            or self.metadata_refresh_result_data is not None
            or self.metadata_snapshot is not None
        ):
            raise ValueError("Unsuccessful primary results cannot carry Metadata refresh data")
        if self.operation_type is AdvancedFlashOperationType.ERASE:
            if not isinstance(self.erase_scope, AdvancedFlashEraseScope):
                raise TypeError("Erase snapshot requires an erase scope")
            if type(self.erase_sector_mask) is not int or self.erase_sector_mask <= 0:
                raise ValueError("Erase snapshot requires a positive sector mask")
        elif self.erase_scope is not None or self.erase_sector_mask is not None:
            raise ValueError("Only Erase snapshots carry erase details")
        if self.operation_type is AdvancedFlashOperationType.VERIFY_ONLY:
            if (
                self.metadata_refresh_result is not None
                or self.metadata_refresh_result_data is not None
                or self.metadata_snapshot is not None
            ):
                raise ValueError("Verify snapshots cannot carry Metadata refresh data")
        elif self.metadata_refresh_result is None:
            if self.metadata_refresh_result_data is not None or self.metadata_snapshot is not None:
                raise ValueError("Metadata refresh data requires metadata_refresh_result")
        else:
            if not isinstance(self.metadata_refresh_result, OperationResult):
                raise TypeError("metadata_refresh_result must be OperationResult")
            if type(self.metadata_refresh_result_data) is not dict:
                raise TypeError("metadata_refresh_result_data must be dict")
            object.__setattr__(
                self,
                "metadata_refresh_result_data",
                _freeze_result_data(self.metadata_refresh_result_data),
            )
            if self.metadata_snapshot is not None and type(self.metadata_snapshot) is not MetadataStatusSnapshot:
                raise TypeError("metadata_snapshot must be MetadataStatusSnapshot")

    def operation_result_dict(self) -> dict[str, object]:
        return dict(_thaw_result_data(self.operation_result_data))

    def metadata_refresh_result_dict(self) -> dict[str, object] | None:
        if self.metadata_refresh_result_data is None:
            return None
        return dict(_thaw_result_data(self.metadata_refresh_result_data))


__all__ = [
    "AdvancedFlashEraseScope",
    "AdvancedFlashOperationSnapshot",
    "AdvancedFlashOperationType",
    "EraseAdvancedFlashRequest",
    "ProgramAdvancedFlashRequest",
    "VerifyAdvancedFlashRequest",
]
