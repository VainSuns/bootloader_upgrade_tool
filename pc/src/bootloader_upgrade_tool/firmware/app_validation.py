"""CPU1 Slot A App image range validation."""

from __future__ import annotations

from .models import FirmwareImage


SLOT_A_REGION_START = 0x082000
SLOT_A_METADATA_START = 0x082000
SLOT_A_METADATA_WORDS = 1024
SLOT_A_METADATA_END = 0x082400
SLOT_A_APP_START = 0x082400
SLOT_A_APP_END_EXCLUSIVE = 0x0C0000

APP_FLASH_START = SLOT_A_APP_START
APP_FLASH_END_EXCLUSIVE = SLOT_A_APP_END_EXCLUSIVE


def _metadata_message(start: int, end_exclusive: int) -> str:
    return (
        f"firmware block 0x{start:08X}-0x{end_exclusive - 1:08X} overlaps "
        f"Slot A metadata area 0x{SLOT_A_METADATA_START:08X}-0x{SLOT_A_METADATA_END - 1:08X}; "
        f"relink the App to start at 0x{SLOT_A_APP_START:08X} or later"
    )


def validate_app_firmware_image(image: FirmwareImage) -> None:
    for block in image.blocks:
        if block.address < SLOT_A_METADATA_END and block.end_exclusive > SLOT_A_METADATA_START:
            raise ValueError(_metadata_message(block.address, block.end_exclusive))
    if not (APP_FLASH_START <= image.entry_point < APP_FLASH_END_EXCLUSIVE):
        raise ValueError(
            f"entry point 0x{image.entry_point:08X} is outside Slot A App range "
            f"0x{APP_FLASH_START:08X}-0x{APP_FLASH_END_EXCLUSIVE - 1:08X}; "
            f"0x{SLOT_A_METADATA_START:08X}-0x{SLOT_A_METADATA_END - 1:08X} "
            f"is reserved for Slot A metadata"
        )
    if image.entry_point % 8:
        raise ValueError(f"entry point 0x{image.entry_point:08X} is not 8-word aligned")
    for block in image.blocks:
        if block.address < APP_FLASH_START or block.end_exclusive > APP_FLASH_END_EXCLUSIVE:
            raise ValueError(
                f"firmware block 0x{block.address:08X}-0x{block.end_exclusive - 1:08X} "
                f"is outside Slot A App range 0x{APP_FLASH_START:08X}-"
                f"0x{APP_FLASH_END_EXCLUSIVE - 1:08X}"
            )
