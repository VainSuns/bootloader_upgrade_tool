"""Target profile model."""

from __future__ import annotations

from dataclasses import dataclass

from .command_sets import CommandSet
from .memory_map import TargetMemoryMap


@dataclass(frozen=True)
class TargetProfile:
    name: str
    cpu_id: int
    command_set: CommandSet
    memory_map: TargetMemoryMap
