"""Immutable GUI requests and summaries for local CPU1 image preparation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)


class ImageSourceKind(str, Enum):
    OUT = ".out"
    TXT = ".txt"


class Hex2000Source(str, Enum):
    GLOBAL_SETTINGS = "Global Settings"
    C2000_CG_ROOT = "C2000_CG_ROOT"
    NOT_USED = "Not used"


@dataclass(frozen=True, slots=True)
class SourceFileFingerprint:
    resolved_path: str
    size_bytes: int
    mtime_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved_path", str(Path(self.resolved_path).expanduser().resolve(strict=False)))
        if self.size_bytes < 0 or self.mtime_ns < 0:
            raise ValueError("file fingerprint values must be non-negative")


@dataclass(frozen=True, slots=True)
class PrepareFlashImageRequest:
    target_key: str
    source_path: str
    selection_revision: int

    def __post_init__(self) -> None:
        if self.target_key not in {"cpu1", "cpu2"}:
            raise ValueError("target_key must be 'cpu1' or 'cpu2'")
        raw_path = str(self.source_path).strip() if isinstance(self.source_path, (str, Path)) else ""
        object.__setattr__(self, "source_path", raw_path)
        if not isinstance(self.selection_revision, int) or isinstance(self.selection_revision, bool) or self.selection_revision < 0:
            raise ValueError("selection_revision must be a non-negative integer")

    def create_plan(self, task_id: str) -> TaskPlan:
        title = f"Prepare {self.target_key.upper()} App Image"
        return TaskPlan(
            task_id,
            title,
            (TaskStepPlan("prepare_flash_image", title, ProgressMode.INDETERMINATE),),
            TaskConnectionRequirement.NONE,
            False,
            CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS,
        )


@dataclass(frozen=True, slots=True)
class PreparedImageSummary:
    target_key: str
    selection_revision: int
    source_path: str
    source_kind: ImageSourceKind
    source_fingerprint: SourceFileFingerprint
    entry_point: int
    image_size_words: int
    image_crc32: int
    app_end: int
    image_sector_mask: int
    effective_sector_mask: int
    image_sector_bits: tuple[int, ...]
    hex2000_source: Hex2000Source
    hex2000_executable: str | None

    def __post_init__(self) -> None:
        if self.target_key not in {"cpu1", "cpu2"}:
            raise ValueError("target_key must be 'cpu1' or 'cpu2'")
        if not isinstance(self.source_kind, ImageSourceKind):
            raise TypeError("source_kind must be ImageSourceKind")
        if not isinstance(self.source_fingerprint, SourceFileFingerprint):
            raise TypeError("source_fingerprint must be SourceFileFingerprint")
        if not isinstance(self.hex2000_source, Hex2000Source):
            raise TypeError("hex2000_source must be Hex2000Source")
        object.__setattr__(self, "source_path", str(Path(self.source_path).expanduser().resolve(strict=False)))
        object.__setattr__(self, "image_sector_bits", tuple(self.image_sector_bits))
        if any(not isinstance(bit, int) or bit < 0 for bit in self.image_sector_bits):
            raise ValueError("image_sector_bits must contain non-negative integers")
        if self.image_size_words <= 0 or self.app_end <= 0:
            raise ValueError("prepared image summary contains invalid image values")
        if self.image_sector_mask <= 0 or self.effective_sector_mask <= 0:
            raise ValueError("prepared image summary contains invalid sector masks")


__all__ = [
    "Hex2000Source",
    "ImageSourceKind",
    "PrepareFlashImageRequest",
    "PreparedImageSummary",
    "SourceFileFingerprint",
]
