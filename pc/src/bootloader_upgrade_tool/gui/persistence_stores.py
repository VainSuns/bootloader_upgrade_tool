"""Strict JSON stores for Runtime V2 persistence documents."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .persistence_models import (
    GLOBAL_SETTINGS_SCHEMA_VERSION,
    RUNTIME_CACHE_SCHEMA_VERSION,
    SESSION_SCHEMA_VERSION,
    DocumentLoadResult,
    GlobalCommandSettings,
    GlobalSettingsDocument,
    RecentSessionEntry,
    RuntimeCacheDocument,
    SessionDocument,
    TargetSessionSettings,
)
from .runtime_v2_models import EraseScope, RuntimeCpuId


class PersistenceError(Exception):
    """Base class for persistence failures."""


class PersistenceFileNotFoundError(PersistenceError):
    pass


class PersistenceFormatError(PersistenceError):
    pass


class UnsupportedSchemaVersionError(PersistenceFormatError):
    pass


class PersistenceWriteError(PersistenceError):
    pass


@dataclass(frozen=True, slots=True)
class PersistencePaths:
    global_settings_path: Path
    runtime_cache_path: Path


def default_persistence_paths(app_name: str = "bootloader_upgrade_tool") -> PersistencePaths:
    if type(app_name) is not str or not app_name.strip():
        raise ValueError("app_name must be a non-empty string")
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    root = base.expanduser() / app_name
    return PersistencePaths(root / "global_settings.json", root / "runtime_cache.json")


def _plain_json(value: object) -> object:
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _session_data(document: SessionDocument) -> dict[str, object]:
    if not isinstance(document, SessionDocument):
        raise TypeError("document must be SessionDocument")
    return {
        "schema_version": document.schema_version,
        "selected_transport": document.selected_transport,
        "target_settings": {
            cpu.value: {
                "cpu_id": settings.cpu_id.value,
                "custom_sector_mask": settings.custom_sector_mask,
                "erase_scope": settings.erase_scope.value,
                "program_image_path": settings.program_image_path,
                "ram_image_path": settings.ram_image_path,
                "sector_mask": settings.sector_mask,
            }
            for cpu, settings in document.target_settings.items()
        },
        "transport_configs": _plain_json(document.transport_configs),
    }


def _global_data(document: GlobalSettingsDocument) -> dict[str, object]:
    if not isinstance(document, GlobalSettingsDocument):
        raise TypeError("document must be GlobalSettingsDocument")
    return {
        "command": {
            "max_retries": document.command.max_retries,
            "retry_backoff_ms": document.command.retry_backoff_ms,
            "timeout_ms": document.command.timeout_ms,
        },
        "hex2000_executable_path": document.hex2000_executable_path,
        "log_output_path": document.log_output_path,
        "schema_version": document.schema_version,
    }


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _cache_data(document: RuntimeCacheDocument) -> dict[str, object]:
    if not isinstance(document, RuntimeCacheDocument):
        raise TypeError("document must be RuntimeCacheDocument")
    return {
        "recent_sessions": [
            {"last_saved_at_utc": _utc_text(entry.last_saved_at_utc), "path": entry.path}
            for entry in document.recent_sessions
        ],
        "schema_version": document.schema_version,
    }


def _serialize(data: dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _atomic_write(path: Path, document: object, encode: Callable[[Any], dict[str, object]]) -> None:
    try:
        payload = _serialize(encode(document))
    except Exception as exc:
        raise PersistenceWriteError(f"{path}: cannot serialize document: {exc}") from exc
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except Exception as exc:
        raise PersistenceWriteError(f"{path}: atomic write failed: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _load_object(path: Path, *, optional: bool) -> dict[str, object] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if optional:
            return None
        raise PersistenceFileNotFoundError(f"{path}: file not found") from exc
    except UnicodeError as exc:
        raise PersistenceFormatError(f"{path}: file is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise PersistenceError(f"{path}: cannot read file: {exc}") from exc
    try:
        value = json.loads(
            text,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"invalid constant {token}")),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise PersistenceFormatError(f"{path}: malformed JSON: {exc}") from exc
    if type(value) is not dict:
        raise PersistenceFormatError(f"{path}: JSON root must be an object")
    return value


def _exact_fields(path: Path, value: Mapping[str, object], expected: set[str], section: str) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise PersistenceFormatError(f"{path}: {section} missing field {sorted(missing)[0]}")
    if unknown:
        raise PersistenceFormatError(f"{path}: {section} has unknown field {sorted(unknown)[0]}")


def _object(path: Path, value: object, section: str) -> dict[str, object]:
    if type(value) is not dict:
        raise PersistenceFormatError(f"{path}: {section} must be an object")
    return value


def _string(path: Path, value: object, field: str) -> str:
    if type(value) is not str:
        raise PersistenceFormatError(f"{path}: {field} must be a string")
    return value


def _integer(path: Path, value: object, field: str, *, positive: bool = False) -> int:
    if type(value) is not int or (value <= 0 if positive else value < 0):
        requirement = "positive" if positive else "non-negative"
        raise PersistenceFormatError(f"{path}: {field} must be a {requirement} integer")
    return value


def _schema(path: Path, data: dict[str, object], supported: int, *, legacy: int | None = None) -> int:
    value = data.get("schema_version")
    if type(value) is not int:
        raise PersistenceFormatError(f"{path}: schema_version must be an integer")
    if value != supported and value != legacy:
        raise UnsupportedSchemaVersionError(
            f"{path}: unsupported schema_version {value}; supported version is {supported}"
        )
    return value


def _parse_session(path: Path, data: dict[str, object]) -> SessionDocument:
    _schema(path, data, SESSION_SCHEMA_VERSION)
    _exact_fields(path, data, {"schema_version", "selected_transport", "transport_configs", "target_settings"}, "Session")
    selected = _string(path, data["selected_transport"], "selected_transport")
    configs = _object(path, data["transport_configs"], "transport_configs")
    targets = _object(path, data["target_settings"], "target_settings")
    if set(targets) != {cpu.value for cpu in RuntimeCpuId}:
        raise PersistenceFormatError(f"{path}: target_settings must contain exactly cpu1 and cpu2")
    parsed_targets: dict[RuntimeCpuId, TargetSessionSettings] = {}
    for cpu in RuntimeCpuId:
        section = _object(path, targets[cpu.value], f"target_settings.{cpu.value}")
        fields = {"cpu_id", "program_image_path", "ram_image_path", "erase_scope", "sector_mask", "custom_sector_mask"}
        _exact_fields(path, section, fields, f"target_settings.{cpu.value}")
        cpu_text = _string(path, section["cpu_id"], f"target_settings.{cpu.value}.cpu_id")
        scope_text = _string(path, section["erase_scope"], f"target_settings.{cpu.value}.erase_scope")
        try:
            cpu_id = RuntimeCpuId(cpu_text)
            scope = EraseScope(scope_text)
        except ValueError as exc:
            raise PersistenceFormatError(f"{path}: invalid CPU or erase scope in target_settings.{cpu.value}") from exc
        try:
            parsed_targets[cpu] = TargetSessionSettings(
                cpu_id=cpu_id,
                program_image_path=_string(path, section["program_image_path"], f"target_settings.{cpu.value}.program_image_path"),
                ram_image_path=_string(path, section["ram_image_path"], f"target_settings.{cpu.value}.ram_image_path"),
                erase_scope=scope,
                sector_mask=_integer(path, section["sector_mask"], f"target_settings.{cpu.value}.sector_mask"),
                custom_sector_mask=_integer(path, section["custom_sector_mask"], f"target_settings.{cpu.value}.custom_sector_mask"),
            )
        except (TypeError, ValueError) as exc:
            raise PersistenceFormatError(f"{path}: invalid target_settings.{cpu.value}: {exc}") from exc
    try:
        return SessionDocument(
            selected_transport=selected, transport_configs=configs, target_settings=parsed_targets
        )
    except (TypeError, ValueError) as exc:
        raise PersistenceFormatError(f"{path}: invalid Session document: {exc}") from exc


def _parse_global_v2(path: Path, data: dict[str, object]) -> GlobalSettingsDocument:
    _exact_fields(path, data, {"schema_version", "hex2000_executable_path", "command", "log_output_path"}, "Global Settings")
    command = _object(path, data["command"], "command")
    _exact_fields(path, command, {"timeout_ms", "max_retries", "retry_backoff_ms"}, "command")
    try:
        return GlobalSettingsDocument(
            hex2000_executable_path=_string(path, data["hex2000_executable_path"], "hex2000_executable_path"),
            command=GlobalCommandSettings(
                timeout_ms=_integer(path, command["timeout_ms"], "command.timeout_ms", positive=True),
                max_retries=_integer(path, command["max_retries"], "command.max_retries"),
                retry_backoff_ms=_integer(path, command["retry_backoff_ms"], "command.retry_backoff_ms"),
            ),
            log_output_path=_string(path, data["log_output_path"], "log_output_path"),
        )
    except (TypeError, ValueError) as exc:
        raise PersistenceFormatError(f"{path}: invalid Global Settings document: {exc}") from exc


_LEGACY_NOTICES = {
    "flash_lib": "flash_lib belongs to application resources and is not persisted in Global Settings v2",
    "temporary_files": "temporary_files is not persisted in Global Settings v2",
    "connection_timeouts": "connection_timeouts is transport-specific and is not persisted in Global Settings v2",
}


def _parse_global_v1(path: Path, data: dict[str, object]) -> DocumentLoadResult[GlobalSettingsDocument]:
    allowed = {"schema_version", "hex2000", *_LEGACY_NOTICES}
    unknown = set(data) - allowed
    if unknown:
        raise PersistenceFormatError(f"{path}: legacy Global Settings has unknown field {sorted(unknown)[0]}")
    if "hex2000" not in data:
        raise PersistenceFormatError(f"{path}: legacy Global Settings missing field hex2000")
    hex2000 = _object(path, data["hex2000"], "hex2000")
    _exact_fields(path, hex2000, {"executable_path"}, "hex2000")
    executable = _string(path, hex2000["executable_path"], "hex2000.executable_path")
    legacy_shapes = {
        "flash_lib": {
            "service_image_path": str,
            "service_map_path": str,
            "descriptor_symbol": str,
        },
        "temporary_files": {"sci8_temp_dir": str, "keep_generated_sci8_txt": bool},
        "connection_timeouts": {
            "tx_timeout_ms": int,
            "rx_timeout_ms": int,
            "autobaud_timeout_ms": int,
        },
    }
    for section_name, shape in legacy_shapes.items():
        if section_name not in data:
            continue
        section = _object(path, data[section_name], section_name)
        unknown_fields = set(section) - set(shape)
        if unknown_fields:
            raise PersistenceFormatError(
                f"{path}: {section_name} has unknown field {sorted(unknown_fields)[0]}"
            )
        for field_name, expected_type in shape.items():
            if field_name in section and type(section[field_name]) is not expected_type:
                raise PersistenceFormatError(
                    f"{path}: {section_name}.{field_name} has an invalid type"
                )
    notices = tuple(message for name, message in _LEGACY_NOTICES.items() if name in data)
    return DocumentLoadResult(
        GlobalSettingsDocument(hex2000_executable_path=executable), 1, True, notices
    )


def _parse_cache(path: Path, data: dict[str, object]) -> RuntimeCacheDocument:
    _schema(path, data, RUNTIME_CACHE_SCHEMA_VERSION)
    _exact_fields(path, data, {"schema_version", "recent_sessions"}, "Runtime Cache")
    values = data["recent_sessions"]
    if type(values) is not list:
        raise PersistenceFormatError(f"{path}: recent_sessions must be an array")
    entries: list[RecentSessionEntry] = []
    for index, value in enumerate(values):
        section = _object(path, value, f"recent_sessions[{index}]")
        _exact_fields(path, section, {"path", "last_saved_at_utc"}, f"recent_sessions[{index}]")
        path_text = _string(path, section["path"], f"recent_sessions[{index}].path")
        timestamp = _string(path, section["last_saved_at_utc"], f"recent_sessions[{index}].last_saved_at_utc")
        try:
            parsed = datetime.fromisoformat(timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp)
            entries.append(RecentSessionEntry(path_text, parsed))
        except (TypeError, ValueError) as exc:
            raise PersistenceFormatError(f"{path}: invalid recent_sessions[{index}]: {exc}") from exc
    return RuntimeCacheDocument(recent_sessions=tuple(entries))


class SessionStore:
    def load(self, path: str | Path) -> DocumentLoadResult[SessionDocument]:
        source = Path(path)
        data = _load_object(source, optional=False)
        assert data is not None
        return DocumentLoadResult(_parse_session(source, data), SESSION_SCHEMA_VERSION)

    def save(self, path: str | Path, document: SessionDocument) -> None:
        _atomic_write(Path(path), document, _session_data)


class GlobalSettingsStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_persistence_paths().global_settings_path

    def load(self) -> DocumentLoadResult[GlobalSettingsDocument]:
        data = _load_object(self.path, optional=True)
        if data is None:
            return DocumentLoadResult(GlobalSettingsDocument(), None)
        version = _schema(self.path, data, GLOBAL_SETTINGS_SCHEMA_VERSION, legacy=1)
        if version == 1:
            return _parse_global_v1(self.path, data)
        return DocumentLoadResult(_parse_global_v2(self.path, data), version)

    def save(self, document: GlobalSettingsDocument) -> None:
        _atomic_write(self.path, document, _global_data)


class RuntimeCacheStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_persistence_paths().runtime_cache_path

    def load(self) -> DocumentLoadResult[RuntimeCacheDocument]:
        data = _load_object(self.path, optional=True)
        if data is None:
            return DocumentLoadResult(RuntimeCacheDocument(), None)
        return DocumentLoadResult(_parse_cache(self.path, data), RUNTIME_CACHE_SCHEMA_VERSION)

    def save(self, document: RuntimeCacheDocument) -> None:
        _atomic_write(self.path, document, _cache_data)


__all__ = [
    "GlobalSettingsStore",
    "PersistenceError",
    "PersistenceFileNotFoundError",
    "PersistenceFormatError",
    "PersistencePaths",
    "PersistenceWriteError",
    "RuntimeCacheStore",
    "SessionStore",
    "UnsupportedSchemaVersionError",
    "default_persistence_paths",
]
