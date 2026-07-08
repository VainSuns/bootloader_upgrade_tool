"""Target memory maps in C28x word addresses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AddressRange:
    start: int
    end_exclusive: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end_exclusive <= self.start:
            raise ValueError("invalid address range")

    def contains(self, address: int) -> bool:
        return self.start <= address < self.end_exclusive

    def contains_range(self, start: int, word_count: int) -> bool:
        return word_count > 0 and self.start <= start and start + word_count <= self.end_exclusive


@dataclass(frozen=True)
class FlashLayout:
    app_ranges: tuple[AddressRange, ...]
    allowed_erase_mask: int
    forbidden_erase_mask: int
    metadata_sector_mask: int


@dataclass(frozen=True)
class RamLayout:
    service_ranges: tuple[AddressRange, ...]
    ram_app_ranges: tuple[AddressRange, ...]
    reserved_ranges: tuple[AddressRange, ...]


@dataclass(frozen=True)
class MetadataLayout:
    range: AddressRange
    sector_mask: int
    record_alignment_words: int


@dataclass(frozen=True)
class TargetMemoryMap:
    flash: FlashLayout | None = None
    ram: RamLayout | None = None
    metadata: MetadataLayout | None = None
