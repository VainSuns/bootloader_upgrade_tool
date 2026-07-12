"""GUI global settings loader."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
USER_CONFIG_PATH = REPO_ROOT / "pc" / "config" / "gui_global_settings.json"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "pc" / "config" / "gui_global_settings.example.json"
DEFAULT_DESCRIPTOR_SYMBOL = "g_boot_flash_service_descriptor"


@dataclass(frozen=True)
class Hex2000Settings:
    executable_path: str = ""


@dataclass(frozen=True)
class FlashLibSettings:
    service_image_path: str = ""
    service_map_path: str = ""
    descriptor_symbol: str = DEFAULT_DESCRIPTOR_SYMBOL


@dataclass(frozen=True)
class TemporaryFileSettings:
    sci8_temp_dir: str = ""
    keep_generated_sci8_txt: bool = False

    @property
    def resolved_sci8_temp_dir(self) -> Path:
        if self.sci8_temp_dir.strip():
            return Path(self.sci8_temp_dir).expanduser()
        return Path(tempfile.gettempdir())


@dataclass(frozen=True)
class ConnectionTimeoutSettings:
    tx_timeout_ms: Any = 1000
    rx_timeout_ms: Any = 1000
    autobaud_timeout_ms: Any = 5000


@dataclass(frozen=True)
class SettingsIssue:
    field: str
    message: str


@dataclass(frozen=True)
class GuiGlobalSettings:
    hex2000: Hex2000Settings = field(default_factory=Hex2000Settings)
    flash_lib: FlashLibSettings = field(default_factory=FlashLibSettings)
    temporary_files: TemporaryFileSettings = field(default_factory=TemporaryFileSettings)
    connection_timeouts: ConnectionTimeoutSettings = field(default_factory=ConnectionTimeoutSettings)
    source_path: Path | None = None


def load_global_settings(path: Path | None = None) -> GuiGlobalSettings:
    source_path = path or _default_config_path()
    data: dict[str, Any] = {}
    if source_path is not None:
        with source_path.open("r", encoding="utf-8") as config_file:
            loaded = json.load(config_file)
        if not isinstance(loaded, dict):
            raise ValueError("Global Settings JSON root must be an object")
        data = loaded

    return GuiGlobalSettings(
        hex2000=_load_hex2000(data.get("hex2000")),
        flash_lib=_load_flash_lib(data.get("flash_lib")),
        temporary_files=_load_temporary_files(data.get("temporary_files")),
        connection_timeouts=_load_connection_timeouts(data.get("connection_timeouts")),
        source_path=source_path,
    )


def validate_global_settings(settings: GuiGlobalSettings) -> list[SettingsIssue]:
    issues: list[SettingsIssue] = []
    _require_non_empty(issues, "hex2000.executable_path", settings.hex2000.executable_path)
    _require_non_empty(issues, "flash_lib.service_image_path", settings.flash_lib.service_image_path)
    _require_non_empty(issues, "flash_lib.service_map_path", settings.flash_lib.service_map_path)
    _require_non_empty(issues, "flash_lib.descriptor_symbol", settings.flash_lib.descriptor_symbol)
    _require_positive_int(issues, "connection_timeouts.tx_timeout_ms", settings.connection_timeouts.tx_timeout_ms)
    _require_positive_int(issues, "connection_timeouts.rx_timeout_ms", settings.connection_timeouts.rx_timeout_ms)
    _require_positive_int(
        issues,
        "connection_timeouts.autobaud_timeout_ms",
        settings.connection_timeouts.autobaud_timeout_ms,
    )
    return issues


def _default_config_path() -> Path | None:
    if USER_CONFIG_PATH.exists():
        return USER_CONFIG_PATH
    if EXAMPLE_CONFIG_PATH.exists():
        return EXAMPLE_CONFIG_PATH
    return None


def _section(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _timeout_value(value: Any, default: int) -> Any:
    if value is None:
        return default
    if isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return value
    return value


def _load_hex2000(value: Any) -> Hex2000Settings:
    if value is None:
        return Hex2000Settings()
    if not isinstance(value, dict):
        raise ValueError("hex2000 must be an object or null")
    executable_path = value.get("executable_path")
    if executable_path is None:
        return Hex2000Settings()
    if not isinstance(executable_path, str):
        raise ValueError("hex2000.executable_path must be a string or null")
    return Hex2000Settings(executable_path=executable_path.strip())


def _load_flash_lib(value: Any) -> FlashLibSettings:
    section = _section(value)
    return FlashLibSettings(
        service_image_path=_string(section.get("service_image_path")),
        service_map_path=_string(section.get("service_map_path")),
        descriptor_symbol=_string(section.get("descriptor_symbol"), DEFAULT_DESCRIPTOR_SYMBOL),
    )


def _load_temporary_files(value: Any) -> TemporaryFileSettings:
    section = _section(value)
    return TemporaryFileSettings(
        sci8_temp_dir=_string(section.get("sci8_temp_dir")),
        keep_generated_sci8_txt=_bool(section.get("keep_generated_sci8_txt")),
    )


def _load_connection_timeouts(value: Any) -> ConnectionTimeoutSettings:
    section = _section(value)
    defaults = ConnectionTimeoutSettings()
    return ConnectionTimeoutSettings(
        tx_timeout_ms=_timeout_value(section.get("tx_timeout_ms"), defaults.tx_timeout_ms),
        rx_timeout_ms=_timeout_value(section.get("rx_timeout_ms"), defaults.rx_timeout_ms),
        autobaud_timeout_ms=_timeout_value(section.get("autobaud_timeout_ms"), defaults.autobaud_timeout_ms),
    )


def _require_non_empty(issues: list[SettingsIssue], field: str, value: str) -> None:
    if not value.strip():
        issues.append(SettingsIssue(field, "must not be empty"))


def _require_positive_int(issues: list[SettingsIssue], field: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        issues.append(SettingsIssue(field, "must be a positive integer"))
