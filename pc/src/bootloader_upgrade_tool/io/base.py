"""Transport-neutral PC IO Device contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Event
from types import TracebackType


class IoDeviceError(RuntimeError):
    pass


class IoTimeoutError(IoDeviceError, TimeoutError):
    """Local IO timeout; it is deliberately not a DSP protocol status."""


class IoDeviceNotOpenError(IoDeviceError):
    pass


class IoCancelledError(IoDeviceError):
    pass


class PcIoDevice(ABC):
    """Word-oriented device boundary used by all PC-side flows."""

    @abstractmethod
    def open(self) -> None:
        pass

    @abstractmethod
    def wait_slave(
        self, timeout_ms: int | None, cancel_event: Event | None = None
    ) -> None:
        pass

    @abstractmethod
    def clear_input(self) -> None:
        pass

    @abstractmethod
    def read_word(self, timeout_ms: int) -> int:
        pass

    @abstractmethod
    def write_word(self, word: int) -> None:
        pass

    def read_byte(self, timeout_ms: int) -> int:
        raise IoDeviceError("byte reads are not supported by this IO Device")

    def read_available(self) -> bytes:
        return b""

    def write_bytes(self, data: bytes) -> int:
        if len(data) % 2:
            raise ValueError("word-stream byte writes must contain complete words")
        for index in range(0, len(data), 2):
            self.write_word(data[index] | (data[index + 1] << 8))
        return len(data)

    def input_bytes_pending(self) -> int | None:
        return None

    @abstractmethod
    def close(self) -> None:
        pass

    def __enter__(self) -> PcIoDevice:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def validate_timeout(timeout_ms: int) -> float:
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    return timeout_ms / 1000.0


def validate_word(word: int) -> int:
    if word < 0 or word > 0xFFFF:
        raise ValueError("word must fit uint16")
    return word
