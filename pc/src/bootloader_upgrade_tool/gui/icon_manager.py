"""Semantic Tabler icon loading for the Phase 11 GUI.

Widgets request semantic names from ``icon_manifest.json``. Direct SVG paths
must not be used outside this module.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Final

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme_tokens import ICON_TONES, THEME_ID

_EXPECTED_LIBRARY: Final = "Tabler Icons"
_EXPECTED_PACKAGE: Final = "@tabler/icons"
_EXPECTED_VERSION: Final = "3.44.0"
_EXPECTED_STYLE: Final = "outline"
_EXPECTED_STROKE: Final = "#526173"
_SAFE_FILENAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.svg$")


class IconError(RuntimeError):
    """Raised when semantic icon resources violate the frozen contract."""


@dataclass(frozen=True)
class IconManifest:
    version: str
    icons: dict[str, str]


class IconManager:
    """Load, recolor, render, and cache project-owned Tabler SVG icons."""

    def __init__(self, resource_root: Path | None = None) -> None:
        self._resource_root = resource_root
        self._manifest = self._read_manifest()
        self._svg_cache: dict[str, bytes] = {}
        self._icon_cache: dict[tuple[str, str, int, float, str], QIcon] = {}

    @property
    def semantic_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._manifest.icons))

    @property
    def version(self) -> str:
        return self._manifest.version

    def has_icon(self, semantic_name: str) -> bool:
        return semantic_name in self._manifest.icons

    def icon(
        self,
        semantic_name: str,
        *,
        tone: str = "neutral",
        size: int = 16,
        device_pixel_ratio: float = 1.0,
    ) -> QIcon:
        """Return a cached QIcon with normal, disabled, active and selected modes."""

        if semantic_name not in self._manifest.icons:
            raise IconError(f"unknown semantic icon name: {semantic_name!r}")
        if tone not in ICON_TONES:
            allowed = ", ".join(sorted(ICON_TONES))
            raise IconError(f"unknown icon tone {tone!r}; expected one of: {allowed}")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError("icon size must be a positive integer")
        if device_pixel_ratio <= 0:
            raise ValueError("device_pixel_ratio must be greater than zero")

        cache_key = (semantic_name, tone, size, float(device_pixel_ratio), THEME_ID)
        cached = self._icon_cache.get(cache_key)
        if cached is not None:
            return QIcon(cached)

        icon = QIcon()
        mode_tones = {
            QIcon.Mode.Normal: tone,
            QIcon.Mode.Disabled: "disabled",
            QIcon.Mode.Active: "primary" if tone == "neutral" else tone,
            QIcon.Mode.Selected: "primary" if tone == "neutral" else tone,
        }
        for mode, mode_tone in mode_tones.items():
            pixmap = self._render_pixmap(
                semantic_name,
                ICON_TONES[mode_tone],
                size,
                float(device_pixel_ratio),
            )
            icon.addPixmap(pixmap, mode, QIcon.State.Off)
            icon.addPixmap(pixmap, mode, QIcon.State.On)

        self._icon_cache[cache_key] = QIcon(icon)
        return icon

    def clear_cache(self) -> None:
        self._svg_cache.clear()
        self._icon_cache.clear()

    def validate_resources(self) -> None:
        """Read and validate every manifest-referenced SVG resource."""

        for filename in sorted(set(self._manifest.icons.values())):
            self._svg_bytes(filename)

    def _read_manifest(self) -> IconManifest:
        try:
            payload = json.loads(self._read_text("icon_manifest.json"))
        except json.JSONDecodeError as exc:
            raise IconError(f"invalid icon manifest JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise IconError("icon manifest root must be an object")
        expected = {
            "schema_version": 1,
            "library": _EXPECTED_LIBRARY,
            "package": _EXPECTED_PACKAGE,
            "version": _EXPECTED_VERSION,
            "style": _EXPECTED_STYLE,
            "source_directory": "icons/outline",
            "license": "MIT",
        }
        for name, value in expected.items():
            if payload.get(name) != value:
                raise IconError(
                    f"icon manifest {name!r} must be {value!r}, "
                    f"got {payload.get(name)!r}"
                )

        icons = payload.get("icons")
        if not isinstance(icons, dict) or not icons:
            raise IconError("icon manifest 'icons' must be a non-empty object")

        normalized: dict[str, str] = {}
        for semantic_name, filename in icons.items():
            if not isinstance(semantic_name, str) or not semantic_name.strip():
                raise IconError("icon manifest contains an invalid semantic name")
            if not isinstance(filename, str) or not _SAFE_FILENAME.fullmatch(filename):
                raise IconError(
                    f"unsafe SVG filename for {semantic_name!r}: {filename!r}"
                )
            path = PurePosixPath(filename)
            if path.name != filename or path.is_absolute() or ".." in path.parts:
                raise IconError(
                    f"SVG filename must be a basename for {semantic_name!r}: {filename!r}"
                )
            normalized[semantic_name] = filename

        statistics = payload.get("statistics")
        if not isinstance(statistics, dict):
            raise IconError("icon manifest 'statistics' must be an object")
        if statistics.get("semantic_entries") != len(normalized):
            raise IconError("icon manifest semantic entry count does not match mapping")
        if statistics.get("unique_svg_files") != len(set(normalized.values())):
            raise IconError("icon manifest unique SVG count does not match mapping")

        contract = payload.get("project_contract")
        if not isinstance(contract, dict):
            raise IconError("icon manifest 'project_contract' must be an object")
        expected_contract = {
            "viewBox": "0 0 24 24",
            "fill": "none",
            "stroke": _EXPECTED_STROKE,
            "stroke_width": "2",
            "stroke_linecap": "round",
            "stroke_linejoin": "round",
        }
        if contract != expected_contract:
            raise IconError("icon manifest project contract does not match GUI V1.0")

        return IconManifest(version=payload["version"], icons=normalized)

    def _read_text(self, name: str) -> str:
        try:
            if self._resource_root is not None:
                return (self._resource_root / name).read_text(encoding="utf-8")
            resource = resources.files(__package__).joinpath("resources/icons", name)
            return resource.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise IconError(f"unable to read icon resource {name!r}: {exc}") from exc

    def _read_bytes(self, relative_path: str) -> bytes:
        try:
            if self._resource_root is not None:
                return (self._resource_root / relative_path).read_bytes()
            resource = resources.files(__package__).joinpath(
                "resources/icons", relative_path
            )
            return resource.read_bytes()
        except OSError as exc:
            raise IconError(
                f"unable to read icon resource {relative_path!r}: {exc}"
            ) from exc

    def _svg_bytes(self, filename: str) -> bytes:
        cached = self._svg_cache.get(filename)
        if cached is not None:
            return cached

        raw = self._read_bytes(f"tabler/outline/{filename}")
        lowered = raw.lower()
        if b"<script" in lowered or b"<!doctype" in lowered or b"<!entity" in lowered:
            raise IconError(f"unsafe SVG content in {filename!r}")
        if b'viewbox="0 0 24 24"' not in lowered:
            raise IconError(f"unexpected SVG viewBox in {filename!r}")
        if _EXPECTED_STROKE.lower().encode("ascii") not in lowered:
            raise IconError(f"unexpected SVG stroke color in {filename!r}")

        renderer = QSvgRenderer(QByteArray(raw))
        if not renderer.isValid():
            raise IconError(f"Qt cannot render SVG resource {filename!r}")

        self._svg_cache[filename] = raw
        return raw

    def _render_pixmap(
        self,
        semantic_name: str,
        color: str,
        size: int,
        device_pixel_ratio: float,
    ) -> QPixmap:
        filename = self._manifest.icons[semantic_name]
        raw = self._svg_bytes(filename)
        recolored = raw.replace(
            _EXPECTED_STROKE.encode("ascii"),
            QColor(color).name(QColor.NameFormat.HexRgb).upper().encode("ascii"),
        )
        renderer = QSvgRenderer(QByteArray(recolored))
        if not renderer.isValid():
            raise IconError(f"Qt cannot render recolored SVG {filename!r}")

        physical_size = max(1, round(size * device_pixel_ratio))
        pixmap = QPixmap(QSize(physical_size, physical_size))
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(device_pixel_ratio)

        painter = QPainter(pixmap)
        try:
            renderer.render(painter)
        finally:
            painter.end()
        return pixmap
