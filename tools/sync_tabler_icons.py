#!/usr/bin/env python3
"""
Import and normalize a selected subset of Tabler Outline SVG icons.

The script does more than copy files:
- reads semantic icon mappings from icon_manifest.json;
- resolves unique SVG source files from a fixed Tabler release;
- validates that every SVG is a simple, static outline icon;
- rejects scripts, embedded images, external links, gradients, masks, filters, etc.;
- normalizes the root SVG attributes for Qt/PySide6;
- removes width, height, class, style and other unnecessary metadata;
- preserves Tabler geometry while applying one project-wide stroke color;
- writes files atomically;
- optionally removes stale SVG files;
- copies the Tabler license;
- creates a resolved manifest containing SHA-256 hashes.

No third-party Python package is required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)

EXPECTED_VIEWBOX = "0 0 24 24"
DEFAULT_STROKE_COLOR = "#526173"
DEFAULT_STROKE_WIDTH = "2"

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

URL_LIKE_RE = re.compile(r"(?:url\s*\(|javascript:|data:|https?://|file:)", re.IGNORECASE)


class IconImportError(RuntimeError):
    """Raised when the manifest or an SVG violates the project contract."""


@dataclass(frozen=True)
class Manifest:
    library: str
    version: str
    style: str
    license_name: str
    icons: Mapping[str, str]


@dataclass(frozen=True)
class ImportedIcon:
    filename: str
    source_path: str
    sha256: str


def local_name(name: str) -> str:
    """Return the local part of an XML tag or attribute."""
    if name.startswith("{"):
        return name.split("}", 1)[1]
    return name


def normalize_space(value: str) -> str:
    return " ".join(value.strip().split())


def read_manifest(path: Path) -> Manifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IconImportError(f"Manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise IconImportError(
            f"Manifest JSON is invalid at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise IconImportError("Manifest root must be a JSON object.")

    required = ("library", "version", "style", "license", "icons")
    missing = [key for key in required if key not in payload]
    if missing:
        raise IconImportError(f"Manifest is missing required keys: {', '.join(missing)}")

    icons = payload["icons"]
    if not isinstance(icons, dict) or not icons:
        raise IconImportError("Manifest 'icons' must be a non-empty object.")

    normalized_icons: dict[str, str] = {}
    for semantic_name, filename in icons.items():
        if not isinstance(semantic_name, str) or not semantic_name.strip():
            raise IconImportError("Every icon semantic name must be a non-empty string.")
        if not isinstance(filename, str):
            raise IconImportError(f"Icon filename for {semantic_name!r} must be a string.")

        filename = filename.strip()
        candidate = Path(filename)
        if (
            candidate.name != filename
            or candidate.suffix.lower() != ".svg"
            or "/" in filename
            or "\\" in filename
            or filename in {".svg", "..svg"}
        ):
            raise IconImportError(
                f"Unsafe or invalid SVG filename for {semantic_name!r}: {filename!r}"
            )
        normalized_icons[semantic_name.strip()] = filename

    style = str(payload["style"]).strip().lower()
    if style != "outline":
        raise IconImportError(
            f"Only Tabler Outline icons are permitted; manifest style is {style!r}."
        )

    return Manifest(
        library=str(payload["library"]).strip(),
        version=str(payload["version"]).strip(),
        style=style,
        license_name=str(payload["license"]).strip(),
        icons=normalized_icons,
    )


def resolve_outline_source(source_root: Path) -> Path:
    """
    Accept either:
    - the extracted Tabler release root;
    - the icons/outline directory itself.

    Several candidate layouts are supported so the script remains usable if the
    upstream archive layout changes slightly.
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
    candidates = [
        source_root / "LICENSE",
        source_root / "LICENSE.txt",
        source_root / "LICENSE.md",
        source_root.parent / "LICENSE",
        source_root.parent / "LICENSE.txt",
        source_root.parent / "LICENSE.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise IconImportError(
        "Tabler license file was not found. Expected LICENSE, LICENSE.txt, or LICENSE.md "
        "in the release root."
    )


def parse_svg(path: Path) -> ET.ElementTree:
    # ElementTree does not resolve external entities. Rejecting DTDs adds another
    # explicit safety barrier and keeps the accepted input format deterministic.
    raw = path.read_bytes()
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise IconImportError(f"{path.name}: DTD/entity declarations are not permitted.")

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

    # Remove non-rendering metadata elements before validating the remaining tree.
    for parent in list(root.iter()):
        for child in list(parent):
            if local_name(child.tag) in REMOVABLE_TAGS:
                parent.remove(child)

    for element in root.iter():
        tag = local_name(element.tag)

        if tag in FORBIDDEN_TAGS:
            raise IconImportError(f"{source_path.name}: forbidden SVG element <{tag}>.")
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
                    f"{source_path.name}: external or reusable references are not permitted."
                )
            if plain_name.lower().startswith("on"):
                raise IconImportError(
                    f"{source_path.name}: event-handler attribute {plain_name!r} is forbidden."
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
                f"{source_path.name}: non-outline fill value {fill!r} is not permitted."
            )

        element_stroke = element.attrib.get("stroke")
        if element_stroke is not None and element_stroke.lower() != "none":
            element.attrib["stroke"] = stroke_color

        # Child-level stroke widths/colors are normalized when explicitly present.
        if "stroke-width" in element.attrib:
            element.attrib["stroke-width"] = stroke_width
        if "stroke-linecap" in element.attrib:
            element.attrib["stroke-linecap"] = "round"
        if "stroke-linejoin" in element.attrib:
            element.attrib["stroke-linejoin"] = "round"

    # Replace the root attributes with the project contract in deterministic order.
    # Geometry-related attributes exist only on child elements, so clearing root
    # presentation metadata is safe.
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


def copy_license(source_root: Path, destination: Path, dry_run: bool) -> None:
    license_source = find_license(source_root)
    if dry_run:
        print(f"[DRY-RUN] copy license: {license_source} -> {destination}")
        return

    data = license_source.read_bytes()
    atomic_write(destination, data)
    print(f"[OK] license: {destination}")


def clean_stale_icons(
    destination: Path,
    expected_filenames: set[str],
    *,
    dry_run: bool,
) -> None:
    if not destination.exists():
        return

    for existing in sorted(destination.glob("*.svg")):
        if existing.name not in expected_filenames:
            if dry_run:
                print(f"[DRY-RUN] remove stale icon: {existing}")
            else:
                existing.unlink()
                print(f"[REMOVED] stale icon: {existing.name}")


def build_resolved_manifest(
    manifest: Manifest,
    imported: Iterable[ImportedIcon],
    *,
    stroke_color: str,
    stroke_width: str,
) -> dict:
    imported_by_name = {item.filename: item for item in imported}
    return {
        "library": manifest.library,
        "version": manifest.version,
        "style": manifest.style,
        "license": manifest.license_name,
        "normalization": {
            "viewBox": EXPECTED_VIEWBOX,
            "fill": "none",
            "stroke": stroke_color,
            "strokeWidth": stroke_width,
            "strokeLinecap": "round",
            "strokeLinejoin": "round",
            "removedRootAttributes": ["width", "height", "class", "style", "id"],
        },
        "icons": {
            semantic_name: {
                "file": filename,
                "sha256": imported_by_name[filename].sha256,
            }
            for semantic_name, filename in sorted(manifest.icons.items())
        },
    }


def import_icons(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    source_argument = args.source.resolve()
    destination = args.destination.resolve()

    manifest = read_manifest(manifest_path)
    outline_source = resolve_outline_source(source_argument)

    # The actual release root is needed to locate LICENSE.
    release_root = source_argument
    if outline_source == source_argument:
        # If icons/outline was passed directly, move up two levels where possible.
        if source_argument.name == "outline" and source_argument.parent.name == "icons":
            release_root = source_argument.parent.parent

    unique_filenames = sorted(set(manifest.icons.values()))
    expected = set(unique_filenames)

    print(f"Library      : {manifest.library}")
    print(f"Version      : {manifest.version}")
    print(f"Style        : {manifest.style}")
    print(f"Source       : {outline_source}")
    print(f"Destination  : {destination}")
    print(f"Unique icons : {len(unique_filenames)}")
    print(f"Stroke       : {args.stroke_color}")
    print(f"Stroke width : {args.stroke_width}")

    missing = [
        filename
        for filename in unique_filenames
        if not (outline_source / filename).is_file()
    ]
    if missing:
        rendered = "\n".join(f"  - {name}" for name in missing)
        raise IconImportError(
            "The following manifest icons do not exist in the selected Tabler release:\n"
            f"{rendered}"
        )

    if args.clean:
        clean_stale_icons(destination, expected, dry_run=args.dry_run)

    imported: list[ImportedIcon] = []

    for filename in unique_filenames:
        source_path = outline_source / filename
        normalized = validate_and_normalize_svg(
            source_path,
            stroke_color=args.stroke_color,
            stroke_width=args.stroke_width,
        )
        digest = sha256_bytes(normalized)
        destination_path = destination / filename

        imported.append(
            ImportedIcon(
                filename=filename,
                source_path=str(source_path),
                sha256=digest,
            )
        )

        if args.dry_run:
            print(f"[DRY-RUN] normalize: {filename} sha256={digest}")
            continue

        if destination_path.is_file() and destination_path.read_bytes() == normalized:
            print(f"[UNCHANGED] {filename}")
        else:
            atomic_write(destination_path, normalized)
            print(f"[UPDATED] {filename}")

    resolved_payload = build_resolved_manifest(
        manifest,
        imported,
        stroke_color=args.stroke_color,
        stroke_width=args.stroke_width,
    )
    resolved_data = (
        json.dumps(resolved_payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    ).encode("utf-8")
    resolved_path = args.resolved_manifest.resolve()

    if args.dry_run:
        print(f"[DRY-RUN] write resolved manifest: {resolved_path}")
    else:
        atomic_write(resolved_path, resolved_data)
        print(f"[OK] resolved manifest: {resolved_path}")

    if args.license_destination is not None:
        copy_license(
            release_root,
            args.license_destination.resolve(),
            dry_run=args.dry_run,
        )

    print("Validation and normalization completed successfully.")
    return 0


def positive_number_text(value: str) -> str:
    try:
        numeric = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if numeric <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import, validate and normalize a selected subset of Tabler Outline SVG icons."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help=(
            "Extracted Tabler release root or its icons/outline directory."
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
        help=(
            "Normalized root stroke color. Default: %(default)s. "
            "Use 'currentColor' only if the Qt icon loader explicitly supports it."
        ),
    )
    parser.add_argument(
        "--stroke-width",
        default=DEFAULT_STROKE_WIDTH,
        type=positive_number_text,
        help="Normalized stroke width. Default: %(default)s.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove destination SVG files that are not referenced by the manifest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report changes without writing files.",
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
