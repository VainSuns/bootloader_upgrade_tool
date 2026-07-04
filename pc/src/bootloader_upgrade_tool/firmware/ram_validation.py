"""RAM image validation for the development RAM bootloader carrier."""

from __future__ import annotations

from .models import AddressRange, FirmwareImage


RAM_WRITE_RANGES = (
    AddressRange(0x000000, 0x000002),  # BEGIN
    AddressRange(0x000123, 0x000400),  # RAMM0 usable portion
    AddressRange(0x008000, 0x00C000),  # RAMLS0..5 + RAMD0..1
    AddressRange(0x010000, 0x01BFF8),  # RAMGS candidate range after bootloader carve-out
    AddressRange(0x03F800, 0x040000),  # CPU message RAM
    AddressRange(0x049000, 0x049800),  # CANA message RAM
    AddressRange(0x04B000, 0x04B800),  # CANB message RAM
)

def _inside_any(start: int, end_exclusive: int, ranges: tuple[AddressRange, ...]) -> bool:
    return any(item.start <= start and end_exclusive <= item.end_exclusive for item in ranges)


def validate_ram_firmware_image(image: FirmwareImage) -> None:
    if image.total_words <= 0:
        raise ValueError("RAM image must contain data")
    if not _inside_any(image.entry_point, image.entry_point + 1, RAM_WRITE_RANGES):
        raise ValueError("RAM entry point is outside allowed RAM write ranges")
    for block in image.blocks:
        if block.end_exclusive > 0xFFFFFFFF:
            raise ValueError("RAM image block address wraps uint32")
        if not _inside_any(block.address, block.end_exclusive, RAM_WRITE_RANGES):
            raise ValueError(
                f"RAM image block 0x{block.address:08X}-0x{block.end_exclusive - 1:08X} "
                "is outside allowed RAM write ranges"
            )
