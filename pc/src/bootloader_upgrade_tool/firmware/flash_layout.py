"""CPU1 Slot A Flash sector mask helpers."""

from __future__ import annotations

from .app_validation import validate_app_firmware_image
from .models import FirmwareImage


ALLOWED_ERASE_MASK = 0x00003FFE
METADATA_SECTOR_MASK = 0x00000002

SECTORS = (
    (0x080000, 0x082000, 0),
    (0x082000, 0x084000, 1),
    (0x084000, 0x086000, 2),
    (0x086000, 0x088000, 3),
    (0x088000, 0x090000, 4),
    (0x090000, 0x098000, 5),
    (0x098000, 0x0A0000, 6),
    (0x0A0000, 0x0A8000, 7),
    (0x0A8000, 0x0B0000, 8),
    (0x0B0000, 0x0B8000, 9),
    (0x0B8000, 0x0BA000, 10),
    (0x0BA000, 0x0BC000, 11),
    (0x0BC000, 0x0BE000, 12),
    (0x0BE000, 0x0C0000, 13),
)


def image_sector_mask(image: FirmwareImage) -> int:
    mask = 0
    for block in image.blocks:
        for start, end, bit in SECTORS:
            if block.address < end and block.end_exclusive > start:
                mask |= 1 << bit
    return mask


def validate_manual_erase_mask(sector_mask: int) -> None:
    if sector_mask == 0:
        raise ValueError("sector-mask must be nonzero")
    if sector_mask & 0x1:
        raise ValueError("sector-mask must not erase Sector A / bootloader")
    if sector_mask & ~ALLOWED_ERASE_MASK:
        raise ValueError("sector-mask contains sectors outside Slot A App erase mask")


def validate_sector_mask_for_image(sector_mask: int, image: FirmwareImage) -> None:
    validate_app_firmware_image(image)
    validate_manual_erase_mask(sector_mask)
    needed = image_sector_mask(image)
    if needed == 0 or (needed & ~sector_mask):
        raise ValueError(
            f"sector-mask 0x{sector_mask:08X} does not cover image sectors 0x{needed:08X}"
        )


def calculate_app_sector_mask(image: FirmwareImage) -> int:
    validate_app_firmware_image(image)
    mask = image_sector_mask(image)
    if mask == 0:
        raise ValueError("image does not touch any known Flash sector")
    validate_manual_erase_mask(mask)
    return mask


def resolve_manual_erase_masks(sector_mask: int) -> dict[str, int | list[int]]:
    validate_manual_erase_mask(sector_mask)
    erased_masks: list[int] = []
    if sector_mask & METADATA_SECTOR_MASK:
        erased_masks.append(METADATA_SECTOR_MASK)
    rest = sector_mask & ~METADATA_SECTOR_MASK
    if rest:
        erased_masks.append(rest)
    return {
        "requested_mask": sector_mask,
        "erased_masks": erased_masks,
    }


def resolve_dfu_erase_masks(
    image: FirmwareImage, requested_mask: int | None
) -> dict[str, int]:
    app_mask = calculate_app_sector_mask(image)
    mask = app_mask if requested_mask is None else requested_mask
    validate_sector_mask_for_image(mask, image)
    effective = mask | METADATA_SECTOR_MASK
    validate_manual_erase_mask(effective)
    return {
        "app_image_mask": app_mask,
        "requested_mask": mask,
        "effective_mask": effective,
        "first_erase_mask": METADATA_SECTOR_MASK,
        "second_erase_mask": effective & ~METADATA_SECTOR_MASK,
    }
