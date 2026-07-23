"""Pure contracts for connection maintenance scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Protocol, TypeVar

from .runtime_v2_models import ConnectionGeneration


class MaintenanceExecutionStatus(str, Enum):
    EXECUTED = "executed"
    SKIPPED_BUSY = "skipped_busy"
    STALE_GENERATION = "stale_generation"
    EXECUTOR_CLOSED = "executor_closed"


class ConnectionHealthState(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class MaintenanceExecutionResult(Generic[T]):
    status: MaintenanceExecutionStatus
    value: T | None = None


class ConnectionMaintenanceScheduler(Protocol):
    def connection_opened(self, generation: ConnectionGeneration) -> None: ...

    def foreground_command_started(self, generation: ConnectionGeneration) -> None: ...

    def foreground_command_finished(self, generation: ConnectionGeneration) -> None: ...

    def protocol_activity(self, generation: ConnectionGeneration) -> None: ...

    def connection_closed(self, generation: ConnectionGeneration) -> None: ...


class NoOpConnectionMaintenanceScheduler:
    """Default scheduler until maintenance commands are implemented."""

    def connection_opened(self, generation: ConnectionGeneration) -> None:
        pass

    def foreground_command_started(self, generation: ConnectionGeneration) -> None:
        pass

    def foreground_command_finished(self, generation: ConnectionGeneration) -> None:
        pass

    def protocol_activity(self, generation: ConnectionGeneration) -> None:
        pass

    def connection_closed(self, generation: ConnectionGeneration) -> None:
        pass


__all__ = [
    "ConnectionHealthState",
    "ConnectionMaintenanceScheduler",
    "MaintenanceExecutionResult",
    "MaintenanceExecutionStatus",
    "NoOpConnectionMaintenanceScheduler",
]
