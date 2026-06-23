"""Encode and decode complete protocol frames without transport dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .constants import HEADER_WORDS, MAGIC0, MAGIC1, PROTOCOL_VERSION
from .crc import crc16_words, words_to_little_endian_bytes


class FrameError(ValueError):
    pass


class FrameLengthError(FrameError):
    pass


class HeaderCrcError(FrameError):
    pass


class PayloadCrcError(FrameError):
    pass


def _word(value: int, field: str) -> int:
    if value < 0 or value > 0xFFFF:
        raise ValueError(f"{field} must fit uint16")
    return value


@dataclass(frozen=True, slots=True)
class Frame:
    packet_type: int
    command: int
    sequence: int
    payload: tuple[int, ...] = ()
    flags: int = 0
    status: int = 0
    protocol_version: int = PROTOCOL_VERSION

    def __init__(
        self,
        packet_type: int,
        command: int,
        sequence: int,
        payload: Sequence[int] = (),
        *,
        flags: int = 0,
        status: int = 0,
        protocol_version: int = PROTOCOL_VERSION,
    ) -> None:
        normalized = tuple(payload)
        for name, value in (
            ("packet_type", packet_type),
            ("command", command),
            ("sequence", sequence),
            ("flags", flags),
            ("status", status),
            ("protocol_version", protocol_version),
        ):
            _word(int(value), name)
        if sequence == 0:
            raise ValueError("sequence 0 is reserved")
        if len(normalized) > 0xFFFF:
            raise ValueError("payload is too large for frame header")
        for value in normalized:
            _word(value, "payload word")
        object.__setattr__(self, "packet_type", int(packet_type))
        object.__setattr__(self, "command", int(command))
        object.__setattr__(self, "sequence", int(sequence))
        object.__setattr__(self, "payload", normalized)
        object.__setattr__(self, "flags", int(flags))
        object.__setattr__(self, "status", int(status))
        object.__setattr__(self, "protocol_version", int(protocol_version))

    def encode_words(self) -> tuple[int, ...]:
        header_without_crc = (
            MAGIC0,
            MAGIC1,
            self.protocol_version,
            self.packet_type,
            self.command,
            self.sequence,
            self.flags,
            self.status,
            len(self.payload),
        )
        return (
            *header_without_crc,
            crc16_words(header_without_crc),
            *self.payload,
            crc16_words(self.payload),
        )

    def encode_bytes(self) -> bytes:
        return words_to_little_endian_bytes(self.encode_words())


def decode_frame(words: Sequence[int], *, max_payload_words: int = 0xFFFF) -> Frame:
    values = tuple(words)
    if len(values) < HEADER_WORDS + 1:
        raise FrameLengthError("frame is shorter than header plus payload CRC")
    if values[0:2] != (MAGIC0, MAGIC1):
        raise FrameError("bad frame magic")
    if crc16_words(values[:9]) != values[9]:
        raise HeaderCrcError("header CRC mismatch")
    payload_words = values[8]
    if payload_words > max_payload_words:
        raise FrameLengthError("payload exceeds configured maximum")
    expected_words = HEADER_WORDS + payload_words + 1
    if len(values) != expected_words:
        raise FrameLengthError(f"frame has {len(values)} words; expected {expected_words}")
    payload = values[HEADER_WORDS:-1]
    if crc16_words(payload) != values[-1]:
        raise PayloadCrcError("payload CRC mismatch")
    try:
        return Frame(
            values[3],
            values[4],
            values[5],
            payload,
            flags=values[6],
            status=values[7],
            protocol_version=values[2],
        )
    except ValueError as exc:
        raise FrameError(str(exc)) from exc

