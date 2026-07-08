"""RAM App image preparation."""

from __future__ import annotations

from pathlib import Path

from ..core.workflow import calculate_ram_image_crc32
from ..targets.profiles import TargetProfile
from .models import PreparedRamImage, load_firmware_image


def _inside_any(start: int, end_exclusive: int, ranges: object) -> bool:
    return any(item.contains_range(start, end_exclusive - start) for item in ranges)  # type: ignore[union-attr]


def _overlaps(start: int, end_exclusive: int, ranges: object) -> bool:
    return any(start < item.end_exclusive and end_exclusive > item.start for item in ranges)  # type: ignore[union-attr]


def prepare_ram_app_image(
    ram_image_path: str | Path,
    *,
    target: TargetProfile,
    hex2000: str | None = None,
    sci8_txt: str | Path | None = None,
    keep_sci8_txt: bool = False,
) -> PreparedRamImage:
    ram = target.memory_map.ram
    if ram is None:
        raise ValueError("target must define a RAM layout")
    image, generated = load_firmware_image(
        ram_image_path,
        hex2000=hex2000,
        sci8_txt=sci8_txt,
        keep_sci8_txt=keep_sci8_txt,
    )
    if not _inside_any(image.entry_point, image.entry_point + 1, ram.ram_app_ranges):
        raise ValueError("RAM App entry point is outside target RAM app ranges")
    for block in image.blocks:
        if not _inside_any(block.address, block.end_exclusive, ram.ram_app_ranges):
            raise ValueError("RAM App block is outside target RAM app ranges")
        if _overlaps(block.address, block.end_exclusive, ram.reserved_ranges):
            raise ValueError("RAM App block overlaps reserved RAM")
        if _overlaps(block.address, block.end_exclusive, ram.service_ranges):
            raise ValueError("RAM App block overlaps service RAM")
    return PreparedRamImage(
        image=image,
        entry_point=image.entry_point,
        total_words=image.total_words,
        image_crc32=calculate_ram_image_crc32(image, 248),
        generated_sci8_txt=generated,
    )
