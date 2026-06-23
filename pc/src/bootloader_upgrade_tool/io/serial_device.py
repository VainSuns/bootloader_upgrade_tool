"""SCI/RS232 IO Device; pySerial is contained entirely in this adapter."""

from __future__ import annotations

import importlib
import time
from typing import Any, Callable

from .base import (
    IoDeviceError,
    IoDeviceNotOpenError,
    IoTimeoutError,
    PcIoDevice,
    validate_timeout,
    validate_word,
)


SerialFactory = Callable[..., Any]


class SerialIoDevice(PcIoDevice):
    def __init__(
        self,
        port: str,
        *,
        baudrate: int = 115200,
        serial_factory: SerialFactory | None = None,
        autobaud_interval_ms: int = 50,
    ) -> None:
        if not port:
            raise ValueError("serial port must not be empty")
        if baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if autobaud_interval_ms <= 0:
            raise ValueError("autobaud_interval_ms must be positive")
        self.port = port
        self.baudrate = baudrate
        self._serial_factory = serial_factory
        self.autobaud_interval_ms = autobaud_interval_ms
        self._serial: Any | None = None

    def _default_factory(self) -> SerialFactory:
        try:
            module = importlib.import_module("serial")
        except ImportError as exc:
            raise IoDeviceError("SerialIoDevice requires the pyserial package") from exc
        return module.Serial

    def open(self) -> None:
        if self._serial is not None:
            return
        factory = self._serial_factory or self._default_factory()
        try:
            self._serial = factory(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=0,
                write_timeout=1,
            )
        except Exception as exc:
            raise IoDeviceError(f"failed to open serial port {self.port}: {exc}") from exc

    def _require_open(self) -> Any:
        if self._serial is None:
            raise IoDeviceNotOpenError("serial device is not open")
        return self._serial

    @staticmethod
    def _set_timeout(serial_port: Any, timeout_seconds: float) -> None:
        try:
            serial_port.timeout = max(0.0, timeout_seconds)
        except Exception:
            pass

    def wait_slave(self, timeout_ms: int) -> None:
        serial_port = self._require_open()
        timeout_seconds = validate_timeout(timeout_ms)
        deadline = time.monotonic() + timeout_seconds
        interval = self.autobaud_interval_ms / 1000.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IoTimeoutError("SCI autobaud handshake timed out")
            try:
                serial_port.write(b"A")
                if hasattr(serial_port, "flush"):
                    serial_port.flush()
                self._set_timeout(serial_port, min(interval, remaining))
                if serial_port.read(1) == b"A":
                    return
            except IoTimeoutError:
                raise
            except Exception as exc:
                raise IoDeviceError(f"SCI autobaud handshake failed: {exc}") from exc

    def read_word(self, timeout_ms: int) -> int:
        serial_port = self._require_open()
        deadline = time.monotonic() + validate_timeout(timeout_ms)
        data = bytearray()
        while len(data) < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise IoTimeoutError("serial word read timed out")
            self._set_timeout(serial_port, remaining)
            try:
                chunk = serial_port.read(2 - len(data))
            except Exception as exc:
                raise IoDeviceError(f"serial read failed: {exc}") from exc
            if chunk:
                data.extend(chunk)
        return data[0] | (data[1] << 8)

    def write_word(self, word: int) -> None:
        serial_port = self._require_open()
        value = validate_word(word)
        try:
            written = serial_port.write(bytes((value & 0xFF, value >> 8)))
            if written is not None and written != 2:
                raise IoDeviceError(f"serial write accepted {written} of 2 bytes")
        except IoDeviceError:
            raise
        except Exception as exc:
            raise IoDeviceError(f"serial write failed: {exc}") from exc

    def close(self) -> None:
        serial_port, self._serial = self._serial, None
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception as exc:
                raise IoDeviceError(f"failed to close serial port: {exc}") from exc
