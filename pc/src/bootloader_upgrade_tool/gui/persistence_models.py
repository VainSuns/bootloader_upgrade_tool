"""Immutable documents for the three Runtime V2 persistence domains."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Generic, TypeVar

from .runtime_v2_models import EraseScope, RuntimeCpuId


SESSION_SCHEMA_VERSION = 1
GLOBAL_SETTINGS_SCHEMA_VERSION = 2
RUNTIME_CACHE_SCHEMA_VERSION = 1
MAX_RECENT_SESSIONS = 10


def _non_negative_int(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _freeze_json(value: object, name: str = "value") -> object:
    if type(value) is float and not math.isfinite(value):
        raise TypeError(f"{name} contains an unsupported JSON float")
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, name) for item in value)
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"{name} mapping keys must be strings")
            frozen[key] = _freeze_json(item, name)
        return MappingProxyType(frozen)
    raise TypeError(f"{name} contains an unsupported JSON value: {type(value).__name__}")


def _normalize_path(path: str | Path) -> str:
    if not isinstance(path, (str, Path)):
        raise TypeError("path must be a string or Path")
    return str(Path(path).expanduser().resolve(strict=False))


@dataclass(frozen=True, slots=True)
class TargetSessionSettings:
    cpu_id: RuntimeCpuId
    program_image_path: str = ""
    ram_image_path: str = ""
    erase_scope: EraseScope = EraseScope.REQUIRED_APP_SECTORS
    sector_mask: int = 0
    custom_sector_mask: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.cpu_id, RuntimeCpuId):
            raise TypeError("cpu_id must be RuntimeCpuId")
        if type(self.program_image_path) is not str or type(self.ram_image_path) is not str:
            raise TypeError("image paths must be strings")
        if not isinstance(self.erase_scope, EraseScope):
            raise TypeError("erase_scope must be EraseScope")
        _non_negative_int(self.sector_mask, "sector_mask")
        _non_negative_int(self.custom_sector_mask, "custom_sector_mask")


def _default_transport_configs() -> Mapping[str, object]:
    return MappingProxyType({"sci_rs232": MappingProxyType({})})


def _default_target_settings() -> Mapping[RuntimeCpuId, TargetSessionSettings]:
    return MappingProxyType({cpu: TargetSessionSettings(cpu) for cpu in RuntimeCpuId})


@dataclass(frozen=True, slots=True)
class SessionDocument:
    schema_version: int = SESSION_SCHEMA_VERSION
    selected_transport: str = "sci_rs232"
    transport_configs: Mapping[str, object] = field(default_factory=_default_transport_configs, repr=False)
    target_settings: Mapping[RuntimeCpuId, TargetSessionSettings] = field(
        default_factory=_default_target_settings, repr=False
    )

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SESSION_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {SESSION_SCHEMA_VERSION}")
        if type(self.selected_transport) is not str or not self.selected_transport:
            raise ValueError("selected_transport must be a non-empty string")
        if not isinstance(self.transport_configs, Mapping):
            raise TypeError("transport_configs must be a mapping")
        configs: dict[str, object] = {}
        for key, value in self.transport_configs.items():
            if type(key) is not str or not key:
                raise ValueError("transport IDs must be non-empty strings")
            if not isinstance(value, Mapping):
                raise TypeError(f"transport_configs.{key} must be an object")
            configs[key] = _freeze_json(value, f"transport_configs.{key}")
        if self.selected_transport not in configs:
            raise ValueError("selected_transport must exist in transport_configs")
        targets = dict(self.target_settings)
        if set(targets) != set(RuntimeCpuId):
            raise ValueError("target_settings must contain exactly CPU1 and CPU2")
        for cpu_id, settings in targets.items():
            if not isinstance(cpu_id, RuntimeCpuId) or not isinstance(settings, TargetSessionSettings):
                raise TypeError("invalid target_settings mapping")
            if settings.cpu_id is not cpu_id:
                raise ValueError("target settings CPU does not match its key")
        object.__setattr__(self, "transport_configs", MappingProxyType(configs))
        object.__setattr__(self, "target_settings", MappingProxyType(targets))


@dataclass(frozen=True, slots=True)
class GlobalCommandSettings:
    timeout_ms: int = 5000
    max_retries: int = 0
    retry_backoff_ms: int = 0

    def __post_init__(self) -> None:
        if type(self.timeout_ms) is not int or self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        _non_negative_int(self.max_retries, "max_retries")
        _non_negative_int(self.retry_backoff_ms, "retry_backoff_ms")


@dataclass(frozen=True, slots=True)
class GlobalSettingsDocument:
    schema_version: int = GLOBAL_SETTINGS_SCHEMA_VERSION
    hex2000_executable_path: str = ""
    command: GlobalCommandSettings = field(default_factory=GlobalCommandSettings)
    log_output_path: str = ""

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != GLOBAL_SETTINGS_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {GLOBAL_SETTINGS_SCHEMA_VERSION}")
        if type(self.hex2000_executable_path) is not str or type(self.log_output_path) is not str:
            raise TypeError("paths must be strings")
        if not isinstance(self.command, GlobalCommandSettings):
            raise TypeError("command must be GlobalCommandSettings")
        object.__setattr__(self, "hex2000_executable_path", self.hex2000_executable_path.strip())
        object.__setattr__(self, "log_output_path", self.log_output_path.strip())


@dataclass(frozen=True, slots=True)
class RecentSessionEntry:
    path: str
    last_saved_at_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalize_path(self.path))
        if not isinstance(self.last_saved_at_utc, datetime) or self.last_saved_at_utc.utcoffset() != timedelta(0):
            raise ValueError("last_saved_at_utc must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class RuntimeCacheDocument:
    schema_version: int = RUNTIME_CACHE_SCHEMA_VERSION
    recent_sessions: tuple[RecentSessionEntry, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != RUNTIME_CACHE_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {RUNTIME_CACHE_SCHEMA_VERSION}")
        latest: dict[str, RecentSessionEntry] = {}
        for entry in self.recent_sessions:
            if not isinstance(entry, RecentSessionEntry):
                raise TypeError("recent_sessions must contain RecentSessionEntry values")
            key = os.path.normcase(entry.path)
            if key not in latest or entry.last_saved_at_utc > latest[key].last_saved_at_utc:
                latest[key] = entry
        entries = tuple(
            sorted(latest.values(), key=lambda item: item.last_saved_at_utc, reverse=True)[
                :MAX_RECENT_SESSIONS
            ]
        )
        object.__setattr__(self, "recent_sessions", entries)

    def with_recent_session(self, path: str | Path, last_saved_at_utc: datetime) -> RuntimeCacheDocument:
        return RuntimeCacheDocument(
            recent_sessions=(*self.recent_sessions, RecentSessionEntry(path, last_saved_at_utc))
        )

    def without_recent_session(self, path: str | Path) -> RuntimeCacheDocument:
        key = os.path.normcase(_normalize_path(path))
        return RuntimeCacheDocument(
            recent_sessions=tuple(
                entry for entry in self.recent_sessions if os.path.normcase(entry.path) != key
            )
        )


DocumentT = TypeVar("DocumentT")


@dataclass(frozen=True, slots=True)
class DocumentLoadResult(Generic[DocumentT]):
    document: DocumentT
    source_schema_version: int | None
    migrated: bool = False
    notices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source_schema_version is not None and type(self.source_schema_version) is not int:
            raise TypeError("source_schema_version must be an integer or None")
        object.__setattr__(self, "notices", tuple(self.notices))


__all__ = [
    "DocumentLoadResult",
    "GLOBAL_SETTINGS_SCHEMA_VERSION",
    "GlobalCommandSettings",
    "GlobalSettingsDocument",
    "MAX_RECENT_SESSIONS",
    "RUNTIME_CACHE_SCHEMA_VERSION",
    "RecentSessionEntry",
    "RuntimeCacheDocument",
    "SESSION_SCHEMA_VERSION",
    "SessionDocument",
    "TargetSessionSettings",
]
