"""Typed protocol payload models for DeviceInfo and ErrorDetail."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .constants import METADATA_SUMMARY_WORDS, SERVICE_STATUS_WORDS, WRITE_DATA_ALIGNMENT_WORDS


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
    revision_id: int = 0
    uid_unique: int = 0

    def __post_init__(self) -> None:
        for name in ("feature_flags", "revision_id", "uid_unique"):
            if not 0 <= getattr(self, name) <= 0xFFFFFFFF:
                raise ValueError(f"{name} must fit uint32")
        for name in (
            "device_id",
            "cpu_id",
            "kernel_ver_major",
            "kernel_ver_minor",
            "kernel_ver_patch",
            "protocol_ver",
            "max_payload_words",
            "max_data_words",
            "boot_mode",
            "kernel_layout",
        ):
            value = getattr(self, name)
            if value < 0 or value > 0xFFFF:
                raise ValueError(f"{name} must fit uint16")
        if self.max_data_words == 0 or self.max_data_words % WRITE_DATA_ALIGNMENT_WORDS:
            raise ValueError("max_data_words must be a positive multiple of 8")
        if self.max_data_words + 5 > self.max_payload_words:
            raise ValueError("max_data_words plus 5 metadata words must fit max_payload_words")

    @classmethod
    def from_words(cls, words: Sequence[int]) -> DeviceInfo:
        values = _check_words(words, 16, "DeviceInfo")
        return cls(
            *values[:6],
            join_u32(values[6], values[7]),
            *values[8:12],
            join_u32(values[12], values[13]),
            join_u32(values[14], values[15]),
        )

    def to_words(self) -> tuple[int, ...]:
        feature_low, feature_high = split_u32(self.feature_flags)
        revision_low, revision_high = split_u32(self.revision_id)
        uid_low, uid_high = split_u32(self.uid_unique)
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
            revision_low,
            revision_high,
            uid_low,
            uid_high,
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


@dataclass(frozen=True, slots=True)
class MetadataSummary:
    metadata_valid: int
    active_slot: int
    latest_record_type: int
    boot_attempt_count: int
    app_confirmed: int
    boot_attempt_limit: int
    app_version_major: int
    app_version_minor: int
    app_version_patch: int
    app_version_build: int
    entry_point: int
    image_crc32: int
    state: int
    valid_record_count: int
    invalid_record_count: int
    erased_record_count: int
    free_record_count: int
    next_record_index: int
    image_size_words: int
    target_device_id: int
    target_cpu_id: int

    @classmethod
    def from_words(cls, words: Sequence[int]) -> MetadataSummary:
        values = _check_words(words, METADATA_SUMMARY_WORDS, "MetadataSummary")
        return cls(
            *values[:9],
            join_u32(values[9], values[10]),
            join_u32(values[11], values[12]),
            join_u32(values[13], values[14]),
            *values[15:21],
            join_u32(values[21], values[22]),
            values[23],
            values[24],
        )


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    service_state: int
    abi_major: int
    abi_minor: int
    service_major: int
    service_minor: int
    capabilities: int
    last_attach_status: int
    loaded_image_crc32: int
    loaded_image_words: int

    @classmethod
    def from_words(cls, words: Sequence[int]) -> ServiceStatus:
        values = _check_words(words, SERVICE_STATUS_WORDS, "ServiceStatus")
        return cls(
            values[0],
            values[1],
            values[2],
            values[3],
            values[4],
            join_u32(values[5], values[6]),
            values[7],
            join_u32(values[8], values[9]),
            join_u32(values[10], values[11]),
        )
