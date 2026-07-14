"""Immutable requests and snapshots for Advanced Flash operations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum, auto

from ..operations import OperationResult
from .advanced_ram_models import _revision
from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)


class AdvancedFlashEraseScope(Enum):
    REQUIRED_APP_SECTORS = auto()
    ENTIRE_APPLICATION_REGION = auto()
    CUSTOM_SECTOR_MASK = auto()


class AdvancedFlashOperationType(Enum):
    ERASE = auto()
    PROGRAM_ONLY = auto()
    VERIFY_ONLY = auto()


@dataclass(frozen=True, slots=True)
class _AdvancedFlashOperationRequest:
    connection_id: str
    target_key: str
    image_selection_revision: int
    image_tool_configuration_revision: int
    service_configuration_revision: int
    service_tool_configuration_revision: int

    title = "Advanced Flash Operation"
    step_id = "advanced_flash_operation"

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

    def create_plan(self, task_id: str) -> TaskPlan:
        return TaskPlan(
            task_id,
            self.title,
            (TaskStepPlan(self.step_id, self.title, ProgressMode.INDETERMINATE),),
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
    operation_result_data: dict[str, object]
    erase_scope: AdvancedFlashEraseScope | None = None
    erase_sector_mask: int | None = None

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
        object.__setattr__(self, "operation_result_data", deepcopy(self.operation_result_data))
        if self.operation_type is AdvancedFlashOperationType.ERASE:
            if not isinstance(self.erase_scope, AdvancedFlashEraseScope):
                raise TypeError("Erase snapshot requires an erase scope")
            if type(self.erase_sector_mask) is not int or self.erase_sector_mask <= 0:
                raise ValueError("Erase snapshot requires a positive sector mask")
        elif self.erase_scope is not None or self.erase_sector_mask is not None:
            raise ValueError("Only Erase snapshots carry erase details")


__all__ = [
    "AdvancedFlashEraseScope",
    "AdvancedFlashOperationSnapshot",
    "AdvancedFlashOperationType",
    "EraseAdvancedFlashRequest",
    "ProgramAdvancedFlashRequest",
    "VerifyAdvancedFlashRequest",
]
