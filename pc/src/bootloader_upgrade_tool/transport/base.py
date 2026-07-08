"""Transport contracts for byte-stream protocol clients."""

from __future__ import annotations

from typing import Protocol


class TransportError(RuntimeError):
    pass


class TransportTimeoutError(TransportError):
    pass


class TransportClosedError(TransportError):
    pass


class ByteTransport(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def write_all(self, data: bytes) -> None: ...
    def read_some(self, max_bytes: int) -> bytes: ...
