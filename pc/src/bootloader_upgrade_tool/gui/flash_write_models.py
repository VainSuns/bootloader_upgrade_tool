"""Immutable user-visible plans for irreversible Flash writes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from ..images import ImageIdentity
from .advanced_flash_operation_models import AdvancedFlashEraseScope
from .advanced_ram_models import _revision
from .flash_service_models import PreparedFlashServiceSummary
from .runtime_v2_models import ConnectionGeneration, RuntimeCpuId, VerifyEvidence
from .status_models import MetadataStatusSnapshot


class FlashWriteOperationType(Enum):
    ERASE = auto()
    PROGRAM_ONLY = auto()
    WRITE_IMAGE_VALID = auto()
    WRITE_BOOT_ATTEMPT = auto()
    WRITE_APP_CONFIRMED = auto()


@dataclass(frozen=True, slots=True)
class FlashWritePlan:
    plan_id: str
    operation_type: FlashWriteOperationType
    cpu_id: RuntimeCpuId
    connection_id: str
    connection_generation: ConnectionGeneration
    transport_label: str
    endpoint_label: str
    image_source_path: str
    image_selection_revision: int
    image_tool_configuration_revision: int
    image_identity: ImageIdentity
    effective_sector_mask: int
    service_configuration_revision: int
    service_tool_configuration_revision: int
    service_summary: PreparedFlashServiceSummary
    erase_scope: AdvancedFlashEraseScope | None = None
    erase_sector_mask: int | None = None
    verify_evidence: VerifyEvidence | None = None
    metadata_snapshot: MetadataStatusSnapshot | None = None

    def __post_init__(self) -> None:
        for name in ("plan_id", "connection_id", "transport_label", "endpoint_label"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if type(self.operation_type) is not FlashWriteOperationType:
            raise TypeError("operation_type must be FlashWriteOperationType")
        if self.cpu_id is not RuntimeCpuId.CPU1:
            raise ValueError("Flash writes support CPU1 only")
        if type(self.connection_generation) is not ConnectionGeneration:
            raise TypeError("connection_generation must be ConnectionGeneration")
        if type(self.image_source_path) is not str or not self.image_source_path.strip():
            raise ValueError("image_source_path must be non-empty")
        object.__setattr__(
            self,
            "image_source_path",
            str(Path(self.image_source_path.strip()).expanduser().resolve(strict=False)),
        )
        for revision in (
            self.image_selection_revision,
            self.image_tool_configuration_revision,
            self.service_configuration_revision,
            self.service_tool_configuration_revision,
        ):
            _revision(revision)
        if type(self.image_identity) is not ImageIdentity:
            raise TypeError("image_identity must be the canonical ImageIdentity")
        if type(self.effective_sector_mask) is not int or self.effective_sector_mask <= 0:
            raise ValueError("effective_sector_mask must be positive")
        if type(self.service_summary) is not PreparedFlashServiceSummary:
            raise TypeError("service_summary must be PreparedFlashServiceSummary")
        if (
            self.service_summary.target_key != "cpu1"
            or self.service_summary.resource_revision != self.service_configuration_revision
            or self.service_summary.tool_configuration_revision
            != self.service_tool_configuration_revision
        ):
            raise ValueError("service_summary revisions must match the plan")
        self._validate_operation_fields()

    def _validate_operation_fields(self) -> None:
        if self.operation_type is FlashWriteOperationType.ERASE:
            if not isinstance(self.erase_scope, AdvancedFlashEraseScope):
                raise TypeError("Erase requires erase_scope")
            if type(self.erase_sector_mask) is not int or self.erase_sector_mask <= 0:
                raise ValueError("Erase requires a positive erase_sector_mask")
            if self.verify_evidence is not None or self.metadata_snapshot is not None:
                raise ValueError("Erase cannot carry evidence or Metadata")
            return
        if self.erase_scope is not None or self.erase_sector_mask is not None:
            raise ValueError("Only Erase carries erase fields")
        if self.operation_type is FlashWriteOperationType.PROGRAM_ONLY:
            if self.verify_evidence is not None or self.metadata_snapshot is not None:
                raise ValueError("Program Only cannot carry evidence or Metadata")
            return
        if self.operation_type is FlashWriteOperationType.WRITE_IMAGE_VALID:
            if type(self.verify_evidence) is not VerifyEvidence:
                raise TypeError("IMAGE_VALID requires exact VerifyEvidence")
            if (
                self.verify_evidence.cpu_id is not RuntimeCpuId.CPU1
                or self.verify_evidence.image_identity != self.image_identity
            ):
                raise ValueError("VerifyEvidence must match the CPU1 image")
            if self.metadata_snapshot is not None:
                raise ValueError("IMAGE_VALID cannot carry Metadata")
            return
        if self.verify_evidence is not None:
            raise ValueError("BOOT_ATTEMPT and APP_CONFIRMED cannot carry VerifyEvidence")
        if type(self.metadata_snapshot) is not MetadataStatusSnapshot:
            raise TypeError("Metadata write requires exact MetadataStatusSnapshot")
        snapshot = self.metadata_snapshot
        raw = snapshot.raw_metadata
        if (
            snapshot.connection_id != self.connection_id
            or snapshot.target_key != "cpu1"
            or raw.entry_point != self.image_identity.entry_point
            or raw.image_size_words != self.image_identity.image_size_words
            or raw.image_crc32 != self.image_identity.image_crc32
        ):
            raise ValueError("Metadata snapshot must match the connection and image")

    @property
    def operation_display_name(self) -> str:
        return {
            FlashWriteOperationType.ERASE: "Erase",
            FlashWriteOperationType.PROGRAM_ONLY: "Program Only",
            FlashWriteOperationType.WRITE_IMAGE_VALID: "Write IMAGE_VALID",
            FlashWriteOperationType.WRITE_BOOT_ATTEMPT: "Write BOOT_ATTEMPT",
            FlashWriteOperationType.WRITE_APP_CONFIRMED: "Write APP_CONFIRMED",
        }[self.operation_type]

    @property
    def metadata_record_name(self) -> str | None:
        return {
            FlashWriteOperationType.WRITE_IMAGE_VALID: "IMAGE_VALID",
            FlashWriteOperationType.WRITE_BOOT_ATTEMPT: "BOOT_ATTEMPT",
            FlashWriteOperationType.WRITE_APP_CONFIRMED: "APP_CONFIRMED",
        }.get(self.operation_type)

    @property
    def boot_attempt_count_before(self) -> int | None:
        return (
            self.metadata_snapshot.raw_metadata.boot_attempt_count
            if self.metadata_snapshot is not None
            else None
        )

    @property
    def app_confirmed_before(self) -> bool | None:
        return self.metadata_snapshot.app_confirmed if self.metadata_snapshot is not None else None


__all__ = ["FlashWriteOperationType", "FlashWritePlan"]
