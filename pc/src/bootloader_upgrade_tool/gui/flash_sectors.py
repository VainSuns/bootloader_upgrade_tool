"""GUI-side Flash sector helpers for F28377D CPU1 app images."""

from __future__ import annotations

from ..firmware import (
    APP_FLASH_END_EXCLUSIVE,
    APP_FLASH_START,
    FirmwareImage,
    SLOT_A_APP_END_EXCLUSIVE,
    SLOT_A_APP_START,
    SLOT_A_METADATA_END,
    SLOT_A_METADATA_START,
    SLOT_A_METADATA_WORDS,
    SLOT_A_REGION_START,
    validate_app_firmware_image,
)
ALLOWED_ERASE_MASK = 0x00003FFE

# Flash B includes Slot A metadata and App data. Erase may include Flash B;
# App Program/Verify payloads must use APP_FLASH_START and avoid metadata words.
SECTORS = (
    ("FLASHA", 0x080000, 0x082000, 0),
    ("FLASHB", 0x082000, 0x084000, 1),
    ("FLASHC", 0x084000, 0x086000, 2),
    ("FLASHD", 0x086000, 0x088000, 3),
    ("FLASHE", 0x088000, 0x090000, 4),
    ("FLASHF", 0x090000, 0x098000, 5),
    ("FLASHG", 0x098000, 0x0A0000, 6),
    ("FLASHH", 0x0A0000, 0x0A8000, 7),
    ("FLASHI", 0x0A8000, 0x0B0000, 8),
    ("FLASHJ", 0x0B0000, 0x0B8000, 9),
    ("FLASHK", 0x0B8000, 0x0BA000, 10),
    ("FLASHL", 0x0BA000, 0x0BC000, 11),
    ("FLASHM", 0x0BC000, 0x0BE000, 12),
    ("FLASHN", 0x0BE000, 0x0C0000, 13),
)


def touched_sector_names(image: FirmwareImage) -> tuple[str, ...]:
    names: list[str] = []
    for block in image.blocks:
        for name, sector_start, sector_end, _bit in SECTORS:
            if block.address < sector_end and block.end_exclusive > sector_start:
                names.append(name)
    return tuple(dict.fromkeys(names))


def calculate_sector_mask(image: FirmwareImage) -> int:
    mask = 0
    for block in image.blocks:
        for _name, sector_start, sector_end, bit in SECTORS:
            if block.address < sector_end and block.end_exclusive > sector_start:
                mask |= 1 << bit
    if mask & 0x1:
        raise ValueError("calculated sector_mask includes Sector A")
    if mask == 0:
        raise ValueError("image does not touch any known Flash sector")
    if mask & ~ALLOWED_ERASE_MASK:
        raise ValueError(f"calculated sector_mask 0x{mask:08X} exceeds allowed app mask")
    return mask
