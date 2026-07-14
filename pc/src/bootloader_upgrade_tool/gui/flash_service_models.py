"""Immutable requests and summaries for CPU1 Flash Service preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .advanced_ram_models import _revision
from .image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from .runtime_models import CompletionPolicy, ProgressMode, TaskConnectionRequirement, TaskPlan, TaskStepPlan


@dataclass(frozen=True, slots=True)
class PrepareFlashServiceRequest:
    service_image_path: str
    service_map_path: str
    descriptor_symbol: str
    configuration_revision: int
    tool_configuration_revision: int
    target_key: str = "cpu1"

    def __post_init__(self) -> None:
        if self.target_key != "cpu1":
            raise ValueError("only target_key 'cpu1' is supported")
        _revision(self.configuration_revision)
        _revision(self.tool_configuration_revision)
        object.__setattr__(self, "service_image_path", str(self.service_image_path).strip())
        object.__setattr__(self, "service_map_path", str(self.service_map_path).strip())
        object.__setattr__(self, "descriptor_symbol", str(self.descriptor_symbol).strip())

    def create_plan(self, task_id: str) -> TaskPlan:
        return TaskPlan(
            task_id,
            "Prepare CPU1 Flash Service",
            (TaskStepPlan("prepare_flash_service", "Prepare CPU1 Flash Service", ProgressMode.INDETERMINATE),),
            TaskConnectionRequirement.NONE,
            False,
            CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS,
        )


@dataclass(frozen=True, slots=True)
class PreparedFlashServiceSummary:
    target_key: str
    service_image_path: str
    service_map_path: str
    descriptor_symbol: str
    configuration_revision: int
    tool_configuration_revision: int
    image_source_kind: ImageSourceKind
    image_fingerprint: SourceFileFingerprint
    map_fingerprint: SourceFileFingerprint
    descriptor_address: int
    api_table_address: int
    crc_patch_address: int
    total_words: int
    expected_crc32: int
    hex2000_source: Hex2000Source
    hex2000_executable: str | None

    def __post_init__(self) -> None:
        if self.target_key != "cpu1":
            raise ValueError("only target_key 'cpu1' is supported")
        _revision(self.configuration_revision)
        _revision(self.tool_configuration_revision)
        object.__setattr__(self, "service_image_path", str(Path(self.service_image_path).resolve(strict=False)))
        object.__setattr__(self, "service_map_path", str(Path(self.service_map_path).resolve(strict=False)))
        if self.total_words <= 0:
            raise ValueError("total_words must be positive")


__all__ = ["PrepareFlashServiceRequest", "PreparedFlashServiceSummary"]
