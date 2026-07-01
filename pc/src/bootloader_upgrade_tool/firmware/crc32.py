"""CRC32/IEEE helpers for firmware reliability metadata."""

from __future__ import annotations

from collections.abc import Sequence
from zlib import crc32


def crc32_bytes(data: bytes | bytearray | memoryview) -> int:
    return crc32(data) & 0xFFFFFFFF


def crc32_words(words: Sequence[int]) -> int:
    data = bytearray()
    for word in words:
        if word < 0 or word > 0xFFFF:
            raise ValueError("CRC32 word input must fit uint16")
        data.append(word & 0xFF)
        data.append((word >> 8) & 0xFF)
    return crc32_bytes(data)
