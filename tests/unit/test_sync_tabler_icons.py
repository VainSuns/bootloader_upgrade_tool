from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "tools" / "sync_tabler_icons.py"

SPEC = importlib.util.spec_from_file_location(
    "_test_sync_tabler_icons_module",
    SCRIPT_PATH,
)
assert SPEC is not None
assert SPEC.loader is not None

sync_tabler_icons = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_tabler_icons
SPEC.loader.exec_module(sync_tabler_icons)


VALID_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg"
     width="24"
     height="24"
     viewBox="0 0 24 24"
     fill="none"
     stroke="currentColor"
     stroke-width="2"
     stroke-linecap="round"
     stroke-linejoin="round"
     class="icon">
  <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
  <path d="M5 12h14"/>
</svg>
"""

UNSAFE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 24 24"
     fill="none"
     stroke="currentColor">
  <script>not_allowed()</script>
  <path d="M5 12h14"/>
</svg>
"""

LICENSE_TEXT = """\
MIT License

Copyright (c) Test

Permission is hereby granted, free of charge, to any person obtaining a copy.
"""


def write_manifest(
    path: Path,
    icons: dict[str, str],
    *,
    version: str = "3.44.0",
    semantic_entries: int | None = None,
    unique_svg_files: int | None = None,
) -> None:
    payload = {
        "schema_version": 1,
        "library": "Tabler Icons",
        "package": "@tabler/icons",
        "version": version,
        "style": "outline",
        "source_directory": "icons/outline",
        "license": "MIT",
        "project_contract": {
            "viewBox": "0 0 24 24",
            "fill": "none",
            "stroke": "#526173",
            "stroke_width": "2",
            "stroke_linecap": "round",
            "stroke_linejoin": "round",
        },
        "statistics": {
            "semantic_entries": (
                len(icons)
                if semantic_entries is None
                else semantic_entries
            ),
            "unique_svg_files": (
                len(set(icons.values()))
                if unique_svg_files is None
                else unique_svg_files
            ),
        },
        "icons": icons,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def make_release(
    root: Path,
    svg_files: dict[str, str],
) -> tuple[Path, Path]:
    release = root / "tabler-icons-3.44.0"
    outline = release / "icons" / "outline"
    outline.mkdir(parents=True)

    for filename, content in svg_files.items():
        (outline / filename).write_text(content, encoding="utf-8")

    (release / "LICENSE").write_text(LICENSE_TEXT, encoding="utf-8")
    return release, outline


def make_args(
    *,
    release: Path,
    manifest: Path,
    destination: Path,
    resolved_manifest: Path,
    license_destination: Path,
    source_version: str = "3.44.0",
    clean: bool = True,
    dry_run: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        source=release,
        source_version=source_version,
        manifest=manifest,
        destination=destination,
        resolved_manifest=resolved_manifest,
        license_destination=license_destination,
        stroke_color="#526173",
        stroke_width="2",
        clean=clean,
        dry_run=dry_run,
    )


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "nan", "NaN", "inf", "+inf", "-inf"],
)
def test_stroke_width_rejects_non_finite_or_non_positive_values(
    value: str,
) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        sync_tabler_icons.positive_number_text(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "red",
        "#123",
        "#12345678",
        "currentColor",
        "url(http://example.com/icon.svg)",
    ],
)
def test_stroke_color_rejects_values_outside_frozen_contract_shape(
    value: str,
) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        sync_tabler_icons.stroke_color_text(value)


def test_manifest_statistics_must_match_mapping(tmp_path: Path) -> None:
    manifest = tmp_path / "icon_manifest.json"
    write_manifest(
        manifest,
        {"test.icon": "test.svg"},
        semantic_entries=2,
    )

    with pytest.raises(
        sync_tabler_icons.IconImportError,
        match="semantic_entries",
    ):
        sync_tabler_icons.read_manifest(manifest)


def test_source_version_must_match_manifest_before_outputs_change(
    tmp_path: Path,
) -> None:
    release, _ = make_release(
        tmp_path,
        {"test.svg": VALID_SVG},
    )
    manifest = tmp_path / "icon_manifest.json"
    write_manifest(manifest, {"test.icon": "test.svg"})

    destination = tmp_path / "output"
    destination.mkdir()
    existing = destination / "existing.svg"
    existing.write_bytes(b"existing")

    resolved = tmp_path / "resolved.json"
    resolved.write_bytes(b"old resolved")
    license_destination = tmp_path / "LICENSE.txt"
    license_destination.write_bytes(b"old license")

    args = make_args(
        release=release,
        manifest=manifest,
        destination=destination,
        resolved_manifest=resolved,
        license_destination=license_destination,
        source_version="3.45.0",
    )

    with pytest.raises(
        sync_tabler_icons.IconImportError,
        match="does not match",
    ):
        sync_tabler_icons.import_icons(args)

    assert existing.read_bytes() == b"existing"
    assert resolved.read_bytes() == b"old resolved"
    assert license_destination.read_bytes() == b"old license"


def test_full_validation_finishes_before_any_output_is_modified(
    tmp_path: Path,
) -> None:
    release, _ = make_release(
        tmp_path,
        {
            "a-good.svg": VALID_SVG,
            "z-bad.svg": UNSAFE_SVG,
        },
    )
    manifest = tmp_path / "icon_manifest.json"
    write_manifest(
        manifest,
        {
            "test.good": "a-good.svg",
            "test.bad": "z-bad.svg",
        },
    )

    destination = tmp_path / "output"
    destination.mkdir()
    stale = destination / "stale.svg"
    stale.write_bytes(b"keep until validation succeeds")

    resolved = tmp_path / "resolved.json"
    resolved.write_bytes(b"old resolved")
    license_destination = tmp_path / "LICENSE.txt"
    license_destination.write_bytes(b"old license")

    args = make_args(
        release=release,
        manifest=manifest,
        destination=destination,
        resolved_manifest=resolved,
        license_destination=license_destination,
    )

    with pytest.raises(
        sync_tabler_icons.IconImportError,
        match="forbidden SVG element",
    ):
        sync_tabler_icons.import_icons(args)

    assert stale.read_bytes() == b"keep until validation succeeds"
    assert not (destination / "a-good.svg").exists()
    assert not (destination / "z-bad.svg").exists()
    assert resolved.read_bytes() == b"old resolved"
    assert license_destination.read_bytes() == b"old license"


def test_successful_import_writes_hashes_and_removes_stale_icons(
    tmp_path: Path,
) -> None:
    release, _ = make_release(
        tmp_path,
        {
            "first.svg": VALID_SVG,
            "second.svg": VALID_SVG.replace("M5 12h14", "M12 5v14"),
        },
    )
    manifest = tmp_path / "icon_manifest.json"
    write_manifest(
        manifest,
        {
            "test.first": "first.svg",
            "test.second": "second.svg",
            "test.first_alias": "first.svg",
        },
    )

    destination = tmp_path / "output"
    destination.mkdir()
    stale = destination / "stale.svg"
    stale.write_bytes(b"stale")

    resolved = tmp_path / "resolved.json"
    license_destination = tmp_path / "LICENSE.txt"

    args = make_args(
        release=release,
        manifest=manifest,
        destination=destination,
        resolved_manifest=resolved,
        license_destination=license_destination,
    )

    assert sync_tabler_icons.import_icons(args) == 0

    assert not stale.exists()
    assert (destination / "first.svg").is_file()
    assert (destination / "second.svg").is_file()
    assert license_destination.read_text(encoding="utf-8") == LICENSE_TEXT

    payload = json.loads(resolved.read_text(encoding="utf-8"))
    assert payload["package"] == "@tabler/icons"
    assert payload["version"] == "3.44.0"
    assert payload["upstream_tag"] == "v3.44.0"

    for semantic_name, item in payload["icons"].items():
        output = destination / item["file"]
        assert item["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
        assert semantic_name.startswith("test.")


def test_synchronization_is_idempotent(tmp_path: Path) -> None:
    release, _ = make_release(
        tmp_path,
        {"test.svg": VALID_SVG},
    )
    manifest = tmp_path / "icon_manifest.json"
    write_manifest(manifest, {"test.icon": "test.svg"})

    destination = tmp_path / "output"
    resolved = tmp_path / "resolved.json"
    license_destination = tmp_path / "LICENSE.txt"

    args = make_args(
        release=release,
        manifest=manifest,
        destination=destination,
        resolved_manifest=resolved,
        license_destination=license_destination,
    )

    assert sync_tabler_icons.import_icons(args) == 0

    first_snapshot = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }

    assert sync_tabler_icons.import_icons(args) == 0

    second_snapshot = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }

    assert second_snapshot == first_snapshot


def test_dry_run_does_not_modify_existing_outputs(tmp_path: Path) -> None:
    release, _ = make_release(
        tmp_path,
        {"test.svg": VALID_SVG},
    )
    manifest = tmp_path / "icon_manifest.json"
    write_manifest(manifest, {"test.icon": "test.svg"})

    destination = tmp_path / "output"
    destination.mkdir()
    stale = destination / "stale.svg"
    stale.write_bytes(b"stale")

    resolved = tmp_path / "resolved.json"
    resolved.write_bytes(b"old resolved")
    license_destination = tmp_path / "LICENSE.txt"
    license_destination.write_bytes(b"old license")

    args = make_args(
        release=release,
        manifest=manifest,
        destination=destination,
        resolved_manifest=resolved,
        license_destination=license_destination,
        dry_run=True,
    )

    assert sync_tabler_icons.import_icons(args) == 0
    assert stale.read_bytes() == b"stale"
    assert not (destination / "test.svg").exists()
    assert resolved.read_bytes() == b"old resolved"
    assert license_destination.read_bytes() == b"old license"


def test_commit_outputs_rolls_back_after_mid_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "a.svg"
    second = tmp_path / "resolved.json"
    stale = tmp_path / "stale.svg"

    first.write_bytes(b"old first")
    second.write_bytes(b"old resolved")
    stale.write_bytes(b"old stale")

    real_atomic_write = sync_tabler_icons.atomic_write
    failed_once = False

    def failing_atomic_write(path: Path, data: bytes) -> None:
        nonlocal failed_once
        if path.resolve() == second.resolve() and not failed_once:
            failed_once = True
            raise OSError("injected write failure")
        real_atomic_write(path, data)

    monkeypatch.setattr(
        sync_tabler_icons,
        "atomic_write",
        failing_atomic_write,
    )

    with pytest.raises(OSError, match="injected write failure"):
        sync_tabler_icons.commit_outputs(
            writes={
                first: b"new first",
                second: b"new resolved",
            },
            stale_paths=[stale],
        )

    assert first.read_bytes() == b"old first"
    assert second.read_bytes() == b"old resolved"
    assert stale.read_bytes() == b"old stale"
