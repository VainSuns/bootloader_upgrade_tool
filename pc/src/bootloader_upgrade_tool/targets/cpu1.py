"""TMS320F28377D CPU1 target profile."""

from __future__ import annotations

from ..firmware.app_validation import (
    APP_FLASH_END_EXCLUSIVE,
    APP_FLASH_START,
    SLOT_A_METADATA_END,
    SLOT_A_METADATA_START,
)
from ..firmware.flash_layout import ALLOWED_ERASE_MASK, METADATA_SECTOR_MASK, SECTORS
from ..firmware.ram_validation import RAM_WRITE_RANGES
from ..protocol.constants import Command, CpuId
from .command_sets import CommandSet
from .memory_map import AddressRange, FlashLayout, FlashSector, MetadataLayout, RamLayout, TargetMemoryMap
from .profiles import TargetProfile


CPU1_COMMAND_SET = CommandSet(
    ping=Command.PING,
    get_device_info=Command.GET_DEVICE_INFO,
    get_protocol_info=Command.GET_PROTOCOL_INFO,
    get_last_error=Command.GET_LAST_ERROR,
    get_service_status=Command.GET_SERVICE_STATUS,
    service_attach=Command.SERVICE_ATTACH,
    ram_load_begin=Command.RAM_LOAD_BEGIN,
    ram_load_data=Command.RAM_LOAD_DATA,
    ram_load_end=Command.RAM_LOAD_END,
    ram_check_crc=Command.RAM_CHECK_CRC,
    run_ram=Command.RUN_RAM,
    erase=Command.ERASE,
    program_begin=Command.PROGRAM_BEGIN,
    program_data=Command.PROGRAM_DATA,
    program_end=Command.PROGRAM_END,
    verify_begin=Command.VERIFY_BEGIN,
    verify_data=Command.VERIFY_DATA,
    verify_end=Command.VERIFY_END,
    get_metadata_summary=Command.GET_METADATA_SUMMARY,
    metadata_append_record=Command.METADATA_APPEND_RECORD,
    run=Command.RUN,
    reset=Command.RESET,
)

_RAM_RANGES = tuple(AddressRange(item.start, item.end_exclusive) for item in RAM_WRITE_RANGES)

CPU1_MEMORY_MAP = TargetMemoryMap(
    flash=FlashLayout(
        app_ranges=(AddressRange(APP_FLASH_START, APP_FLASH_END_EXCLUSIVE),),
        allowed_erase_mask=ALLOWED_ERASE_MASK,
        forbidden_erase_mask=0x00000001,
        metadata_sector_mask=METADATA_SECTOR_MASK,
        sectors=tuple(
            FlashSector(chr(ord("A") + bit), start, end, bit)
            for start, end, bit in SECTORS
        ),
    ),
    ram=RamLayout(
        service_ranges=(AddressRange(0x010000, 0x01BFF8),),
        ram_app_ranges=_RAM_RANGES,
        reserved_ranges=(),
    ),
    metadata=MetadataLayout(
        range=AddressRange(SLOT_A_METADATA_START, SLOT_A_METADATA_END),
        sector_mask=METADATA_SECTOR_MASK,
        record_alignment_words=8,
    ),
)

CPU1_PROFILE = TargetProfile(
    name="TMS320F28377D CPU1",
    cpu_id=CpuId.CPU1,
    command_set=CPU1_COMMAND_SET,
    memory_map=CPU1_MEMORY_MAP,
)
