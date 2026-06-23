"""Parse TI linker ``MEMORY`` declarations and generate device information."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence


class MemoryParseError(ValueError):
    """Raised when a linker MEMORY declaration cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class MemoryRegion:
    """One linker MEMORY region, expressed in 16-bit word addresses."""

    name: str
    origin: int
    length: int
    page: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("memory region name must not be empty")
        if self.origin < 0:
            raise ValueError("memory region origin must be non-negative")
        if self.length <= 0:
            raise ValueError("memory region length must be positive")

    @property
    def end_exclusive(self) -> int:
        return self.origin + self.length


_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\r\n]*", re.DOTALL)
_MEMORY_RE = re.compile(r"\bMEMORY\b", re.IGNORECASE)
_PAGE_RE = re.compile(r"^\s*PAGE\s+(?P<page>\d+)\s*:\s*", re.IGNORECASE)
_ENTRY_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_$][\w$]*)\s*(?:\([^)]*\))?\s*:\s*(?P<body>.*)$"
)
_ASSIGNMENT_RE = re.compile(
    r"\b(?P<key>origin|org|o|length|len|l)\b\s*=\s*"
    r"(?P<value>0[xX][0-9A-Fa-f]+|\d+)",
    re.IGNORECASE,
)


def _memory_body(text: str) -> str:
    match = _MEMORY_RE.search(text)
    if match is None:
        raise MemoryParseError("linker command file has no MEMORY block")

    opening = text.find("{", match.end())
    if opening < 0:
        raise MemoryParseError("MEMORY block has no opening brace")

    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise MemoryParseError("MEMORY block has no closing brace")


def _parse_int(value: str) -> int:
    return int(value, 0)


def parse_memory_text(text: str) -> tuple[MemoryRegion, ...]:
    """Parse the first TI linker ``MEMORY`` block in source order.

    The first implementation intentionally accepts only literal decimal or
    hexadecimal ``origin`` and ``length`` values. Expressions and symbols are
    rejected instead of being evaluated implicitly.
    """

    body = _memory_body(_COMMENT_RE.sub("", text))
    page: int | None = None
    regions: list[MemoryRegion] = []
    pending = ""

    def consume(declaration: str, current_page: int | None) -> None:
        match = _ENTRY_RE.match(declaration)
        if match is None:
            raise MemoryParseError(f"invalid MEMORY declaration: {declaration.strip()!r}")
        assignments = {
            assignment.group("key").lower(): _parse_int(assignment.group("value"))
            for assignment in _ASSIGNMENT_RE.finditer(match.group("body"))
        }
        origin = next((assignments[key] for key in ("origin", "org", "o") if key in assignments), None)
        length = next((assignments[key] for key in ("length", "len", "l") if key in assignments), None)
        if origin is None or length is None:
            raise MemoryParseError(
                f"MEMORY region {match.group('name')!r} requires literal origin and length"
            )
        regions.append(MemoryRegion(match.group("name"), origin, length, current_page))

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        page_match = _PAGE_RE.match(line)
        if page_match:
            if pending:
                consume(pending, page)
                pending = ""
            page = int(page_match.group("page"))
            line = line[page_match.end() :].strip()
            if not line:
                continue

        if _ENTRY_RE.match(line):
            if pending:
                consume(pending, page)
            pending = line
        elif pending:
            pending = f"{pending} {line}"
        else:
            raise MemoryParseError(f"unexpected content in MEMORY block: {line!r}")

    if pending:
        consume(pending, page)
    if not regions:
        raise MemoryParseError("MEMORY block contains no regions")

    names: set[str] = set()
    for region in regions:
        folded = region.name.casefold()
        if folded in names:
            raise MemoryParseError(f"duplicate MEMORY region name: {region.name}")
        names.add(folded)
    return tuple(regions)


def parse_memory_file(path: str | Path) -> tuple[MemoryRegion, ...]:
    return parse_memory_text(Path(path).read_text(encoding="utf-8"))


def _hex(value: int) -> str:
    return f"0x{value:06X}"


def _region_dict(region: MemoryRegion) -> dict[str, object]:
    result: dict[str, object] = {
        "name": region.name,
        "origin": _hex(region.origin),
        "length": _hex(region.length),
    }
    if region.page is not None:
        result["page"] = region.page
    return result


def _contiguous_ranges(regions: Sequence[MemoryRegion]) -> list[dict[str, str]]:
    if not regions:
        return []
    ordered = sorted(regions, key=lambda region: region.origin)
    ranges: list[tuple[int, int]] = []
    start = ordered[0].origin
    end = ordered[0].end_exclusive
    for region in ordered[1:]:
        if region.origin < end:
            raise ValueError("selected Flash MEMORY regions overlap")
        if region.origin == end:
            end = region.end_exclusive
        else:
            ranges.append((start, end))
            start, end = region.origin, region.end_exclusive
    ranges.append((start, end))
    return [
        {
            "name": "APP_FLASH" if len(ranges) == 1 else f"APP_FLASH_{index + 1}",
            "start": _hex(range_start),
            "end": _hex(range_end - 1),
        }
        for index, (range_start, range_end) in enumerate(ranges)
    ]


def build_device_info(
    regions: Iterable[MemoryRegion],
    *,
    device: str = "F28377D",
    cpu: str = "CPU1",
    flash_region_names: Sequence[str] | None = None,
) -> dict[str, object]:
    """Build the documented MVP device-info object.

    When ``flash_region_names`` is omitted, regions whose names start with
    ``FLASH`` are selected in linker source order. Callers may provide an
    explicit ordered list when project naming differs or sector-mask ordering
    must be pinned independently of the linker file.
    """

    memory_regions = tuple(regions)
    if cpu.upper() != "CPU1":
        raise ValueError("MVP supports CPU1 device information only")

    by_name = {region.name.casefold(): region for region in memory_regions}
    if flash_region_names is None:
        flash_regions = tuple(
            region for region in memory_regions if region.name.upper().startswith("FLASH")
        )
    else:
        missing = [name for name in flash_region_names if name.casefold() not in by_name]
        if missing:
            raise ValueError(f"unknown flash MEMORY regions: {', '.join(missing)}")
        flash_regions = tuple(by_name[name.casefold()] for name in flash_region_names)
    if not flash_regions:
        raise ValueError("no Flash sectors selected")

    allowed_ranges = _contiguous_ranges(flash_regions)
    entry_ranges = [
        {"start": item["start"], "end": item["end"]} for item in allowed_ranges
    ]
    return {
        "device": device,
        "cpu": cpu.upper(),
        "memory_regions": [_region_dict(region) for region in memory_regions],
        "flash_sectors": [_region_dict(region) for region in flash_regions],
        "allowed_address_ranges": allowed_ranges,
        "default_erase_region": "sector_mask",
        "entry_point_range": entry_ranges,
    }


def write_device_info(path: str | Path, device_info: Mapping[str, object]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(device_info, indent=2) + "\n", encoding="utf-8")
    return output

