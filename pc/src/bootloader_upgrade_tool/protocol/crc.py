"""CRC-16/CCITT-FALSE over bytes or little-endian 16-bit words."""

from collections.abc import Iterable


def crc16_ccitt_false(data: bytes | bytearray | memoryview) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def words_to_little_endian_bytes(words: Iterable[int]) -> bytes:
    result = bytearray()
    for word in words:
        if word < 0 or word > 0xFFFF:
            raise ValueError(f"word does not fit uint16: {word}")
        result.extend((word & 0xFF, word >> 8))
    return bytes(result)


def crc16_words(words: Iterable[int]) -> int:
    return crc16_ccitt_false(words_to_little_endian_bytes(words))

