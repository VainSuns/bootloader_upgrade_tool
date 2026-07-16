"""Immutable Runtime V2 state models and the Backend-owned state kernel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock
from types import MappingProxyType

from ..images.models import ImageIdentity, RamImageIdentity
from .runtime_models import ConnectionInfo


class RuntimeCpuId(str, Enum):
    CPU1 = "cpu1"
    CPU2 = "cpu2"

    @classmethod
    def from_target_key(cls, target_key: str) -> RuntimeCpuId:
        if type(target_key) is not str:
            raise TypeError("target_key must be a string")
        try:
            return cls(target_key)
        except ValueError as exc:
            raise ValueError("target_key must be 'cpu1' or 'cpu2'") from exc


@dataclass(frozen=True, slots=True)
class ConnectionGeneration:
    value: int = 0

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 0:
            raise ValueError("connection generation must be a non-negative integer")

    def next(self) -> ConnectionGeneration:
        return ConnectionGeneration(self.value + 1)


class ImageParseStatus(str, Enum):
    EMPTY = "empty"
    PARSING = "parsing"
    READY = "ready"
    ERROR = "error"


class DataFreshness(str, Enum):
    EMPTY = "empty"
    FRESH = "fresh"
    STALE = "stale"


class EraseScope(str, Enum):
    REQUIRED_APP_SECTORS = "required_app_sectors"
    ENTIRE_APPLICATION_REGION = "entire_application_region"
    CUSTOM = "custom"


def _non_negative_int(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _runtime_cpu(value: object, name: str = "cpu_id") -> None:
    if not isinstance(value, RuntimeCpuId):
        raise TypeError(f"{name} must be RuntimeCpuId")


@dataclass(frozen=True, slots=True)
class FlashImageSummary:
    identity: ImageIdentity
    sector_mask: int

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ImageIdentity):
            raise TypeError("identity must be the canonical ImageIdentity")
        _non_negative_int(self.sector_mask, "sector_mask")


@dataclass(frozen=True, slots=True)
class RamImageSummary:
    identity: RamImageIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.identity, RamImageIdentity):
            raise TypeError("identity must be the canonical RamImageIdentity")


@dataclass(frozen=True, slots=True)
class VerifyEvidence:
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    image_identity: ImageIdentity
    operation_id: str

    def __post_init__(self) -> None:
        _runtime_cpu(self.cpu_id)
        if not isinstance(self.connection_generation, ConnectionGeneration):
            raise TypeError("connection_generation must be ConnectionGeneration")
        if not isinstance(self.image_identity, ImageIdentity):
            raise TypeError("image_identity must be the canonical ImageIdentity")
        if type(self.operation_id) is not str or not self.operation_id:
            raise ValueError("operation_id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class RamCrcEvidence:
    cpu_id: RuntimeCpuId
    connection_generation: ConnectionGeneration
    ram_image_identity: RamImageIdentity
    entry_point: int
    image_crc32: int
    operation_id: str

    def __post_init__(self) -> None:
        _runtime_cpu(self.cpu_id)
        if not isinstance(self.connection_generation, ConnectionGeneration):
            raise TypeError("connection_generation must be ConnectionGeneration")
        if not isinstance(self.ram_image_identity, RamImageIdentity):
            raise TypeError("ram_image_identity must be the canonical RamImageIdentity")
        _non_negative_int(self.entry_point, "entry_point")
        _non_negative_int(self.image_crc32, "image_crc32")
        if type(self.operation_id) is not str or not self.operation_id:
            raise ValueError("operation_id must be a non-empty string")


def _validate_parse_state(
    status: ImageParseStatus,
    summary: object | None,
    error: str | None,
    name: str,
) -> None:
    if not isinstance(status, ImageParseStatus):
        raise TypeError(f"{name}_parse_status must be ImageParseStatus")
    if error is not None and type(error) is not str:
        raise TypeError(f"{name}_parse_error must be a string or None")
    if status is ImageParseStatus.READY:
        if summary is None or error is not None:
            raise ValueError(f"READY {name} state requires a summary and no error")
    elif status is ImageParseStatus.ERROR:
        if summary is not None or not error:
            raise ValueError(f"ERROR {name} state requires a non-empty error and no summary")
    elif summary is not None or error is not None:
        raise ValueError(f"{status.name} {name} state cannot carry a summary or error")


@dataclass(frozen=True, slots=True)
class TargetResourceState:
    cpu_id: RuntimeCpuId
    program_image_path: str = ""
    program_image_summary: FlashImageSummary | None = None
    program_image_parse_status: ImageParseStatus = ImageParseStatus.EMPTY
    program_image_parse_error: str | None = None
    ram_image_path: str = ""
    ram_image_summary: RamImageSummary | None = None
    ram_image_parse_status: ImageParseStatus = ImageParseStatus.EMPTY
    ram_image_parse_error: str | None = None
    erase_scope: EraseScope = EraseScope.REQUIRED_APP_SECTORS
    custom_sector_mask: int = 0
    verify_evidence: VerifyEvidence | None = None
    ram_crc_evidence: RamCrcEvidence | None = None

    def __post_init__(self) -> None:
        _runtime_cpu(self.cpu_id)
        if type(self.program_image_path) is not str or type(self.ram_image_path) is not str:
            raise TypeError("image paths must be strings")
        if self.program_image_summary is not None and not isinstance(self.program_image_summary, FlashImageSummary):
            raise TypeError("program_image_summary must be FlashImageSummary or None")
        if self.ram_image_summary is not None and not isinstance(self.ram_image_summary, RamImageSummary):
            raise TypeError("ram_image_summary must be RamImageSummary or None")
        _validate_parse_state(
            self.program_image_parse_status,
            self.program_image_summary,
            self.program_image_parse_error,
            "program image",
        )
        _validate_parse_state(
            self.ram_image_parse_status,
            self.ram_image_summary,
            self.ram_image_parse_error,
            "RAM image",
        )
        if not isinstance(self.erase_scope, EraseScope):
            raise TypeError("erase_scope must be EraseScope")
        _non_negative_int(self.custom_sector_mask, "custom_sector_mask")
        if self.verify_evidence is not None:
            if not isinstance(self.verify_evidence, VerifyEvidence):
                raise TypeError("verify_evidence must be VerifyEvidence or None")
            if self.verify_evidence.cpu_id is not self.cpu_id:
                raise ValueError("verify evidence CPU does not match resource CPU")
        if self.ram_crc_evidence is not None:
            if not isinstance(self.ram_crc_evidence, RamCrcEvidence):
                raise TypeError("ram_crc_evidence must be RamCrcEvidence or None")
            if self.ram_crc_evidence.cpu_id is not self.cpu_id:
                raise ValueError("RAM CRC evidence CPU does not match resource CPU")


@dataclass(frozen=True, slots=True)
class ConnectionRuntimeState:
    generation: ConnectionGeneration
    connection_id: str
    cpu_id: RuntimeCpuId
    transport_label: str
    endpoint_label: str
    connected_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.generation, ConnectionGeneration):
            raise TypeError("generation must be ConnectionGeneration")
        _runtime_cpu(self.cpu_id)
        for name in ("connection_id", "transport_label", "endpoint_label"):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.connected_at, datetime) or self.connected_at.utcoffset() != timedelta(0):
            raise ValueError("connected_at must be timezone-aware UTC")

    @classmethod
    def from_connection_info(
        cls,
        connection_info: ConnectionInfo,
        generation: ConnectionGeneration,
    ) -> ConnectionRuntimeState:
        if not isinstance(connection_info, ConnectionInfo):
            raise TypeError("connection_info must be ConnectionInfo")
        return cls(
            generation=generation,
            connection_id=connection_info.connection_id,
            cpu_id=RuntimeCpuId.from_target_key(connection_info.target_key),
            transport_label=connection_info.transport_label,
            endpoint_label=connection_info.endpoint_label,
            connected_at=connection_info.connected_at,
        )


@dataclass(frozen=True, slots=True)
class MemoryRuntimeState:
    cpu_id: RuntimeCpuId
    freshness: DataFreshness = DataFreshness.EMPTY
    base_address: int | None = None
    words: tuple[int, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        _runtime_cpu(self.cpu_id)
        if not isinstance(self.freshness, DataFreshness):
            raise TypeError("freshness must be DataFreshness")
        if self.base_address is not None:
            _non_negative_int(self.base_address, "base_address")
        if self.error is not None and type(self.error) is not str:
            raise TypeError("error must be a string or None")
        words = tuple(self.words)
        if any(type(word) is not int or not 0 <= word <= 0xFFFF for word in words):
            raise ValueError("words must contain only 16-bit unsigned integers")
        object.__setattr__(self, "words", words)
        if self.freshness is DataFreshness.EMPTY:
            if self.base_address is not None or words or self.error is not None:
                raise ValueError("EMPTY memory state cannot carry data or error")
        elif self.freshness is DataFreshness.FRESH and self.base_address is None:
            raise ValueError("FRESH memory state requires a base address")


_RUNTIME_CPUS = frozenset(RuntimeCpuId)


@dataclass(frozen=True, slots=True)
class RuntimeV2Snapshot:
    connection_generation: ConnectionGeneration
    connection: ConnectionRuntimeState | None
    target_resources: Mapping[RuntimeCpuId, TargetResourceState] = field(repr=False)
    memory_states: Mapping[RuntimeCpuId, MemoryRuntimeState] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.connection_generation, ConnectionGeneration):
            raise TypeError("connection_generation must be ConnectionGeneration")
        if self.connection is not None:
            if not isinstance(self.connection, ConnectionRuntimeState):
                raise TypeError("connection must be ConnectionRuntimeState or None")
            if self.connection.generation != self.connection_generation:
                raise ValueError("active connection generation must match snapshot generation")
        resources = dict(self.target_resources)
        memories = dict(self.memory_states)
        if set(resources) != _RUNTIME_CPUS or set(memories) != _RUNTIME_CPUS:
            raise ValueError("Runtime V2 mappings must contain exactly CPU1 and CPU2")
        for cpu_id, state in resources.items():
            if not isinstance(cpu_id, RuntimeCpuId) or not isinstance(state, TargetResourceState):
                raise TypeError("invalid target resource mapping")
            if state.cpu_id is not cpu_id:
                raise ValueError("target resource CPU does not match its key")
        for cpu_id, state in memories.items():
            if not isinstance(cpu_id, RuntimeCpuId) or not isinstance(state, MemoryRuntimeState):
                raise TypeError("invalid memory state mapping")
            if state.cpu_id is not cpu_id:
                raise ValueError("memory state CPU does not match its key")
        object.__setattr__(self, "target_resources", MappingProxyType(resources))
        object.__setattr__(self, "memory_states", MappingProxyType(memories))


class RuntimeStateDraft:
    """One-transition mutable draft; never retained or returned."""

    __slots__ = (
        "_connection_generation",
        "_connection",
        "_target_resources",
        "_memory_states",
        "_derived_events",
        "_original_connection_generation",
    )

    def __init__(
        self,
        connection_generation: ConnectionGeneration,
        connection: ConnectionRuntimeState | None,
        target_resources: Mapping[RuntimeCpuId, TargetResourceState],
        memory_states: Mapping[RuntimeCpuId, MemoryRuntimeState],
    ) -> None:
        self._connection_generation = connection_generation
        self._original_connection_generation = connection_generation
        self._connection = connection
        self._target_resources = dict(target_resources)
        self._memory_states = dict(memory_states)
        self._derived_events: list[object] = []

    @property
    def connection_generation(self) -> ConnectionGeneration:
        return self._connection_generation

    @property
    def original_connection_generation(self) -> ConnectionGeneration:
        return self._original_connection_generation

    @property
    def connection(self) -> ConnectionRuntimeState | None:
        return self._connection

    def replace_connection_generation(self, value: ConnectionGeneration) -> None:
        if not isinstance(value, ConnectionGeneration):
            raise TypeError("connection generation must be ConnectionGeneration")
        self._connection_generation = value

    def replace_connection(self, value: ConnectionRuntimeState | None) -> None:
        if value is not None and not isinstance(value, ConnectionRuntimeState):
            raise TypeError("connection must be ConnectionRuntimeState or None")
        self._connection = value

    def replace_target_resource(self, cpu_id: RuntimeCpuId, state: TargetResourceState) -> None:
        _runtime_cpu(cpu_id, "target resource key")
        if not isinstance(state, TargetResourceState):
            raise TypeError("state must be TargetResourceState")
        if state.cpu_id is not cpu_id:
            raise ValueError("target resource CPU does not match its key")
        self._target_resources[cpu_id] = state

    def replace_memory_state(self, cpu_id: RuntimeCpuId, state: MemoryRuntimeState) -> None:
        _runtime_cpu(cpu_id, "memory state key")
        if not isinstance(state, MemoryRuntimeState):
            raise TypeError("state must be MemoryRuntimeState")
        if state.cpu_id is not cpu_id:
            raise ValueError("memory state CPU does not match its key")
        self._memory_states[cpu_id] = state

    def record(self, event: object) -> None:
        from .runtime_v2_events import DomainEvent

        if not isinstance(event, DomainEvent):
            raise TypeError("derived event must be DomainEvent")
        self._derived_events.append(event)

    def candidate(self) -> RuntimeV2Snapshot:
        return RuntimeV2Snapshot(
            self._connection_generation,
            self._connection,
            self._target_resources,
            self._memory_states,
        )

    @property
    def derived_events(self) -> tuple[object, ...]:
        return tuple(self._derived_events)


class RuntimeStateStore:
    """Mutable Runtime V2 kernel; callers only receive immutable snapshots."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._connection_generation = ConnectionGeneration()
        self._connection: ConnectionRuntimeState | None = None
        self._target_resources = {cpu_id: TargetResourceState(cpu_id) for cpu_id in RuntimeCpuId}
        self._memory_states = {cpu_id: MemoryRuntimeState(cpu_id) for cpu_id in RuntimeCpuId}

    def snapshot(self) -> RuntimeV2Snapshot:
        with self._lock:
            return RuntimeV2Snapshot(
                self._connection_generation,
                self._connection,
                self._target_resources,
                self._memory_states,
            )

    def replace_target_resource(self, cpu_id: RuntimeCpuId, state: TargetResourceState) -> None:
        _runtime_cpu(cpu_id, "target resource key")
        if not isinstance(state, TargetResourceState):
            raise TypeError("state must be TargetResourceState")
        if state.cpu_id is not cpu_id:
            raise ValueError("target resource CPU does not match its key")
        with self._lock:
            self._target_resources[cpu_id] = state

    def replace_memory_state(self, cpu_id: RuntimeCpuId, state: MemoryRuntimeState) -> None:
        _runtime_cpu(cpu_id, "memory state key")
        if not isinstance(state, MemoryRuntimeState):
            raise TypeError("state must be MemoryRuntimeState")
        if state.cpu_id is not cpu_id:
            raise ValueError("memory state CPU does not match its key")
        with self._lock:
            self._memory_states[cpu_id] = state

    def commit_connection(self, connection_info: ConnectionInfo) -> ConnectionRuntimeState:
        with self._lock:
            generation = self._connection_generation.next()
            connection = ConnectionRuntimeState.from_connection_info(connection_info, generation)
            self._connection_generation = generation
            self._connection = connection
            return connection

    def clear_connection(self) -> None:
        with self._lock:
            self._connection = None

    def transition(self, event: object, policies: Sequence[object]):
        from .runtime_v2_transition import DomainTransitionError

        with self._lock:
            draft = RuntimeStateDraft(
                self._connection_generation,
                self._connection,
                self._target_resources,
                self._memory_states,
            )
            for policy in policies:
                try:
                    policy.apply(event, draft)
                except Exception as exc:
                    raise DomainTransitionError(type(policy).__name__, exc) from exc
            try:
                candidate = draft.candidate()
            except Exception as exc:
                raise DomainTransitionError("RuntimeV2Snapshot", exc) from exc
            self._connection_generation = candidate.connection_generation
            self._connection = candidate.connection
            self._target_resources = dict(candidate.target_resources)
            self._memory_states = dict(candidate.memory_states)
            return candidate, draft.derived_events


__all__ = [
    "ConnectionGeneration",
    "ConnectionRuntimeState",
    "DataFreshness",
    "EraseScope",
    "FlashImageSummary",
    "ImageParseStatus",
    "MemoryRuntimeState",
    "RamCrcEvidence",
    "RamImageSummary",
    "RuntimeCpuId",
    "RuntimeStateStore",
    "RuntimeStateDraft",
    "RuntimeV2Snapshot",
    "TargetResourceState",
    "VerifyEvidence",
]
