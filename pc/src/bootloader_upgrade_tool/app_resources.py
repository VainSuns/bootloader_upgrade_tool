"""Application-owned Flash Service resources.

The installed resource layout is intentionally deferred to the packaging stage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class AppResourceError(RuntimeError):
    """Base error for application resource configuration and access."""


class AppResourceConfigurationError(AppResourceError):
    """The resource provider configuration is invalid or unavailable."""


class AppResourceNotFoundError(AppResourceError):
    """A configured application resource is not a regular file."""


@dataclass(frozen=True, slots=True)
class FlashServiceResources:
    image_path: Path
    map_path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.image_path, Path) or not isinstance(self.map_path, Path):
            raise TypeError("Flash Service resource paths must be Path values")
        image_path = self.image_path.expanduser().resolve(strict=False)
        map_path = self.map_path.expanduser().resolve(strict=False)
        if image_path == map_path:
            raise AppResourceConfigurationError(
                f"Flash Service image and map paths must differ: {image_path}"
            )
        object.__setattr__(self, "image_path", image_path)
        object.__setattr__(self, "map_path", map_path)


@runtime_checkable
class AppResourceProvider(Protocol):
    def flash_service_image_path(self) -> Path: ...

    def flash_service_map_path(self) -> Path: ...


@dataclass(frozen=True, slots=True)
class DevelopmentResourceProvider:
    resources: FlashServiceResources

    @classmethod
    def from_config(cls, path: str | Path) -> DevelopmentResourceProvider:
        config_path = Path(path).expanduser().resolve(strict=False)
        try:
            with config_path.open("r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        except FileNotFoundError as exc:
            raise AppResourceConfigurationError(
                f"Development resource configuration was not found: {config_path}"
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AppResourceConfigurationError(
                f"Invalid development resource configuration {config_path}: {exc}"
            ) from exc
        expected = {"flash_service_image_path", "flash_service_map_path"}
        if not isinstance(data, dict) or set(data) != expected:
            raise AppResourceConfigurationError(
                f"Development resource configuration {config_path} must be an object "
                f"with exactly these fields: {', '.join(sorted(expected))}"
            )
        image_path = _configured_path(config_path, data["flash_service_image_path"], "flash_service_image_path")
        map_path = _configured_path(config_path, data["flash_service_map_path"], "flash_service_map_path")
        if image_path.suffix.lower() not in {".out", ".txt"}:
            raise AppResourceConfigurationError(
                f"flash_service_image_path in {config_path} must end in .out or .txt: {image_path}"
            )
        if map_path.suffix.lower() != ".map":
            raise AppResourceConfigurationError(
                f"flash_service_map_path in {config_path} must end in .map: {map_path}"
            )
        return cls(FlashServiceResources(image_path, map_path))

    def flash_service_image_path(self) -> Path:
        return _regular_file(self.resources.image_path, "Flash Service image")

    def flash_service_map_path(self) -> Path:
        return _regular_file(self.resources.map_path, "Flash Service map")


@dataclass(frozen=True, slots=True)
class InstalledResourceProvider:
    """Packaging-pending placeholder; no installed resource layout is defined."""

    def flash_service_image_path(self) -> Path:
        raise _installed_layout_error()

    def flash_service_map_path(self) -> Path:
        raise _installed_layout_error()


def default_development_resource_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "development_app_resources.json"


def load_development_resource_provider(
    path: str | Path | None = None,
) -> DevelopmentResourceProvider:
    config_path = (
        Path(path).expanduser().resolve(strict=False)
        if path is not None
        else default_development_resource_config_path()
    )
    try:
        return DevelopmentResourceProvider.from_config(config_path)
    except AppResourceConfigurationError as exc:
        example = config_path.with_name("development_app_resources.json.example")
        raise AppResourceConfigurationError(
            f"{exc}. Copy {example} to {config_path} and edit both absolute paths."
        ) from exc


def _configured_path(config_path: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise AppResourceConfigurationError(
            f"{field} in {config_path} must be a non-empty string"
        )
    resource_path = Path(value.strip()).expanduser()
    if not resource_path.is_absolute():
        raise AppResourceConfigurationError(
            f"{field} in {config_path} must be an absolute path: {value}"
        )
    return resource_path.resolve(strict=False)


def _regular_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise AppResourceNotFoundError(f"{label} is not a regular file: {path}")
    return path


def _installed_layout_error() -> AppResourceConfigurationError:
    return AppResourceConfigurationError(
        "Installed Flash Service resource layout will be defined during the packaging stage"
    )


__all__ = [
    "AppResourceConfigurationError",
    "AppResourceError",
    "AppResourceNotFoundError",
    "AppResourceProvider",
    "DevelopmentResourceProvider",
    "FlashServiceResources",
    "InstalledResourceProvider",
    "default_development_resource_config_path",
    "load_development_resource_provider",
]
