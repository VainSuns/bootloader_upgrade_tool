"""CPU2 profile skeleton; no real CPU2 workflow in this phase."""

from __future__ import annotations

from ..protocol.constants import CpuId
from .command_sets import CommandSet
from .memory_map import TargetMemoryMap
from .profiles import TargetProfile


CPU2_COMMAND_SET = CommandSet()
CPU2_MEMORY_MAP = TargetMemoryMap()
CPU2_PROFILE = TargetProfile(
    name="TMS320F28377D CPU2",
    cpu_id=CpuId.CPU2,
    command_set=CPU2_COMMAND_SET,
    memory_map=CPU2_MEMORY_MAP,
)
