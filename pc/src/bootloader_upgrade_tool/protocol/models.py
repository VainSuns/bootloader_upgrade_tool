"""Typed protocol payload models for DeviceInfo and ErrorDetail."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Sequence

from .constants import WRITE_DATA_ALIGNMENT_WORDS


def join_u32(low: int, high: int) -> int:
    return low | (high << 16)


def split_u32(value: int) -> tuple[int, int]:
    if value < 0 or value > 0xFFFFFFFF:
        raise ValueError("value must fit uint32")
    return value & 0xFFFF, value >> 16


def _check_words(words: Sequence[int], expected: int, name: str) -> tuple[int, ...]:
    result = tuple(words)
    if len(result) != expected:
        raise ValueError(f"{name} requires exactly {expected} words")
    if any(word < 0 or word > 0xFFFF for word in result):
        raise ValueError(f"{name} values must fit uint16")
    return result


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    device_id: int
    cpu_id: int
    kernel_ver_major: int
    kernel_ver_minor: int
    kernel_ver_patch: int
    protocol_ver: int
    feature_flags: int
    max_payload_words: int
    max_data_words: int
    boot_mode: int
    kernel_layout: int
    reserved0: int = 0
    reserved1: int = 0
    reserved2: int = 0
    reserved3: int = 0

    def __post_init__(self) -> None:
        if self.feature_flags < 0 or self.feature_flags > 0xFFFFFFFF:
            raise ValueError("feature_flags must fit uint32")
        scalar_names = [field.name for field in fields(self) if field.name != "feature_flags"]
        for name in scalar_names:
            value = getattr(self, name)
            if value < 0 or value > 0xFFFF:
                raise ValueError(f"{name} must fit uint16")
        if self.max_data_words == 0 or self.max_data_words % WRITE_DATA_ALIGNMENT_WORDS:
            raise ValueError("max_data_words must be a positive multiple of 8")
        if self.max_data_words > self.max_payload_words:
            raise ValueError("max_data_words must not exceed max_payload_words")

    @classmethod
    def from_words(cls, words: Sequence[int]) -> DeviceInfo:
        values = _check_words(words, 16, "DeviceInfo")
        return cls(
            *values[:6],
            join_u32(values[6], values[7]),
            *values[8:],
        )

    def to_words(self) -> tuple[int, ...]:
        feature_low, feature_high = split_u32(self.feature_flags)
        return (
            self.device_id,
            self.cpu_id,
            self.kernel_ver_major,
            self.kernel_ver_minor,
            self.kernel_ver_patch,
            self.protocol_ver,
            feature_low,
            feature_high,
            self.max_payload_words,
            self.max_data_words,
            self.boot_mode,
            self.kernel_layout,
            self.reserved0,
            self.reserved1,
            self.reserved2,
            self.reserved3,
        )


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    operation: int
    stage: int
    address: int
    length_words: int
    api_status: int
    fsm_status: int
    extra0: int
    extra1: int

    def __post_init__(self) -> None:
        for name in ("operation", "stage", "api_status", "extra0", "extra1"):
            value = getattr(self, name)
            if value < 0 or value > 0xFFFF:
                raise ValueError(f"{name} must fit uint16")
        for name in ("address", "length_words", "fsm_status"):
            value = getattr(self, name)
            if value < 0 or value > 0xFFFFFFFF:
                raise ValueError(f"{name} must fit uint32")

    @classmethod
    def from_words(cls, words: Sequence[int]) -> ErrorDetail:
        values = _check_words(words, 11, "ErrorDetail")
        return cls(
            values[0],
            values[1],
            join_u32(values[2], values[3]),
            join_u32(values[4], values[5]),
            values[6],
            join_u32(values[7], values[8]),
            values[9],
            values[10],
        )

    def to_words(self) -> tuple[int, ...]:
        address_low, address_high = split_u32(self.address)
        length_low, length_high = split_u32(self.length_words)
        fsm_low, fsm_high = split_u32(self.fsm_status)
        return (
            self.operation,
            self.stage,
            address_low,
            address_high,
            length_low,
            length_high,
            self.api_status,
            fsm_low,
            fsm_high,
            self.extra0,
            self.extra1,
        )

