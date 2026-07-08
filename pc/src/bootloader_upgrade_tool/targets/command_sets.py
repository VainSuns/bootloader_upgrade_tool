"""Target command set declarations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSet:
    ping: int | None = None
    get_device_info: int | None = None
    get_protocol_info: int | None = None
    get_last_error: int | None = None
    get_service_status: int | None = None
    service_attach: int | None = None
    ram_load_begin: int | None = None
    ram_load_data: int | None = None
    ram_load_end: int | None = None
    ram_check_crc: int | None = None
    run_ram: int | None = None
    erase: int | None = None
    program_begin: int | None = None
    program_data: int | None = None
    program_end: int | None = None
    verify_begin: int | None = None
    verify_data: int | None = None
    verify_end: int | None = None
    get_metadata_summary: int | None = None
    metadata_append_record: int | None = None
    run: int | None = None
    reset: int | None = None
    boot_cpu2_run_cpu1: int | None = None
    boot_cpu2_reset_cpu1: int | None = None


class UnsupportedOperationError(RuntimeError):
    pass


def require_command(command_set: CommandSet, field_name: str) -> int:
    value = getattr(command_set, field_name)
    if value is None:
        raise UnsupportedOperationError(f"unsupported command: {field_name}")
    return int(value)
