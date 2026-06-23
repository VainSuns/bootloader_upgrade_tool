"""Immutable firmware image models used by conversion and protocol layers."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class AddressRange:
    start: int
    end_exclusive: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end_exclusive <= self.start:
            raise ValueError("invalid address range")


@dataclass(frozen=True, slots=True)
class FirmwareBlock:
    address: int
    words: tuple[int, ...]

    def __init__(self, address: int, words: Sequence[int]) -> None:
        normalized = tuple(words)
        if address < 0 or address > 0xFFFFFFFF:
            raise ValueError("block address must fit uint32")
        if not normalized:
            raise ValueError("firmware block must contain data")
        if any(word < 0 or word > 0xFFFF for word in normalized):
            raise ValueError("firmware data words must fit uint16")
        object.__setattr__(self, "address", address)
        object.__setattr__(self, "words", normalized)

    @property
    def end_exclusive(self) -> int:
        return self.address + len(self.words)


@dataclass(frozen=True, slots=True)
class FirmwareImage:
    source_out_file: str
    generated_hex_file: str
    entry_point: int
    blocks: tuple[FirmwareBlock, ...]
    total_words: int
    address_ranges: tuple[AddressRange, ...]
    file_checksum: str
    format_info: Mapping[str, object]

    def __init__(
        self,
        *,
        source_out_file: str,
        generated_hex_file: str,
        entry_point: int,
        blocks: Sequence[FirmwareBlock],
        file_checksum: str,
        format_info: Mapping[str, object],
    ) -> None:
        normalized = tuple(blocks)
        if entry_point < 0 or entry_point > 0xFFFFFFFF:
            raise ValueError("entry point must fit uint32")
        if not normalized:
            raise ValueError("firmware image must contain at least one block")
        ranges = tuple(AddressRange(block.address, block.end_exclusive) for block in normalized)
        sorted_ranges = sorted(ranges, key=lambda item: item.start)
        if any(left.end_exclusive > right.start for left, right in zip(sorted_ranges, sorted_ranges[1:])):
            raise ValueError("firmware blocks overlap")
        object.__setattr__(self, "source_out_file", source_out_file)
        object.__setattr__(self, "generated_hex_file", generated_hex_file)
        object.__setattr__(self, "entry_point", entry_point)
        object.__setattr__(self, "blocks", normalized)
        object.__setattr__(self, "total_words", sum(len(block.words) for block in normalized))
        object.__setattr__(self, "address_ranges", ranges)
        object.__setattr__(self, "file_checksum", file_checksum)
        object.__setattr__(self, "format_info", MappingProxyType(dict(format_info)))

