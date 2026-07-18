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


@dataclass(frozen=True, slots=True)
class FlashSector:
    sector_id: str
    start: int
    end_exclusive: int
    bit_index: int

    def __post_init__(self) -> None:
        if type(self.sector_id) is not str or not self.sector_id:
            raise ValueError("sector_id must be a non-empty string")
        if type(self.start) is not int or self.start < 0:
            raise ValueError("start must be a non-negative integer")
        if type(self.end_exclusive) is not int or self.end_exclusive <= self.start:
            raise ValueError("end_exclusive must be an integer greater than start")
        if type(self.bit_index) is not int or self.bit_index < 0:
            raise ValueError("bit_index must be a non-negative integer")


@dataclass(frozen=True)
class FlashLayout:
    app_ranges: tuple[AddressRange, ...]
    allowed_erase_mask: int
    forbidden_erase_mask: int
    metadata_sector_mask: int
    sectors: tuple[FlashSector, ...] = ()

    def __post_init__(self) -> None:
        if type(self.sectors) is not tuple:
            raise TypeError("sectors must be a tuple")
        if any(type(sector) is not FlashSector for sector in self.sectors):
            raise TypeError("sectors must contain exact FlashSector values")
        if len({sector.sector_id for sector in self.sectors}) != len(self.sectors):
            raise ValueError("sector IDs must be unique")
        if len({sector.bit_index for sector in self.sectors}) != len(self.sectors):
            raise ValueError("sector bit indexes must be unique")
        ordered = sorted(self.sectors, key=lambda sector: sector.start)
        if any(left.end_exclusive > right.start for left, right in zip(ordered, ordered[1:])):
            raise ValueError("sector address ranges must not overlap")


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
