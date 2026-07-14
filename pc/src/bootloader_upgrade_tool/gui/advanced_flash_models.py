"""Immutable requests and summaries for Advanced Flash image preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .advanced_ram_models import _revision, _target_key
from .image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from .runtime_models import CompletionPolicy, ProgressMode, TaskConnectionRequirement, TaskPlan, TaskStepPlan


@dataclass(frozen=True, slots=True)
class PrepareAdvancedFlashImageRequest:
    target_key: str
    source_path: str
    selection_revision: int
    configuration_revision: int

    def __post_init__(self) -> None:
        _target_key(self.target_key)
        _revision(self.selection_revision)
        _revision(self.configuration_revision)
        object.__setattr__(self, "source_path", str(self.source_path).strip())

    def create_plan(self, task_id: str) -> TaskPlan:
        title = f"Prepare {self.target_key.upper()} Flash App Image"
        return TaskPlan(
            task_id,
            title,
            (TaskStepPlan("prepare_advanced_flash_image", title, ProgressMode.INDETERMINATE),),
            TaskConnectionRequirement.NONE,
            False,
            CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS,
        )


@dataclass(frozen=True, slots=True)
class PreparedAdvancedFlashImageSummary:
    target_key: str
    source_path: str
    selection_revision: int
    configuration_revision: int
    source_kind: ImageSourceKind
    source_fingerprint: SourceFileFingerprint
    entry_point: int
    image_size_words: int
    image_crc32: int
    app_end: int
    image_sector_mask: int
    effective_sector_mask: int
    hex2000_source: Hex2000Source
    hex2000_executable: str | None

    def __post_init__(self) -> None:
        _target_key(self.target_key)
        _revision(self.selection_revision)
        _revision(self.configuration_revision)
        object.__setattr__(self, "source_path", str(Path(self.source_path).resolve(strict=False)))
        if self.image_size_words <= 0 or self.image_sector_mask <= 0 or self.effective_sector_mask <= 0:
            raise ValueError("prepared Advanced Flash summary contains invalid image values")


__all__ = ["PrepareAdvancedFlashImageRequest", "PreparedAdvancedFlashImageSummary"]
