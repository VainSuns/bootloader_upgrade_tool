"""Immutable Advanced Flash App execution request and result."""

from __future__ import annotations

from dataclasses import dataclass

from ..operations import OperationResult
from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)
from .runtime_v2_models import ConnectionGeneration, RuntimeCpuId
from .status_models import MetadataStatusSnapshot

FLASH_APP_RUN_CPU = RuntimeCpuId.CPU1
FLASH_APP_RUN_TARGET_KEY = FLASH_APP_RUN_CPU.value


@dataclass(frozen=True, slots=True)
class RunAdvancedFlashAppRequest:
    connection_id: str
    target_key: str
    expected_connection_generation: ConnectionGeneration
    expected_metadata_snapshot: MetadataStatusSnapshot
    entry_point: int

    title = "Run Flash App"
    step_id = "run_flash_app"
    cancellable = False

    def __post_init__(self) -> None:
        if type(self.connection_id) is not str or not self.connection_id.strip():
            raise ValueError("connection_id must not be empty")
        if self.target_key != FLASH_APP_RUN_TARGET_KEY:
            raise ValueError(f"target_key must be {FLASH_APP_RUN_TARGET_KEY!r}")
        if type(self.expected_connection_generation) is not ConnectionGeneration:
            raise TypeError("expected_connection_generation must be ConnectionGeneration")
        snapshot = self.expected_metadata_snapshot
        if type(snapshot) is not MetadataStatusSnapshot:
            raise TypeError("expected_metadata_snapshot must be MetadataStatusSnapshot")
        if snapshot.connection_id != self.connection_id:
            raise ValueError("Metadata snapshot connection does not match request")
        if snapshot.target_key != self.target_key:
            raise ValueError("Metadata snapshot target does not match request")
        if not (
            snapshot.metadata_valid is True
            and snapshot.image_valid is True
            and snapshot.entry_point_valid is True
        ):
            raise ValueError("a valid IMAGE_VALID entry point is required")
        if type(self.entry_point) is not int or self.entry_point < 0:
            raise ValueError("entry_point must be a non-negative integer")
        if snapshot.raw_metadata.entry_point != self.entry_point:
            raise ValueError("entry_point does not match Metadata snapshot")

    def create_plan(self, task_id: str) -> TaskPlan:
        return TaskPlan(
            task_id,
            self.title,
            (TaskStepPlan(self.step_id, self.title, ProgressMode.INDETERMINATE),),
            TaskConnectionRequirement.CONNECTED,
            False,
            CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT,
        )


@dataclass(frozen=True, slots=True)
class AdvancedFlashAppRunSnapshot:
    connection_id: str
    target_key: str
    connection_generation: ConnectionGeneration
    metadata_snapshot: MetadataStatusSnapshot
    entry_point: int
    operation_result: OperationResult

    def __post_init__(self) -> None:
        RunAdvancedFlashAppRequest(
            self.connection_id,
            self.target_key,
            self.connection_generation,
            self.metadata_snapshot,
            self.entry_point,
        )
        if not isinstance(self.operation_result, OperationResult):
            raise TypeError("operation_result must be OperationResult")


__all__ = [
    "AdvancedFlashAppRunSnapshot",
    "FLASH_APP_RUN_CPU",
    "FLASH_APP_RUN_TARGET_KEY",
    "RunAdvancedFlashAppRequest",
]
