"""Response frame reader for byte-stream transports."""

from __future__ import annotations

import time

from ..transport.base import ByteTransport, TransportTimeoutError
from .crc import crc16_words
from .frame import Frame, FrameError, decode_frame


class FrameReader:
    def __init__(self, transport: ByteTransport) -> None:
        self.transport = transport
        self._buffer = bytearray()

    def read_frame(
        self,
        *,
        timeout_ms: int = 1000,
        max_payload_words: int = 0xFFFF,
    ) -> Frame:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        magic = b"\x5A\xA5\xA5\x5A"
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            if time.monotonic() >= deadline:
                raise TransportTimeoutError("response byte read timed out")
            chunk = self.transport.read_some(4096)
            if not chunk:
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
                continue
            self._buffer.extend(chunk)

            while True:
                start = self._buffer.find(magic)
                if start < 0:
                    if len(self._buffer) > 3:
                        del self._buffer[:-3]
                    break
                if start:
                    del self._buffer[:start]
                if len(self._buffer) < 20:
                    break
                header = tuple(
                    self._buffer[index] | (self._buffer[index + 1] << 8)
                    for index in range(0, 20, 2)
                )
                if crc16_words(header[:9]) != header[9]:
                    del self._buffer[0]
                    continue
                if header[8] > max_payload_words:
                    raise FrameError("response payload exceeds configured maximum")
                frame_size = (10 + header[8] + 1) * 2
                if len(self._buffer) < frame_size:
                    break
                frame_bytes = bytes(self._buffer[:frame_size])
                del self._buffer[:frame_size]
                words = tuple(
                    frame_bytes[index] | (frame_bytes[index + 1] << 8)
                    for index in range(0, frame_size, 2)
                )
                return decode_frame(words, max_payload_words=max_payload_words)
