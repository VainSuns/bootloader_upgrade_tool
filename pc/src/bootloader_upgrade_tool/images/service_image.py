"""Downloaded flash_service_lib image preparation."""

from __future__ import annotations

from pathlib import Path

from ..firmware import (
    calculate_service_ram_load_crc32_descriptor_last,
    parse_flash_service_symbols_from_map,
    patch_flash_service_image,
)
from ..protocol.constants import SERVICE_DESCRIPTOR_WORDS, SERVICE_REQUIRED_CAPABILITIES
from ..targets.profiles import TargetProfile
from .models import PreparedServiceImage, load_firmware_image


def _inside_any(start: int, end_exclusive: int, ranges: object) -> bool:
    return any(item.contains_range(start, end_exclusive - start) for item in ranges)  # type: ignore[union-attr]


def _overlaps(start: int, end_exclusive: int, ranges: object) -> bool:
    return any(start < item.end_exclusive and end_exclusive > item.start for item in ranges)  # type: ignore[union-attr]


def prepare_service_image(
    service_image_path: str | Path,
    service_map_path: str | Path,
    *,
    target: TargetProfile,
    descriptor_symbol: str = "g_boot_flash_service_descriptor",
    hex2000: str | None = None,
    required_capabilities: int = int(SERVICE_REQUIRED_CAPABILITIES),
) -> PreparedServiceImage:
    ram = target.memory_map.ram
    if ram is None:
        raise ValueError("target must define a RAM layout")
    image, _generated = load_firmware_image(service_image_path, hex2000=hex2000)
    symbols = parse_flash_service_symbols_from_map(
        Path(service_map_path),
        descriptor_symbol=descriptor_symbol,
    )
    for block in image.blocks:
        if not _inside_any(block.address, block.end_exclusive, ram.service_ranges):
            raise ValueError("service image block is outside target service RAM")
        if _overlaps(block.address, block.end_exclusive, ram.reserved_ranges):
            raise ValueError("service image block overlaps reserved RAM")
    patched = patch_flash_service_image(
        image,
        descriptor_address=symbols.descriptor_address,
        api_table_address=symbols.api_table_address,
        crc_patch_address=symbols.crc_patch_address,
        capabilities=required_capabilities,
        load_order="descriptor_last",
        descriptor_words=SERVICE_DESCRIPTOR_WORDS,
        max_data_words=248,
    )
    expected_crc32 = calculate_service_ram_load_crc32_descriptor_last(
        patched,
        symbols.descriptor_address,
        SERVICE_DESCRIPTOR_WORDS,
        248,
    )
    return PreparedServiceImage(
        image=patched,
        descriptor_address=symbols.descriptor_address,
        api_table_address=symbols.api_table_address,
        crc_patch_address=symbols.crc_patch_address,
        total_words=patched.total_words,
        expected_crc32=expected_crc32,
        required_capabilities=required_capabilities,
    )
