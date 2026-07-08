"""Flash App image preparation."""

from __future__ import annotations

from pathlib import Path

from ..core.workflow import calculate_programmed_image_crc32, _programmed_image_size_and_end
from ..firmware.flash_layout import image_sector_mask
from ..targets.profiles import TargetProfile
from .models import ImageIdentity, PreparedFlashImage, load_firmware_image


def _inside_any(start: int, end_exclusive: int, ranges: object) -> bool:
    return any(item.contains_range(start, end_exclusive - start) for item in ranges)  # type: ignore[union-attr]


def prepare_flash_app_image(
    app_image_path: str | Path,
    *,
    target: TargetProfile,
    hex2000: str | None = None,
    sci8_txt: str | Path | None = None,
    keep_sci8_txt: bool = False,
) -> PreparedFlashImage:
    flash = target.memory_map.flash
    metadata = target.memory_map.metadata
    if flash is None or metadata is None:
        raise ValueError("target must define flash and metadata layouts")
    image, generated = load_firmware_image(
        app_image_path,
        hex2000=hex2000,
        sci8_txt=sci8_txt,
        keep_sci8_txt=keep_sci8_txt,
    )
    if not _inside_any(image.entry_point, image.entry_point + 1, flash.app_ranges):
        raise ValueError("Flash App entry point is outside target app ranges")
    if image.entry_point % 8:
        raise ValueError("Flash App entry point must be 8-word aligned")
    for block in image.blocks:
        if not _inside_any(block.address, block.end_exclusive, flash.app_ranges):
            raise ValueError("Flash App block is outside target app ranges")
        if metadata.range.contains_range(block.address, len(block.words)):
            raise ValueError("Flash App block overlaps metadata range")
    sector_mask = image_sector_mask(image)
    if sector_mask == 0:
        raise ValueError("image does not touch any known Flash sector")
    if sector_mask & flash.forbidden_erase_mask:
        raise ValueError("image requires a forbidden erase sector")
    if sector_mask & ~flash.allowed_erase_mask:
        raise ValueError("image requires a sector outside target erase mask")
    size_words, app_end = _programmed_image_size_and_end(image, 248)
    return PreparedFlashImage(
        image=image,
        identity=ImageIdentity(
            image.entry_point,
            size_words,
            calculate_programmed_image_crc32(image, 248),
            app_end,
        ),
        sector_mask=sector_mask | flash.metadata_sector_mask,
        generated_sci8_txt=generated,
    )
