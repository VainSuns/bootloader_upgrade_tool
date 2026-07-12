"""Minimal target profile used only to read DeviceInfo."""

from __future__ import annotations

from ..protocol.constants import Command, CpuId
from .command_sets import CommandSet
from .memory_map import TargetMemoryMap
from .profiles import TargetProfile


DISCOVERY_COMMAND_SET = CommandSet(get_device_info=Command.GET_DEVICE_INFO)
DISCOVERY_MEMORY_MAP = TargetMemoryMap()
DISCOVERY_PROFILE = TargetProfile(
    name="TMS320F28377D target discovery",
    cpu_id=CpuId.UNKNOWN,
    command_set=DISCOVERY_COMMAND_SET,
    memory_map=DISCOVERY_MEMORY_MAP,
)

__all__ = ["DISCOVERY_COMMAND_SET", "DISCOVERY_MEMORY_MAP", "DISCOVERY_PROFILE"]
