"""Firmware conversion, parsing, and image models."""

from .cmd_memory import (
    MemoryParseError,
    MemoryRegion,
    build_device_info,
    parse_memory_file,
    parse_memory_text,
    write_device_info,
)
from .hex2000 import (
    Hex2000Error,
    Hex2000NotFoundError,
    Sci8BootTable,
    Sci8ParseError,
    build_firmware_image,
    locate_hex2000,
    parse_sci8_file,
    parse_sci8_text,
    run_hex2000,
)
from .models import AddressRange, FirmwareBlock, FirmwareImage
from .app_validation import (
    APP_FLASH_END_EXCLUSIVE,
    APP_FLASH_START,
    SLOT_A_APP_END_EXCLUSIVE,
    SLOT_A_APP_START,
    SLOT_A_METADATA_END,
    SLOT_A_METADATA_START,
    SLOT_A_METADATA_WORDS,
    SLOT_A_REGION_START,
    validate_app_firmware_image,
)

__all__ = [
    "AddressRange",
    "APP_FLASH_END_EXCLUSIVE",
    "APP_FLASH_START",
    "FirmwareBlock",
    "FirmwareImage",
    "Hex2000Error",
    "Hex2000NotFoundError",
    "MemoryParseError",
    "MemoryRegion",
    "Sci8BootTable",
    "Sci8ParseError",
    "SLOT_A_APP_END_EXCLUSIVE",
    "SLOT_A_APP_START",
    "SLOT_A_METADATA_END",
    "SLOT_A_METADATA_START",
    "SLOT_A_METADATA_WORDS",
    "SLOT_A_REGION_START",
    "build_device_info",
    "build_firmware_image",
    "locate_hex2000",
    "parse_memory_file",
    "parse_memory_text",
    "parse_sci8_file",
    "parse_sci8_text",
    "run_hex2000",
    "validate_app_firmware_image",
    "write_device_info",
]
