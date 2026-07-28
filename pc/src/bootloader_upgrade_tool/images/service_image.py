"""Downloaded flash_service_lib image preparation."""

from __future__ import annotations

from pathlib import Path

from ..firmware import (
    calculate_service_ram_load_crc32,
    parse_flash_service_symbols_from_map,
    patch_flash_service_image,
)
from ..protocol.constants import SERVICE_HEADER_WORDS, SERVICE_REQUIRED_CAPABILITIES
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
    header_symbol: str = "g_boot_flash_service_header",
    hex2000: str | None = None,
    required_capabilities: int = int(SERVICE_REQUIRED_CAPABILITIES),
    work_dir: str | Path | None = None,
) -> PreparedServiceImage:
    ram = target.memory_map.ram
    if ram is None:
        raise ValueError("target must define a RAM layout")
    image, _generated = load_firmware_image(
        service_image_path, hex2000=hex2000, work_dir=work_dir
    )
    symbols = parse_flash_service_symbols_from_map(
        Path(service_map_path),
        header_symbol=header_symbol,
    )
    symbol_ranges = (
        (symbols.header_address, symbols.header_address + SERVICE_HEADER_WORDS),
        (symbols.publish_state_address, symbols.publish_state_address + 2),
        (symbols.runtime_state_address, symbols.runtime_state_address + 1),
        (symbols.app_export_address, symbols.app_export_address + 2),
        (symbols.immutable_start, symbols.immutable_end_exclusive),
        (symbols.boot_init_address, symbols.boot_init_address + 1),
        (symbols.boot_handle_command_address, symbols.boot_handle_command_address + 1),
        (symbols.confirm_current_image_address, symbols.confirm_current_image_address + 1),
    )
    if any(
        not _inside_any(start, end, ram.service_ranges)
        or _overlaps(start, end, ram.reserved_ranges)
        for start, end in symbol_ranges
    ):
        raise ValueError("service map symbol is outside target service RAM")
    for block in image.blocks:
        if not _inside_any(block.address, block.end_exclusive, ram.service_ranges):
            raise ValueError("service image block is outside target service RAM")
        if _overlaps(block.address, block.end_exclusive, ram.reserved_ranges):
            raise ValueError("service image block overlaps reserved RAM")
    patched = patch_flash_service_image(
        image,
        symbols=symbols,
        capabilities=required_capabilities,
    )
    expected_crc32 = calculate_service_ram_load_crc32(patched, 248)
    return PreparedServiceImage(
        image=patched,
        header_address=symbols.header_address,
        total_words=patched.total_words,
        expected_crc32=expected_crc32,
        required_capabilities=required_capabilities,
    )
