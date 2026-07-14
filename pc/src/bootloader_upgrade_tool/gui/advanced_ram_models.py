"""Immutable requests and snapshots for Advanced RAM image operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..operations import OperationResult
from .image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)


def _target_key(value: str) -> str:
    if value not in {"cpu1", "cpu2"}:
        raise ValueError("target_key must be 'cpu1' or 'cpu2'")
    return value


def _revision(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("selection_revision must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class PrepareRamImageRequest:
    target_key: str
    source_path: str
    selection_revision: int

    def __post_init__(self) -> None:
        _target_key(self.target_key)
        _revision(self.selection_revision)
        object.__setattr__(self, "source_path", str(self.source_path).strip())

    def create_plan(self, task_id: str) -> TaskPlan:
        return TaskPlan(
            task_id,
            f"Prepare {self.target_key.upper()} RAM Image",
            (TaskStepPlan("prepare_ram_image", "Prepare RAM Image", ProgressMode.INDETERMINATE),),
            TaskConnectionRequirement.NONE,
            False,
            CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS,
        )


@dataclass(frozen=True, slots=True)
class PreparedRamImageSummary:
    target_key: str
    selection_revision: int
    source_path: str
    source_kind: ImageSourceKind
    source_fingerprint: SourceFileFingerprint
    entry_point: int
    image_size_words: int
    image_crc32: int
    hex2000_source: Hex2000Source
    hex2000_executable: str | None

    def __post_init__(self) -> None:
        _target_key(self.target_key)
        _revision(self.selection_revision)
        if self.image_size_words <= 0:
            raise ValueError("image_size_words must be positive")
        object.__setattr__(self, "source_path", str(Path(self.source_path).resolve(strict=False)))


@dataclass(frozen=True, slots=True)
class _RamOperationRequest:
    connection_id: str
    target_key: str
    selection_revision: int

    title = "RAM Operation"
    step_id = "ram_operation"
    cancellable = False

    def __post_init__(self) -> None:
        if not isinstance(self.connection_id, str) or not self.connection_id.strip():
            raise ValueError("connection_id must not be empty")
        _target_key(self.target_key)
        _revision(self.selection_revision)

    def create_plan(self, task_id: str) -> TaskPlan:
        return TaskPlan(
            task_id,
            self.title,
            (TaskStepPlan(self.step_id, self.title, ProgressMode.INDETERMINATE),),
            TaskConnectionRequirement.CONNECTED,
            self.cancellable,
            CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT,
        )


@dataclass(frozen=True, slots=True)
class LoadAdvancedRamImageRequest(_RamOperationRequest):
    title = "Load RAM Image"
    step_id = "load_ram_image"
    cancellable = True


@dataclass(frozen=True, slots=True)
class CheckAdvancedRamCrcRequest(_RamOperationRequest):
    title = "Check RAM CRC"
    step_id = "check_ram_crc"


@dataclass(frozen=True, slots=True)
class RunAdvancedRamImageRequest(_RamOperationRequest):
    title = "Run RAM Image"
    step_id = "run_ram_image"


@dataclass(frozen=True, slots=True)
class AdvancedRamOperationSnapshot:
    connection_id: str
    target_key: str
    selection_revision: int
    operation_result: OperationResult

    def __post_init__(self) -> None:
        if not self.connection_id:
            raise ValueError("connection_id must not be empty")
        _target_key(self.target_key)
        _revision(self.selection_revision)
        if not isinstance(self.operation_result, OperationResult):
            raise TypeError("operation_result must be OperationResult")


__all__ = [
    "AdvancedRamOperationSnapshot",
    "CheckAdvancedRamCrcRequest",
    "LoadAdvancedRamImageRequest",
    "PrepareRamImageRequest",
    "PreparedRamImageSummary",
    "RunAdvancedRamImageRequest",
]
