"""Bounded word-stream frame reader with magic-pair resynchronization."""

from __future__ import annotations

from collections.abc import Iterable

from .constants import HEADER_WORDS, MAGIC0, MAGIC1
from .crc import crc16_words
from .frame import Frame, FrameError, PayloadCrcError, decode_frame


class ResyncReader:
    """Incrementally extract frames while discarding malformed candidates."""

    def __init__(self, max_payload_words: int) -> None:
        if max_payload_words < 0 or max_payload_words > 0xFFFF:
            raise ValueError("max_payload_words must fit uint16")
        self.max_payload_words = max_payload_words
        self._buffer: list[int] = []
        self.errors: list[FrameError] = []

    def feed(self, words: int | Iterable[int]) -> list[Frame]:
        incoming = (words,) if isinstance(words, int) else words
        for word in incoming:
            if word < 0 or word > 0xFFFF:
                raise ValueError("stream words must fit uint16")
            self._buffer.append(word)
        return self._extract()

    def _seek_magic(self) -> bool:
        for index in range(len(self._buffer) - 1):
            if self._buffer[index : index + 2] == [MAGIC0, MAGIC1]:
                del self._buffer[:index]
                return True
        if self._buffer and self._buffer[-1] == MAGIC0:
            self._buffer[:] = [MAGIC0]
        else:
            self._buffer.clear()
        return False

    def _extract(self) -> list[Frame]:
        frames: list[Frame] = []
        while self._seek_magic():
            if len(self._buffer) < HEADER_WORDS:
                break
            if crc16_words(self._buffer[:9]) != self._buffer[9]:
                self.errors.append(FrameError("header CRC mismatch during resync"))
                del self._buffer[0]
                continue
            payload_words = self._buffer[8]
            if payload_words > self.max_payload_words:
                self.errors.append(FrameError("payload exceeds configured maximum during resync"))
                del self._buffer[0]
                continue
            total_words = HEADER_WORDS + payload_words + 1
            if len(self._buffer) < total_words:
                break
            candidate = self._buffer[:total_words]
            del self._buffer[:total_words]
            try:
                frames.append(decode_frame(candidate, max_payload_words=self.max_payload_words))
            except PayloadCrcError as exc:
                self.errors.append(exc)
            except FrameError as exc:
                self.errors.append(exc)
        return frames

