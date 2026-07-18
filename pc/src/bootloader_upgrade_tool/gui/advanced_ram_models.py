"""Immutable requests and snapshots for Advanced RAM image operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from ..images.models import RamImageIdentity
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
        if type(self.source_path) is not str or not self.source_path.strip():
            raise ValueError("source_path must be a non-empty string")
        object.__setattr__(self, "source_path", self.source_path.strip())

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


def _identity(value: object) -> RamImageIdentity:
    if type(value) is not RamImageIdentity:
        raise TypeError("expected_image_identity must be the canonical RamImageIdentity")
    if value.total_words <= 0:
        raise ValueError("expected_image_identity total_words must be positive")
    return value


class AdvancedRamOperationType(Enum):
    LOAD = auto()
    CHECK_CRC = auto()
    RUN = auto()


@dataclass(frozen=True, slots=True)
class _MaterializedRamOperationRequest:
    connection_id: str
    target_key: str
    image_source_path: str
    selection_revision: int
    image_tool_configuration_revision: int
    expected_image_identity: RamImageIdentity

    title = "RAM Operation"
    step_id = "ram_operation"
    cancellable = False

    def __post_init__(self) -> None:
        if not isinstance(self.connection_id, str) or not self.connection_id.strip():
            raise ValueError("connection_id must not be empty")
        _target_key(self.target_key)
        _revision(self.selection_revision)
        _revision(self.image_tool_configuration_revision)
        _identity(self.expected_image_identity)
        if type(self.image_source_path) is not str or not self.image_source_path.strip():
            raise ValueError("image_source_path must be a non-empty string")
        object.__setattr__(
            self,
            "image_source_path",
            str(Path(self.image_source_path.strip()).expanduser().resolve(strict=False)),
        )

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
class LoadAdvancedRamImageRequest(_MaterializedRamOperationRequest):
    title = "Load RAM Image"
    step_id = "load_ram_image"
    cancellable = True


@dataclass(frozen=True, slots=True)
class CheckAdvancedRamCrcRequest(_MaterializedRamOperationRequest):
    title = "Check RAM CRC"
    step_id = "check_ram_crc"


@dataclass(frozen=True, slots=True)
class RunAdvancedRamImageRequest:
    connection_id: str
    target_key: str
    selection_revision: int
    expected_image_identity: RamImageIdentity

    title = "Run RAM Image"
    step_id = "run_ram_image"
    cancellable = False

    def __post_init__(self) -> None:
        if not isinstance(self.connection_id, str) or not self.connection_id.strip():
            raise ValueError("connection_id must not be empty")
        _target_key(self.target_key)
        _revision(self.selection_revision)
        _identity(self.expected_image_identity)

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
class AdvancedRamOperationSnapshot:
    connection_id: str
    target_key: str
    selection_revision: int
    image_identity: RamImageIdentity
    operation_type: AdvancedRamOperationType
    operation_result: OperationResult

    def __post_init__(self) -> None:
        if not self.connection_id:
            raise ValueError("connection_id must not be empty")
        _target_key(self.target_key)
        _revision(self.selection_revision)
        _identity(self.image_identity)
        if not isinstance(self.operation_type, AdvancedRamOperationType):
            raise TypeError("operation_type must be AdvancedRamOperationType")
        if not isinstance(self.operation_result, OperationResult):
            raise TypeError("operation_result must be OperationResult")


__all__ = [
    "AdvancedRamOperationType",
    "AdvancedRamOperationSnapshot",
    "CheckAdvancedRamCrcRequest",
    "LoadAdvancedRamImageRequest",
    "PrepareRamImageRequest",
    "PreparedRamImageSummary",
    "RunAdvancedRamImageRequest",
]
