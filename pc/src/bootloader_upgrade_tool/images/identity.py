"""PC-local image identity comparison."""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol.models import MetadataSummary
from .models import ImageIdentity, PreparedFlashImage


@dataclass(frozen=True)
class ImageMetadataComparison:
    same_image: bool
    metadata_valid: bool
    mismatches: tuple[str, ...]
    reason: str | None = None


def compare_image_identity_with_metadata(
    image_identity: ImageIdentity,
    metadata_summary: MetadataSummary,
) -> ImageMetadataComparison:
    if metadata_summary.metadata_valid == 0:
        return ImageMetadataComparison(False, False, (), "METADATA_INVALID")
    mismatches = tuple(
        name
        for name in ("entry_point", "image_size_words", "image_crc32")
        if getattr(image_identity, name) != getattr(metadata_summary, name)
    )
    if mismatches:
        return ImageMetadataComparison(False, True, mismatches, "IMAGE_IDENTITY_MISMATCH")
    return ImageMetadataComparison(True, True, (), None)


def compare_flash_image_with_metadata(
    image: PreparedFlashImage,
    metadata_summary: MetadataSummary,
) -> ImageMetadataComparison:
    return compare_image_identity_with_metadata(image.identity, metadata_summary)
