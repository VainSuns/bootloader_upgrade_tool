"""Immutable Runtime V2 domain events."""

from __future__ import annotations

from dataclasses import dataclass

from .runtime_models import ConnectionInfo
from .runtime_v2_models import ConnectionGeneration, RuntimeCpuId


class DomainEvent:
    __slots__ = ()


def _cpu(value: object, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, RuntimeCpuId):
        raise TypeError("cpu_id must be RuntimeCpuId" + (" or None" if optional else ""))


def _generation(value: object, name: str = "connection_generation") -> None:
    if not isinstance(value, ConnectionGeneration):
        raise TypeError(f"{name} must be ConnectionGeneration")


def _identifier(value: object, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ActiveTargetChanged(DomainEvent):
    cpu_id: RuntimeCpuId | None

    def __post_init__(self) -> None:
        _cpu(self.cpu_id, optional=True)


@dataclass(frozen=True, slots=True)
class ProgramImageChanged(DomainEvent):
    cpu_id: RuntimeCpuId

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)


@dataclass(frozen=True, slots=True)
class RamImageChanged(DomainEvent):
    cpu_id: RuntimeCpuId

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)


@dataclass(frozen=True, slots=True)
class ConnectionOpened(DomainEvent):
    connection_info: ConnectionInfo

    def __post_init__(self) -> None:
        if not isinstance(self.connection_info, ConnectionInfo):
            raise TypeError("connection_info must be ConnectionInfo")
        _identifier(self.connection_info.connection_id, "connection_id")
        RuntimeCpuId.from_target_key(self.connection_info.target_key)


@dataclass(frozen=True, slots=True)
class ConnectionClosed(DomainEvent):
    connection_id: str
    connection_generation: ConnectionGeneration

    def __post_init__(self) -> None:
        _identifier(self.connection_id, "connection_id")
        _generation(self.connection_generation)


@dataclass(frozen=True, slots=True)
class ConnectionGenerationChanged(DomainEvent):
    previous_generation: ConnectionGeneration
    current_generation: ConnectionGeneration

    def __post_init__(self) -> None:
        _generation(self.previous_generation, "previous_generation")
        _generation(self.current_generation, "current_generation")
        if self.current_generation.value != self.previous_generation.value + 1:
            raise ValueError("current_generation must equal previous_generation + 1")


@dataclass(frozen=True, slots=True)
class OperationStarted(DomainEvent):
    operation_id: str
    cpu_id: RuntimeCpuId | None = None
    connection_generation: ConnectionGeneration | None = None

    def __post_init__(self) -> None:
        _identifier(self.operation_id, "operation_id")
        _cpu(self.cpu_id, optional=True)
        if self.connection_generation is not None:
            _generation(self.connection_generation)


@dataclass(frozen=True, slots=True)
class OperationSucceeded(DomainEvent):
    operation_id: str
    cpu_id: RuntimeCpuId | None = None
    connection_generation: ConnectionGeneration | None = None

    def __post_init__(self) -> None:
        _identifier(self.operation_id, "operation_id")
        _cpu(self.cpu_id, optional=True)
        if self.connection_generation is not None:
            _generation(self.connection_generation)


@dataclass(frozen=True, slots=True)
class OperationFailed(DomainEvent):
    operation_id: str
    cpu_id: RuntimeCpuId | None = None
    connection_generation: ConnectionGeneration | None = None
    error_code: str = ""

    def __post_init__(self) -> None:
        _identifier(self.operation_id, "operation_id")
        _cpu(self.cpu_id, optional=True)
        if self.connection_generation is not None:
            _generation(self.connection_generation)
        _identifier(self.error_code, "error_code")


@dataclass(frozen=True, slots=True)
class SessionChanged(DomainEvent):
    pass


__all__ = [
    "ActiveTargetChanged",
    "ConnectionClosed",
    "ConnectionGenerationChanged",
    "ConnectionOpened",
    "DomainEvent",
    "OperationFailed",
    "OperationStarted",
    "OperationSucceeded",
    "ProgramImageChanged",
    "RamImageChanged",
    "SessionChanged",
]
