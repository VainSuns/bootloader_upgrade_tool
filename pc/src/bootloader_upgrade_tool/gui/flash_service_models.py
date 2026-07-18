"""Immutable application-owned Flash Service resource models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from .advanced_ram_models import _revision
from .image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from .runtime_models import CompletionPolicy, ProgressMode, TaskConnectionRequirement, TaskPlan, TaskStepPlan


DEFAULT_SERVICE_DESCRIPTOR_SYMBOL = "g_boot_flash_service_descriptor"


class FlashServiceResourceStatus(Enum):
    UNAVAILABLE = auto()
    UNVALIDATED = auto()
    READY = auto()
    ERROR = auto()
    STALE = auto()


@dataclass(frozen=True, slots=True)
class PrepareFlashServiceRequest:
    resource_revision: int
    tool_configuration_revision: int
    target_key: str = "cpu1"

    def __post_init__(self) -> None:
        _revision(self.resource_revision)
        _revision(self.tool_configuration_revision)
        if self.target_key != "cpu1":
            raise ValueError("only target_key 'cpu1' is supported")

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
    provider_name: str
    service_image_path: str
    service_map_path: str
    descriptor_symbol: str
    resource_revision: int
    tool_configuration_revision: int
    image_source_kind: ImageSourceKind
    image_fingerprint: SourceFileFingerprint
    map_fingerprint: SourceFileFingerprint
    descriptor_address: int
    api_table_address: int
    crc_patch_address: int
    total_words: int
    expected_crc32: int
    required_capabilities: int
    hex2000_source: Hex2000Source
    hex2000_executable: str | None

    def __post_init__(self) -> None:
        if self.target_key != "cpu1":
            raise ValueError("only target_key 'cpu1' is supported")
        if type(self.provider_name) is not str or not self.provider_name.strip():
            raise ValueError("provider_name must not be empty")
        if self.descriptor_symbol != DEFAULT_SERVICE_DESCRIPTOR_SYMBOL:
            raise ValueError("descriptor_symbol must be the canonical Flash Service symbol")
        _revision(self.resource_revision)
        _revision(self.tool_configuration_revision)
        for name in ("image_source_kind", "hex2000_source"):
            expected = ImageSourceKind if name == "image_source_kind" else Hex2000Source
            if not isinstance(getattr(self, name), expected):
                raise TypeError(f"{name} must be {expected.__name__}")
        for name in ("image_fingerprint", "map_fingerprint"):
            if type(getattr(self, name)) is not SourceFileFingerprint:
                raise TypeError(f"{name} must be SourceFileFingerprint")
        for name in (
            "descriptor_address", "api_table_address", "crc_patch_address",
            "total_words", "expected_crc32", "required_capabilities",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.total_words == 0:
            raise ValueError("total_words must be positive")
        object.__setattr__(self, "provider_name", self.provider_name.strip())
        object.__setattr__(self, "service_image_path", _normalized_path(self.service_image_path))
        object.__setattr__(self, "service_map_path", _normalized_path(self.service_map_path))
        if self.image_fingerprint.resolved_path != self.service_image_path:
            raise ValueError("image_fingerprint path must match service_image_path")
        if self.map_fingerprint.resolved_path != self.service_map_path:
            raise ValueError("map_fingerprint path must match service_map_path")
        if self.hex2000_executable is not None:
            if type(self.hex2000_executable) is not str or not self.hex2000_executable.strip():
                raise ValueError("hex2000_executable must be a non-empty string or None")
            object.__setattr__(self, "hex2000_executable", _normalized_path(self.hex2000_executable))
        if self.image_source_kind is ImageSourceKind.TXT:
            if self.hex2000_source is not Hex2000Source.NOT_USED or self.hex2000_executable is not None:
                raise ValueError("TXT service summaries must not use hex2000")
        elif self.hex2000_source is Hex2000Source.NOT_USED or self.hex2000_executable is None:
            raise ValueError("OUT service summaries require hex2000 identity")


@dataclass(frozen=True, slots=True)
class FlashServiceResourceState:
    revision: int
    provider_name: str
    image_path: str | None
    map_path: str | None
    status: FlashServiceResourceStatus
    summary: PreparedFlashServiceSummary | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        _revision(self.revision)
        if type(self.provider_name) is not str or not self.provider_name.strip():
            raise ValueError("provider_name must not be empty")
        if not isinstance(self.status, FlashServiceResourceStatus):
            raise TypeError("status must be FlashServiceResourceStatus")
        object.__setattr__(self, "provider_name", self.provider_name.strip())
        for name in ("image_path", "map_path"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _normalized_path(value))
        has_paths = self.image_path is not None and self.map_path is not None
        has_error = bool(self.error_code and self.error_message)
        if self.status is FlashServiceResourceStatus.UNVALIDATED:
            if not has_paths or self.summary is not None or self.error_code is not None or self.error_message is not None:
                raise ValueError("UNVALIDATED requires paths and no summary or error")
        elif self.status is FlashServiceResourceStatus.READY:
            if not has_paths or type(self.summary) is not PreparedFlashServiceSummary:
                raise ValueError("READY requires paths and a lightweight summary")
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("READY cannot carry an error")
            if (self.summary.service_image_path, self.summary.service_map_path) != (self.image_path, self.map_path):
                raise ValueError("READY summary paths must match resource paths")
            if self.summary.provider_name != self.provider_name or self.summary.resource_revision != self.revision:
                raise ValueError("READY summary provider and revision must match resource state")
        elif self.status in {
            FlashServiceResourceStatus.UNAVAILABLE,
            FlashServiceResourceStatus.ERROR,
            FlashServiceResourceStatus.STALE,
        }:
            if self.summary is not None or not has_error:
                raise ValueError(f"{self.status.name} requires an explicit error and no summary")


def _normalized_path(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("resource paths must be non-empty strings")
    return str(Path(value.strip()).expanduser().resolve(strict=False))


__all__ = [
    "DEFAULT_SERVICE_DESCRIPTOR_SYMBOL",
    "FlashServiceResourceState",
    "FlashServiceResourceStatus",
    "PrepareFlashServiceRequest",
    "PreparedFlashServiceSummary",
]
