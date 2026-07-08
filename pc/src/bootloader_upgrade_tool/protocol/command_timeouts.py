"""Default command timeouts migrated from UpgradeWorkflow."""

from .constants import Command


DEFAULT_COMMAND_TIMEOUT_MS: dict[int, int] = {
    Command.ERASE: 60_000,
    Command.PROGRAM_BEGIN: 10_000,
    Command.PROGRAM_DATA: 10_000,
    Command.PROGRAM_END: 10_000,
    Command.VERIFY_BEGIN: 10_000,
    Command.VERIFY_DATA: 10_000,
    Command.VERIFY_END: 10_000,
    Command.METADATA_APPEND_RECORD: 10_000,
    Command.RUN: 5_000,
    Command.RESET: 5_000,
    Command.RAM_LOAD_BEGIN: 10_000,
    Command.RAM_LOAD_DATA: 10_000,
    Command.RAM_LOAD_END: 10_000,
    Command.RAM_CHECK_CRC: 10_000,
    Command.RUN_RAM: 5_000,
    Command.SERVICE_ATTACH: 10_000,
    Command.GET_SERVICE_STATUS: 5_000,
}
