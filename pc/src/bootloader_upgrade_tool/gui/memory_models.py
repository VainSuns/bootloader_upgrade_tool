"""Immutable GUI requests and results for target Memory reads."""

from __future__ import annotations

from dataclasses import dataclass

from ..operations import OperationResult
from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)
from .runtime_v2_models import ConnectionGeneration, RuntimeCpuId


@dataclass(frozen=True, slots=True)
class MemoryRefreshRequest:
    connection_id: str
    target_key: str
    expected_connection_generation: ConnectionGeneration
    start_address: int
    word_count: int

    def __post_init__(self) -> None:
        if type(self.connection_id) is not str or not self.connection_id.strip():
            raise ValueError("connection_id must not be empty")
        RuntimeCpuId.from_target_key(self.target_key)
        if type(self.expected_connection_generation) is not ConnectionGeneration:
            raise TypeError("expected_connection_generation must be ConnectionGeneration")
        if type(self.start_address) is not int:
            raise TypeError("start_address must be an int")
        if not 0 <= self.start_address <= 0xFFFFFFFF:
            raise ValueError("start_address must fit uint32")
        if type(self.word_count) is not int:
            raise TypeError("word_count must be an int")
        if not 1 <= self.word_count <= 4096:
            raise ValueError("word_count must be between 1 and 4096")
        if self.start_address + self.word_count - 1 > 0xFFFFFFFF:
            raise ValueError("memory read exceeds the uint32 address space")

    def create_plan(self, task_id: str) -> TaskPlan:
        title = f"Read {self.target_key.upper()} Memory"
        return TaskPlan(
            task_id,
            title,
            (TaskStepPlan("read_memory", title, ProgressMode.DETERMINATE),),
            TaskConnectionRequirement.CONNECTED,
            True,
            CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS,
        )


@dataclass(frozen=True, slots=True)
class MemoryReadTaskSnapshot:
    connection_id: str
    target_key: str
    connection_generation: ConnectionGeneration
    start_address: int
    word_count: int
    operation_result: OperationResult

    def __post_init__(self) -> None:
        MemoryRefreshRequest(
            self.connection_id,
            self.target_key,
            self.connection_generation,
            self.start_address,
            self.word_count,
        )
        if not isinstance(self.operation_result, OperationResult):
            raise TypeError("operation_result must be OperationResult")


__all__ = ["MemoryReadTaskSnapshot", "MemoryRefreshRequest"]
