"""Immutable Runtime V2 domain events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..images.models import ImageIdentity, RamImageIdentity
from .runtime_models import ConnectionInfo
from .runtime_v2_models import (
    ConnectionGeneration,
    EraseScope,
    FlashImageSummary,
    ImageParseStatus,
    RamImageSummary,
    RuntimeCpuId,
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
    "ConnectionOpened",
    "DomainEvent",
    "OperationFailed",
    "OperationStarted",
    "OperationSucceeded",
    "ProgramImageChanged",
    "RamImageChanged",
    "RuntimeOperationType",
    "SectorSelectionChanged",
    "SessionChanged",
]
