"""Target profiles and memory maps."""

from types import MappingProxyType

from .command_sets import CommandSet, UnsupportedOperationError, require_command
from .cpu1 import CPU1_COMMAND_SET, CPU1_MEMORY_MAP, CPU1_PROFILE
from .cpu2 import CPU2_COMMAND_SET, CPU2_MEMORY_MAP, CPU2_PROFILE
from .discovery import DISCOVERY_COMMAND_SET, DISCOVERY_MEMORY_MAP, DISCOVERY_PROFILE
from .memory_map import AddressRange, FlashLayout, MetadataLayout, RamLayout, TargetMemoryMap
from .profiles import TargetProfile


_TARGET_PROFILES = MappingProxyType(
    {
        "cpu1": CPU1_PROFILE,
        "cpu2": CPU2_PROFILE,
    }
)


def target_profile_for_key(target_key: str) -> TargetProfile | None:
    if not isinstance(target_key, str):
        raise TypeError("target_key must be a string")
    return _TARGET_PROFILES.get(target_key)

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
    "target_profile_for_key",
]
