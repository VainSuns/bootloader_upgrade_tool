"""Transport-neutral PC IO Device contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType


class IoDeviceError(RuntimeError):
    pass


class IoTimeoutError(IoDeviceError, TimeoutError):
    """Local IO timeout; it is deliberately not a DSP protocol status."""


class IoDeviceNotOpenError(IoDeviceError):
    pass


class PcIoDevice(ABC):
    """Word-oriented device boundary used by all PC-side flows."""

    @abstractmethod
    def open(self) -> None:
        pass

    @abstractmethod
    def wait_slave(self, timeout_ms: int) -> None:
        pass

    @abstractmethod
    def read_word(self, timeout_ms: int) -> int:
        pass

    @abstractmethod
    def write_word(self, word: int) -> None:
        pass

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

