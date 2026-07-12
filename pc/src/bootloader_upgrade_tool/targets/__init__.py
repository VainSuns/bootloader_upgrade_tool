"""Target profiles and memory maps."""

from .command_sets import CommandSet, UnsupportedOperationError, require_command
from .cpu1 import CPU1_COMMAND_SET, CPU1_MEMORY_MAP, CPU1_PROFILE
from .cpu2 import CPU2_COMMAND_SET, CPU2_MEMORY_MAP, CPU2_PROFILE
from .discovery import DISCOVERY_COMMAND_SET, DISCOVERY_MEMORY_MAP, DISCOVERY_PROFILE
from .memory_map import AddressRange, FlashLayout, MetadataLayout, RamLayout, TargetMemoryMap
from .profiles import TargetProfile

__all__ = [
    "AddressRange",
    "CPU1_COMMAND_SET",
    "CPU1_MEMORY_MAP",
    "CPU1_PROFILE",
    "CPU2_COMMAND_SET",
    "CPU2_MEMORY_MAP",
    "CPU2_PROFILE",
    "DISCOVERY_COMMAND_SET",
    "DISCOVERY_MEMORY_MAP",
    "DISCOVERY_PROFILE",
    "CommandSet",
    "FlashLayout",
    "MetadataLayout",
    "RamLayout",
    "TargetMemoryMap",
    "TargetProfile",
    "UnsupportedOperationError",
    "require_command",
]
