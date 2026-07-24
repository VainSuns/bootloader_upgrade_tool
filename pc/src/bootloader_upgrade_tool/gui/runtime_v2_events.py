"""Immutable Runtime V2 domain events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from ..images.models import ImageIdentity, RamImageIdentity
from .runtime_models import ConnectionInfo
from .runtime_v2_models import (
    ConnectionGeneration,
    ConnectionHealthState,
    DiagnosticGroup,
    EraseScope,
    FlashImageSummary,
    ImageParseStatus,
    RamImageSummary,
    RuntimeCpuId,
    RuntimeReadError,
    _validate_parse_state,
)


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


def _utc(value: object, name: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


def _identifier(value: object, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")


class RuntimeOperationType(str, Enum):
    ERASE = "erase"
    PROGRAM = "program"
    VERIFY = "verify"
    RAM_LOAD = "ram_load"
    RAM_CRC = "ram_crc"


def _operation_identity(
    operation_id: object,
    operation_type: object,
    cpu_id: object,
    connection_generation: object,
    image_identity: object,
) -> None:
    _identifier(operation_id, "operation_id")
    if type(operation_type) is not RuntimeOperationType:
        raise TypeError("operation_type must be RuntimeOperationType")
    if type(cpu_id) is not RuntimeCpuId:
        raise TypeError("cpu_id must be RuntimeCpuId")
    if type(connection_generation) is not ConnectionGeneration:
        raise TypeError("connection_generation must be ConnectionGeneration")
    if operation_type is RuntimeOperationType.ERASE:
        if image_identity is not None and type(image_identity) is not ImageIdentity:
            raise TypeError("ERASE image_identity must be ImageIdentity or None")
    elif operation_type in (RuntimeOperationType.PROGRAM, RuntimeOperationType.VERIFY):
        if type(image_identity) is not ImageIdentity:
            raise TypeError(f"{operation_type.name} image_identity must be ImageIdentity")
    elif type(image_identity) is not RamImageIdentity:
        raise TypeError(f"{operation_type.name} image_identity must be RamImageIdentity")


@dataclass(frozen=True, slots=True)
class MetadataReadSucceeded(DomainEvent):
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    value: object

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)
        _generation(self.connection_generation)
        if self.value is None:
            raise ValueError("Metadata success requires a value")


@dataclass(frozen=True, slots=True)
class MetadataReadFailed(DomainEvent):
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    error: RuntimeReadError

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)
        _generation(self.connection_generation)
        if not isinstance(self.error, RuntimeReadError):
            raise TypeError("error must be RuntimeReadError")


@dataclass(frozen=True, slots=True)
class MetadataWriteStarted(DomainEvent):
    operation_id: str
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    image_identity: ImageIdentity | None = None

    def __post_init__(self) -> None:
        _identifier(self.operation_id, "operation_id")
        _cpu(self.cpu_id)
        _generation(self.connection_generation)
        if self.image_identity is not None and type(self.image_identity) is not ImageIdentity:
            raise TypeError("image_identity must be ImageIdentity or None")


@dataclass(frozen=True, slots=True)
class DiagnosticReadSucceeded(DomainEvent):
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    group: DiagnosticGroup
    value: object

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)
        _generation(self.connection_generation)
        if not isinstance(self.group, DiagnosticGroup):
            raise TypeError("group must be DiagnosticGroup")
        if self.value is None:
            raise ValueError("Diagnostics success requires a value")


@dataclass(frozen=True, slots=True)
class DiagnosticReadFailed(DomainEvent):
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    group: DiagnosticGroup
    error: RuntimeReadError

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)
        _generation(self.connection_generation)
        if not isinstance(self.group, DiagnosticGroup):
            raise TypeError("group must be DiagnosticGroup")
        if not isinstance(self.error, RuntimeReadError):
            raise TypeError("error must be RuntimeReadError")


@dataclass(frozen=True, slots=True)
class MemoryReadSucceeded(DomainEvent):
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    base_address: int
    words: tuple[int, ...]
    read_at: datetime

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)
        _generation(self.connection_generation)
        if type(self.base_address) is not int or self.base_address < 0:
            raise ValueError("base_address must be a non-negative integer")
        words = tuple(self.words)
        if not words or any(type(word) is not int or not 0 <= word <= 0xFFFF for word in words):
            raise ValueError("words must be a non-empty sequence of 16-bit unsigned integers")
        object.__setattr__(self, "words", words)
        if not isinstance(self.read_at, datetime) or self.read_at.utcoffset() != timedelta(0):
            raise ValueError("read_at must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class MemoryReadFailed(DomainEvent):
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    error: RuntimeReadError

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)
        _generation(self.connection_generation)
        if not isinstance(self.error, RuntimeReadError):
            raise TypeError("error must be RuntimeReadError")


@dataclass(frozen=True, slots=True)
class MemoryCleared(DomainEvent):
    cpu_id: RuntimeCpuId

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)


@dataclass(frozen=True, slots=True)
class ActiveTargetChanged(DomainEvent):
    cpu_id: RuntimeCpuId | None

    def __post_init__(self) -> None:
        _cpu(self.cpu_id, optional=True)


@dataclass(frozen=True, slots=True)
class ProgramImageChanged(DomainEvent):
    cpu_id: RuntimeCpuId
    path: str
    parse_status: ImageParseStatus
    summary: FlashImageSummary | None = None
    parse_error: str | None = None

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)
        if type(self.path) is not str:
            raise TypeError("path must be a string")
        if self.summary is not None and not isinstance(self.summary, FlashImageSummary):
            raise TypeError("summary must be FlashImageSummary or None")
        _validate_parse_state(self.parse_status, self.summary, self.parse_error, "program image")
        if self.parse_status is not ImageParseStatus.EMPTY and not self.path:
            raise ValueError(f"{self.parse_status.name} program image state requires a non-empty path")


@dataclass(frozen=True, slots=True)
class RamImageChanged(DomainEvent):
    cpu_id: RuntimeCpuId
    path: str
    parse_status: ImageParseStatus
    summary: RamImageSummary | None = None
    parse_error: str | None = None

    def __post_init__(self) -> None:
        _cpu(self.cpu_id)
        if type(self.path) is not str:
            raise TypeError("path must be a string")
        if self.summary is not None and not isinstance(self.summary, RamImageSummary):
            raise TypeError("summary must be RamImageSummary or None")
        _validate_parse_state(self.parse_status, self.summary, self.parse_error, "RAM image")
        if self.parse_status is not ImageParseStatus.EMPTY and not self.path:
            raise ValueError(f"{self.parse_status.name} RAM image state requires a non-empty path")


@dataclass(frozen=True, slots=True)
class SectorSelectionChanged(DomainEvent):
    cpu_id: RuntimeCpuId
    erase_scope: EraseScope
    custom_sector_mask: int

    def __post_init__(self) -> None:
        if type(self.cpu_id) is not RuntimeCpuId:
            raise TypeError("cpu_id must be RuntimeCpuId")
        if type(self.erase_scope) is not EraseScope:
            raise TypeError("erase_scope must be EraseScope")
        if type(self.custom_sector_mask) is not int or self.custom_sector_mask < 0:
            raise ValueError("custom_sector_mask must be a non-negative integer")


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
class ProtocolActivityRecorded(DomainEvent):
    connection_generation: ConnectionGeneration
    occurred_at: datetime

    def __post_init__(self) -> None:
        _generation(self.connection_generation)
        _utc(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class ConnectionHealthChanged(DomainEvent):
    connection_generation: ConnectionGeneration
    state: ConnectionHealthState
    checked_at: datetime
    error: RuntimeReadError | None = None

    def __post_init__(self) -> None:
        _generation(self.connection_generation)
        if not isinstance(self.state, ConnectionHealthState):
            raise TypeError("state must be ConnectionHealthState")
        if self.state is ConnectionHealthState.UNKNOWN:
            raise ValueError("UNKNOWN is not a connection health check result")
        _utc(self.checked_at, "checked_at")
        if self.error is not None and not isinstance(self.error, RuntimeReadError):
            raise TypeError("error must be RuntimeReadError or None")
        if self.state is ConnectionHealthState.HEALTHY and self.error is not None:
            raise ValueError("HEALTHY cannot carry an error")
        if self.state is ConnectionHealthState.UNHEALTHY and self.error is None:
            raise ValueError("UNHEALTHY requires an error")


@dataclass(frozen=True, slots=True)
class OperationStarted(DomainEvent):
    operation_id: str
    operation_type: RuntimeOperationType
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    image_identity: ImageIdentity | RamImageIdentity | None = None

    def __post_init__(self) -> None:
        _operation_identity(
            self.operation_id,
            self.operation_type,
            self.cpu_id,
            self.connection_generation,
            self.image_identity,
        )


@dataclass(frozen=True, slots=True)
class OperationSucceeded(DomainEvent):
    operation_id: str
    operation_type: RuntimeOperationType
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    image_identity: ImageIdentity | RamImageIdentity | None = None

    def __post_init__(self) -> None:
        _operation_identity(
            self.operation_id,
            self.operation_type,
            self.cpu_id,
            self.connection_generation,
            self.image_identity,
        )


@dataclass(frozen=True, slots=True)
class OperationFailed(DomainEvent):
    operation_id: str
    operation_type: RuntimeOperationType
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    image_identity: ImageIdentity | RamImageIdentity | None
    error_code: str

    def __post_init__(self) -> None:
        _operation_identity(
            self.operation_id,
            self.operation_type,
            self.cpu_id,
            self.connection_generation,
            self.image_identity,
        )
        _identifier(self.error_code, "error_code")


@dataclass(frozen=True, slots=True)
class SessionChanged(DomainEvent):
    pass


__all__ = [
    "ActiveTargetChanged",
    "ConnectionClosed",
    "ConnectionGenerationChanged",
    "ConnectionHealthChanged",
    "ConnectionOpened",
    "DiagnosticReadFailed",
    "DiagnosticReadSucceeded",
    "DomainEvent",
    "OperationFailed",
    "OperationStarted",
    "OperationSucceeded",
    "ProgramImageChanged",
    "ProtocolActivityRecorded",
    "MetadataReadFailed",
    "MetadataReadSucceeded",
    "MetadataWriteStarted",
    "MemoryCleared",
    "MemoryReadFailed",
    "MemoryReadSucceeded",
    "RamImageChanged",
    "RuntimeOperationType",
    "SectorSelectionChanged",
    "SessionChanged",
]
