#!/usr/bin/env python3
"""
Import and normalize a selected subset of Tabler Outline SVG icons.

The synchronization is deliberately strict:

- the manifest is the source of truth for package, release, style, statistics,
  and the project-wide SVG normalization contract;
- the caller must identify the selected upstream release and it must match the
  manifest version;
- every source SVG and the upstream license are validated before any output is
  changed;
- output updates are committed as one rollback-protected batch;
- stale SVG files are removed only after all replacement outputs are ready;
- the resolved manifest records deterministic SHA-256 hashes.

No third-party Python package is required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)

EXPECTED_SCHEMA_VERSION = 1
EXPECTED_LIBRARY = "Tabler Icons"
EXPECTED_PACKAGE = "@tabler/icons"
EXPECTED_STYLE = "outline"
EXPECTED_SOURCE_DIRECTORY = "icons/outline"
EXPECTED_LICENSE = "MIT"

EXPECTED_VIEWBOX = "0 0 24 24"
DEFAULT_STROKE_COLOR = "#526173"
DEFAULT_STROKE_WIDTH = "2"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
URL_LIKE_RE = re.compile(
    r"(?:url\s*\(|javascript:|data:|https?://|file:)",
    re.IGNORECASE,
)

# Tabler Outline icons should only require simple static geometry.
ALLOWED_TAGS = {
    "svg",
    "g",
    "path",
    "line",
    "polyline",
    "polygon",
    "rect",
    "circle",
    "ellipse",
}

REMOVABLE_TAGS = {
    "title",
    "desc",
    "metadata",
}

FORBIDDEN_TAGS = {
    "script",
    "image",
    "foreignObject",
    "style",
    "filter",
    "mask",
    "clipPath",
    "linearGradient",
    "radialGradient",
    "pattern",
    "symbol",
    "use",
    "animate",
    "animateMotion",
    "animateTransform",
    "set",
}

DROP_ATTRIBUTES = {
    "width",
    "height",
    "class",
    "style",
    "id",
    "role",
    "focusable",
    "aria-hidden",
    "aria-label",
    "tabindex",
}


class IconImportError(RuntimeError):
    """Raised when the manifest, release, SVG, or output violates the contract."""


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    library: str
    package: str
    version: str
    style: str
    source_directory: str
    license_name: str
    stroke_color: str
    stroke_width: str
    icons: Mapping[str, str]


@dataclass(frozen=True)
class PreparedIcon:
    filename: str
    normalized: bytes
    sha256: str


@dataclass(frozen=True)
class CommitReport:
    updated: tuple[Path, ...]
    unchanged: tuple[Path, ...]
    removed: tuple[Path, ...]


def local_name(name: str) -> str:
    """Return the local part of an XML tag or attribute."""
    if name.startswith("{"):
        return name.split("}", 1)[1]
    return name


def normalize_space(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_hex_color(value: str) -> str:
    normalized = value.strip()
    if not HEX_COLOR_RE.fullmatch(normalized):
        raise ValueError(
            "must be a six-digit hexadecimal color such as #526173"
        )
    return normalized.upper()


def stroke_color_text(value: str) -> str:
    try:
        return normalize_hex_color(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def positive_number_text(value: str) -> str:
    try:
        numeric = Decimal(value.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc

    if not numeric.is_finite() or numeric <= 0:
        raise argparse.ArgumentTypeError(
            "must be a finite number greater than zero"
        )

    normalized = format(numeric.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _manifest_color(value: object) -> str:
    if not isinstance(value, str):
        raise IconImportError("Manifest project_contract.stroke must be a string.")
    try:
        return normalize_hex_color(value)
    except ValueError as exc:
        raise IconImportError(
            f"Manifest project_contract.stroke {exc}."
        ) from exc


def _manifest_width(value: object) -> str:
    if not isinstance(value, str):
        raise IconImportError(
            "Manifest project_contract.stroke_width must be a string."
        )
    try:
        return positive_number_text(value)
    except argparse.ArgumentTypeError as exc:
        raise IconImportError(
            f"Manifest project_contract.stroke_width {exc}."
        ) from exc


def read_manifest(path: Path) -> Manifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IconImportError(f"Manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise IconImportError(
            f"Manifest JSON is invalid at line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise IconImportError("Manifest root must be a JSON object.")

    required = (
        "schema_version",
        "library",
        "package",
        "version",
        "style",
        "source_directory",
        "license",
        "project_contract",
        "statistics",
        "icons",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise IconImportError(
            f"Manifest is missing required keys: {', '.join(missing)}"
        )

    if payload["schema_version"] != EXPECTED_SCHEMA_VERSION:
        raise IconImportError(
            "Unsupported manifest schema_version: "
            f"{payload['schema_version']!r}; expected {EXPECTED_SCHEMA_VERSION}."
        )

    library = str(payload["library"]).strip()
    package = str(payload["package"]).strip()
    version = str(payload["version"]).strip()
    style = str(payload["style"]).strip().lower()
    source_directory = str(payload["source_directory"]).strip()
    license_name = str(payload["license"]).strip()

    if library != EXPECTED_LIBRARY:
        raise IconImportError(
            f"Unexpected icon library {library!r}; expected {EXPECTED_LIBRARY!r}."
        )
    if package != EXPECTED_PACKAGE:
        raise IconImportError(
            f"Unexpected icon package {package!r}; expected {EXPECTED_PACKAGE!r}."
        )
    if not VERSION_RE.fullmatch(version):
        raise IconImportError(
            f"Manifest version must use MAJOR.MINOR.PATCH form; found {version!r}."
        )
    if style != EXPECTED_STYLE:
        raise IconImportError(
            f"Only Tabler Outline icons are permitted; manifest style is {style!r}."
        )
    if source_directory != EXPECTED_SOURCE_DIRECTORY:
        raise IconImportError(
            "Manifest source_directory must be "
            f"{EXPECTED_SOURCE_DIRECTORY!r}; found {source_directory!r}."
        )
    if license_name != EXPECTED_LICENSE:
        raise IconImportError(
            f"Unexpected icon license {license_name!r}; expected {EXPECTED_LICENSE!r}."
        )

    contract = payload["project_contract"]
    if not isinstance(contract, dict):
        raise IconImportError("Manifest 'project_contract' must be an object.")

    expected_contract_keys = {
        "viewBox",
        "fill",
        "stroke",
        "stroke_width",
        "stroke_linecap",
        "stroke_linejoin",
    }
    missing_contract = sorted(expected_contract_keys - set(contract))
    extra_contract = sorted(set(contract) - expected_contract_keys)
    if missing_contract or extra_contract:
        details: list[str] = []
        if missing_contract:
            details.append(f"missing={missing_contract}")
        if extra_contract:
            details.append(f"unexpected={extra_contract}")
        raise IconImportError(
            "Manifest project_contract keys do not match the frozen contract: "
            + ", ".join(details)
        )

    view_box = normalize_space(str(contract["viewBox"]))
    fill = str(contract["fill"]).strip().lower()
    stroke_color = _manifest_color(contract["stroke"])
    stroke_width = _manifest_width(contract["stroke_width"])
    stroke_linecap = str(contract["stroke_linecap"]).strip().lower()
    stroke_linejoin = str(contract["stroke_linejoin"]).strip().lower()

    if view_box != EXPECTED_VIEWBOX:
        raise IconImportError(
            f"Manifest project_contract.viewBox must be {EXPECTED_VIEWBOX!r}."
        )
    if fill != "none":
        raise IconImportError("Manifest project_contract.fill must be 'none'.")
    if stroke_color != DEFAULT_STROKE_COLOR:
        raise IconImportError(
            "Manifest project_contract.stroke must be "
            f"{DEFAULT_STROKE_COLOR!r}; found {stroke_color!r}."
        )
    if stroke_width != DEFAULT_STROKE_WIDTH:
        raise IconImportError(
            "Manifest project_contract.stroke_width must be "
            f"{DEFAULT_STROKE_WIDTH!r}; found {stroke_width!r}."
        )
    if stroke_linecap != "round" or stroke_linejoin != "round":
        raise IconImportError(
            "Manifest stroke_linecap and stroke_linejoin must both be 'round'."
        )

    icons = payload["icons"]
    if not isinstance(icons, dict) or not icons:
        raise IconImportError("Manifest 'icons' must be a non-empty object.")

    normalized_icons: dict[str, str] = {}
    for semantic_name, filename in icons.items():
        if not isinstance(semantic_name, str) or not semantic_name.strip():
            raise IconImportError(
                "Every icon semantic name must be a non-empty string."
            )
        if not isinstance(filename, str):
            raise IconImportError(
                f"Icon filename for {semantic_name!r} must be a string."
            )

        normalized_semantic_name = semantic_name.strip()
        if normalized_semantic_name in normalized_icons:
            raise IconImportError(
                "Duplicate semantic icon name after whitespace normalization: "
                f"{normalized_semantic_name!r}."
            )

        normalized_filename = filename.strip()
        candidate = Path(normalized_filename)
        if (
            candidate.name != normalized_filename
            or candidate.suffix.lower() != ".svg"
            or "/" in normalized_filename
            or "\\" in normalized_filename
            or normalized_filename in {".svg", "..svg"}
        ):
            raise IconImportError(
                "Unsafe or invalid SVG filename for "
                f"{normalized_semantic_name!r}: {normalized_filename!r}"
            )

        normalized_icons[normalized_semantic_name] = normalized_filename

    statistics = payload["statistics"]
    if not isinstance(statistics, dict):
        raise IconImportError("Manifest 'statistics' must be an object.")

    expected_stat_keys = {"semantic_entries", "unique_svg_files"}
    missing_stats = sorted(expected_stat_keys - set(statistics))
    extra_stats = sorted(set(statistics) - expected_stat_keys)
    if missing_stats or extra_stats:
        details = []
        if missing_stats:
            details.append(f"missing={missing_stats}")
        if extra_stats:
            details.append(f"unexpected={extra_stats}")
        raise IconImportError(
            "Manifest statistics keys do not match the frozen contract: "
            + ", ".join(details)
        )

    actual_semantic_entries = len(normalized_icons)
    actual_unique_svg_files = len(set(normalized_icons.values()))

    if statistics["semantic_entries"] != actual_semantic_entries:
        raise IconImportError(
            "Manifest statistics.semantic_entries does not match the icon mapping: "
            f"declared={statistics['semantic_entries']!r}, "
            f"actual={actual_semantic_entries}."
        )
    if statistics["unique_svg_files"] != actual_unique_svg_files:
        raise IconImportError(
            "Manifest statistics.unique_svg_files does not match the icon mapping: "
            f"declared={statistics['unique_svg_files']!r}, "
            f"actual={actual_unique_svg_files}."
        )

    return Manifest(
        schema_version=EXPECTED_SCHEMA_VERSION,
        library=library,
        package=package,
        version=version,
        style=style,
        source_directory=source_directory,
        license_name=license_name,
        stroke_color=stroke_color,
        stroke_width=stroke_width,
        icons=normalized_icons,
    )


def resolve_outline_source(source_root: Path) -> Path:
    """
    Accept either the extracted Tabler release root or an Outline SVG directory.
    """
    candidates = [
        source_root,
        source_root / "icons" / "outline",
        source_root / "packages" / "icons" / "icons",
        source_root / "packages" / "icons" / "icons" / "outline",
    ]

    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.svg")):
            return candidate.resolve()

    rendered = "\n".join(f"  - {item}" for item in candidates)
    raise IconImportError(
        "Could not locate a directory containing Tabler Outline SVG files.\n"
        f"Checked:\n{rendered}"
    )


def find_license(source_root: Path) -> Path:
    search_roots = [source_root]
    search_roots.extend(list(source_root.parents)[:4])

    candidates: list[Path] = []
    for root in search_roots:
        candidates.extend(
            [
                root / "LICENSE",
                root / "LICENSE.txt",
                root / "LICENSE.md",
            ]
        )

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate.resolve()

    raise IconImportError(
        "Tabler license file was not found. Expected LICENSE, LICENSE.txt, "
        "or LICENSE.md in the selected release root or one of its parents."
    )


def read_license_bytes(source_root: Path) -> bytes:
    license_path = find_license(source_root)
    try:
        data = license_path.read_bytes()
    except OSError as exc:
        raise IconImportError(
            f"Unable to read the Tabler license: {license_path}"
        ) from exc

    if not data.strip():
        raise IconImportError(f"Tabler license is empty: {license_path}")
    return data


def parse_svg(path: Path) -> ET.ElementTree:
    # ElementTree does not resolve external entities. Rejecting DTDs adds another
    # explicit safety barrier and keeps the accepted input format deterministic.
    raw = path.read_bytes()
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise IconImportError(
            f"{path.name}: DTD/entity declarations are not permitted."
        )

    try:
        return ET.ElementTree(ET.fromstring(raw))
    except ET.ParseError as exc:
        raise IconImportError(f"{path.name}: invalid SVG XML: {exc}") from exc


def reject_unsafe_value(filename: str, attr_name: str, value: str) -> None:
    if URL_LIKE_RE.search(value):
        raise IconImportError(
            f"{filename}: attribute {attr_name!r} contains a forbidden URL-like value."
        )


def validate_and_normalize_svg(
    source_path: Path,
    *,
    stroke_color: str,
    stroke_width: str,
) -> bytes:
    tree = parse_svg(source_path)
    root = tree.getroot()

    if local_name(root.tag) != "svg":
        raise IconImportError(f"{source_path.name}: root element must be <svg>.")

    view_box = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if normalize_space(view_box or "") != EXPECTED_VIEWBOX:
        raise IconImportError(
            f"{source_path.name}: expected viewBox={EXPECTED_VIEWBOX!r}, "
            f"found {view_box!r}."
        )

    # Remove non-rendering metadata before validating the remaining tree.
    for parent in list(root.iter()):
        for child in list(parent):
            if local_name(child.tag) in REMOVABLE_TAGS:
                parent.remove(child)

    for element in root.iter():
        tag = local_name(element.tag)

        if tag in FORBIDDEN_TAGS:
            raise IconImportError(
                f"{source_path.name}: forbidden SVG element <{tag}>."
            )
        if tag not in ALLOWED_TAGS:
            raise IconImportError(
                f"{source_path.name}: unsupported SVG element <{tag}>. "
                "Only simple static outline geometry is permitted."
            )

        # Validate all original values before attributes are cleaned.
        for attr_name, attr_value in list(element.attrib.items()):
            plain_name = local_name(attr_name)
            reject_unsafe_value(source_path.name, plain_name, attr_value)

            if plain_name in {"href", "src"} or attr_name == f"{{{XLINK_NS}}}href":
                raise IconImportError(
                    f"{source_path.name}: external or reusable references "
                    "are not permitted."
                )
            if plain_name.lower().startswith("on"):
                raise IconImportError(
                    f"{source_path.name}: event-handler attribute "
                    f"{plain_name!r} is forbidden."
                )

        # Remove presentation metadata that should be controlled by the project.
        for attr_name in list(element.attrib):
            plain_name = local_name(attr_name)
            if (
                plain_name in DROP_ATTRIBUTES
                or plain_name.startswith("data-")
                or plain_name.startswith("aria-")
            ):
                del element.attrib[attr_name]

        # Enforce Outline semantics. The invisible Tabler canvas path may use
        # stroke="none" and fill="none"; preserve that special case.
        fill = element.attrib.get("fill")
        if fill is not None and fill.lower() not in {"none", "transparent"}:
            raise IconImportError(
                f"{source_path.name}: non-outline fill value {fill!r} "
                "is not permitted."
            )

        element_stroke = element.attrib.get("stroke")
        if element_stroke is not None and element_stroke.lower() != "none":
            element.attrib["stroke"] = stroke_color

        # Child-level stroke properties are normalized when explicitly present.
        if "stroke-width" in element.attrib:
            element.attrib["stroke-width"] = stroke_width
        if "stroke-linecap" in element.attrib:
            element.attrib["stroke-linecap"] = "round"
        if "stroke-linejoin" in element.attrib:
            element.attrib["stroke-linejoin"] = "round"

    # Replace root attributes with the frozen contract in deterministic order.
    root.attrib.clear()
    root.attrib["viewBox"] = EXPECTED_VIEWBOX
    root.attrib["fill"] = "none"
    root.attrib["stroke"] = stroke_color
    root.attrib["stroke-width"] = stroke_width
    root.attrib["stroke-linecap"] = "round"
    root.attrib["stroke-linejoin"] = "round"

    ET.indent(tree, space="  ")
    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    normalized = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + xml_body.rstrip()
        + "\n"
    )
    return normalized.encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def prepare_icons(
    *,
    outline_source: Path,
    filenames: Iterable[str],
    stroke_color: str,
    stroke_width: str,
) -> list[PreparedIcon]:
    """Validate and normalize every selected SVG without modifying outputs."""
    prepared: list[PreparedIcon] = []

    for filename in filenames:
        source_path = outline_source / filename
        normalized = validate_and_normalize_svg(
            source_path,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
        )
        prepared.append(
            PreparedIcon(
                filename=filename,
                normalized=normalized,
                sha256=sha256_bytes(normalized),
            )
        )

    return prepared


def build_resolved_manifest(
    manifest: Manifest,
    prepared: Iterable[PreparedIcon],
    *,
    stroke_color: str,
    stroke_width: str,
) -> dict[str, object]:
    prepared_by_name = {item.filename: item for item in prepared}
    return {
        "library": manifest.library,
        "package": manifest.package,
        "version": manifest.version,
        "upstream_tag": f"v{manifest.version}",
        "style": manifest.style,
        "license": manifest.license_name,
        "normalization": {
            "viewBox": EXPECTED_VIEWBOX,
            "fill": "none",
            "stroke": stroke_color,
            "strokeWidth": stroke_width,
            "strokeLinecap": "round",
            "strokeLinejoin": "round",
            "removedRootAttributes": [
                "width",
                "height",
                "class",
                "style",
                "id",
            ],
        },
        "icons": {
            semantic_name: {
                "file": filename,
                "sha256": prepared_by_name[filename].sha256,
            }
            for semantic_name, filename in sorted(manifest.icons.items())
        },
    }


def _read_original(path: Path) -> bytes | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise IconImportError(f"Output path exists but is not a file: {path}")
    return path.read_bytes()


def commit_outputs(
    *,
    writes: Mapping[Path, bytes],
    stale_paths: Iterable[Path],
) -> CommitReport:
    """
    Commit all prepared outputs as one rollback-protected batch.

    The function is not an OS-level multi-file transaction, but if any write or
    removal fails it restores every touched file to its pre-call contents.
    """
    normalized_writes = {
        Path(path).resolve(): data
        for path, data in writes.items()
    }
    normalized_stale = {
        Path(path).resolve()
        for path in stale_paths
    }

    overlap = set(normalized_writes) & normalized_stale
    if overlap:
        rendered = "\n".join(f"  - {path}" for path in sorted(overlap))
        raise IconImportError(
            "The same output path cannot be written and removed:\n"
            f"{rendered}"
        )

    touched = set(normalized_writes) | normalized_stale
    originals = {
        path: _read_original(path)
        for path in touched
    }

    updated: list[Path] = []
    unchanged: list[Path] = []
    removed: list[Path] = []

    try:
        for path in sorted(normalized_writes, key=str):
            data = normalized_writes[path]
            original = originals[path]
            if original == data:
                unchanged.append(path)
                continue
            atomic_write(path, data)
            updated.append(path)

        for path in sorted(normalized_stale, key=str):
            if path.is_file():
                path.unlink()
                removed.append(path)
            elif path.exists():
                raise IconImportError(
                    f"Stale output path exists but is not a file: {path}"
                )

    except Exception as exc:
        rollback_errors: list[str] = []

        for path in sorted(touched, key=str, reverse=True):
            original = originals[path]
            try:
                if original is None:
                    if path.is_file():
                        path.unlink()
                    elif path.exists():
                        raise OSError("created path is not a regular file")
                else:
                    atomic_write(path, original)
            except OSError as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")

        if rollback_errors:
            rendered = "\n".join(f"  - {item}" for item in rollback_errors)
            raise IconImportError(
                "Icon synchronization failed and rollback was incomplete:\n"
                f"{rendered}"
            ) from exc
        raise

    return CommitReport(
        updated=tuple(updated),
        unchanged=tuple(unchanged),
        removed=tuple(removed),
    )


def import_icons(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    source_argument = args.source.resolve()
    destination = args.destination.resolve()
    resolved_path = args.resolved_manifest.resolve()

    manifest = read_manifest(manifest_path)

    source_version = str(args.source_version).strip()
    if not VERSION_RE.fullmatch(source_version):
        raise IconImportError(
            "--source-version must use MAJOR.MINOR.PATCH form; "
            f"found {source_version!r}."
        )
    if source_version != manifest.version:
        raise IconImportError(
            "Tabler source version does not match the manifest: "
            f"source={source_version!r}, manifest={manifest.version!r}."
        )

    try:
        stroke_color = normalize_hex_color(str(args.stroke_color))
    except ValueError as exc:
        raise IconImportError(f"Invalid --stroke-color: {exc}") from exc
    try:
        stroke_width = positive_number_text(str(args.stroke_width))
    except argparse.ArgumentTypeError as exc:
        raise IconImportError(f"Invalid --stroke-width: {exc}") from exc

    if stroke_color != manifest.stroke_color:
        raise IconImportError(
            "--stroke-color does not match manifest project_contract.stroke: "
            f"argument={stroke_color!r}, manifest={manifest.stroke_color!r}."
        )
    if stroke_width != manifest.stroke_width:
        raise IconImportError(
            "--stroke-width does not match manifest project_contract.stroke_width: "
            f"argument={stroke_width!r}, manifest={manifest.stroke_width!r}."
        )

    outline_source = resolve_outline_source(source_argument)

    # Locate the release root for LICENSE discovery.
    release_root = source_argument
    if outline_source == source_argument:
        if source_argument.name == "outline" and source_argument.parent.name == "icons":
            release_root = source_argument.parent.parent

    unique_filenames = sorted(set(manifest.icons.values()))
    expected = set(unique_filenames)

    print(f"Library        : {manifest.library}")
    print(f"Package        : {manifest.package}")
    print(f"Version        : {manifest.version}")
    print(f"Upstream tag   : v{manifest.version}")
    print(f"Style          : {manifest.style}")
    print(f"Source         : {outline_source}")
    print(f"Destination    : {destination}")
    print(f"Semantic icons : {len(manifest.icons)}")
    print(f"Unique icons   : {len(unique_filenames)}")
    print(f"Stroke         : {stroke_color}")
    print(f"Stroke width   : {stroke_width}")

    missing = [
        filename
        for filename in unique_filenames
        if not (outline_source / filename).is_file()
    ]
    if missing:
        rendered = "\n".join(f"  - {name}" for name in missing)
        raise IconImportError(
            "The following manifest icons do not exist in the selected "
            f"Tabler release:\n{rendered}"
        )

    # Phase A: validate and prepare the complete output set. Nothing below this
    # point modifies destination files until all SVGs and the license are ready.
    prepared = prepare_icons(
        outline_source=outline_source,
        filenames=unique_filenames,
        stroke_color=stroke_color,
        stroke_width=stroke_width,
    )

    resolved_payload = build_resolved_manifest(
        manifest,
        prepared,
        stroke_color=stroke_color,
        stroke_width=stroke_width,
    )
    resolved_data = (
        json.dumps(
            resolved_payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=False,
        )
        + "\n"
    ).encode("utf-8")

    license_path: Path | None = None
    license_data: bytes | None = None
    if args.license_destination is not None:
        license_path = args.license_destination.resolve()
        license_data = read_license_bytes(release_root)

    stale_paths: list[Path] = []
    if args.clean and destination.exists():
        stale_paths = [
            path
            for path in sorted(destination.glob("*.svg"))
            if path.name not in expected
        ]

    if args.dry_run:
        for item in prepared:
            print(
                f"[DRY-RUN] normalize: {item.filename} "
                f"sha256={item.sha256}"
            )
        for path in stale_paths:
            print(f"[DRY-RUN] remove stale icon: {path}")
        print(f"[DRY-RUN] write resolved manifest: {resolved_path}")
        if license_path is not None:
            print(f"[DRY-RUN] write license: {license_path}")
        print("Validation completed successfully; no files were modified.")
        return 0

    # Phase B: commit the already validated output set and roll back on failure.
    writes: dict[Path, bytes] = {
        destination / item.filename: item.normalized
        for item in prepared
    }
    writes[resolved_path] = resolved_data
    if license_path is not None and license_data is not None:
        writes[license_path] = license_data

    report = commit_outputs(
        writes=writes,
        stale_paths=stale_paths,
    )

    destination_resolved = destination.resolve()
    icon_updates = [
        path
        for path in report.updated
        if path.parent == destination_resolved and path.suffix.lower() == ".svg"
    ]
    icon_unchanged = [
        path
        for path in report.unchanged
        if path.parent == destination_resolved and path.suffix.lower() == ".svg"
    ]

    for path in report.removed:
        print(f"[REMOVED] stale icon: {path.name}")
    print(f"[OK] updated SVG files   : {len(icon_updates)}")
    print(f"[OK] unchanged SVG files : {len(icon_unchanged)}")
    print(f"[OK] resolved manifest   : {resolved_path}")
    if license_path is not None:
        print(f"[OK] license             : {license_path}")
    print("Validation and normalization completed successfully.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import, validate, and normalize a selected subset of "
            "Tabler Outline SVG icons."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Extracted Tabler release root or its icons/outline directory.",
    )
    parser.add_argument(
        "--source-version",
        required=True,
        help=(
            "Version of the selected Tabler source release. It must exactly "
            "match icon_manifest.json."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Source icon_manifest.json containing semantic-name-to-SVG mappings.",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Destination directory for normalized SVG files.",
    )
    parser.add_argument(
        "--resolved-manifest",
        type=Path,
        required=True,
        help="Output JSON containing normalized parameters and SHA-256 hashes.",
    )
    parser.add_argument(
        "--license-destination",
        type=Path,
        help="Optional destination file for the upstream Tabler MIT license.",
    )
    parser.add_argument(
        "--stroke-color",
        default=DEFAULT_STROKE_COLOR,
        type=stroke_color_text,
        help=(
            "Normalized root stroke color. It must match the manifest "
            "project_contract. Default: %(default)s."
        ),
    )
    parser.add_argument(
        "--stroke-width",
        default=DEFAULT_STROKE_WIDTH,
        type=positive_number_text,
        help=(
            "Normalized stroke width. It must match the manifest "
            "project_contract. Default: %(default)s."
        ),
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help=(
            "Remove destination SVG files not referenced by the manifest, "
            "after the complete replacement set has been validated."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report changes without modifying any file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        return import_icons(args)
    except IconImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: filesystem operation failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
