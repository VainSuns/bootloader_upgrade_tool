"""SCI/RS232 IO Device; pySerial is contained entirely in this adapter."""

from __future__ import annotations

import importlib
from threading import Event
import time
from typing import Any, Callable

from .base import (
    IoDeviceError,
    IoCancelledError,
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
        post_autobaud_delay_ms: int = 100,
    ) -> None:
        if not port:
            raise ValueError("serial port must not be empty")
        if baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if autobaud_interval_ms <= 0:
            raise ValueError("autobaud_interval_ms must be positive")
        if post_autobaud_delay_ms < 0:
            raise ValueError("post_autobaud_delay_ms must be non-negative")
        self.port = port
        self.baudrate = baudrate
        self._serial_factory = serial_factory
        self.autobaud_interval_ms = autobaud_interval_ms
        self.post_autobaud_delay_ms = post_autobaud_delay_ms
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
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            self._serial.dtr = False
            self._serial.rts = False
            time.sleep(0.5)
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

    def wait_slave(
        self, timeout_ms: int | None, cancel_event: Event | None = None
    ) -> None:
        serial_port = self._require_open()
        deadline = (
            None if timeout_ms is None else time.monotonic() + validate_timeout(timeout_ms)
        )
        interval = self.autobaud_interval_ms / 1000.0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise IoCancelledError("SCI autobaud handshake cancelled")
            remaining = interval if deadline is None else deadline - time.monotonic()
            if deadline is not None and remaining <= 0:
                raise IoTimeoutError("SCI autobaud handshake timed out")
            try:
                serial_port.write(b"A")
                if hasattr(serial_port, "flush"):
                    serial_port.flush()
                self._set_timeout(serial_port, min(interval, remaining))
                if serial_port.read(1) == b"A":
                    time.sleep(self.post_autobaud_delay_ms / 1000.0)
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

    def read_byte(self, timeout_ms: int) -> int:
        serial_port = self._require_open()
        self._set_timeout(serial_port, validate_timeout(timeout_ms))
        try:
            data = serial_port.read(1)
        except Exception as exc:
            raise IoDeviceError(f"serial byte read failed: {exc}") from exc
        if not data:
            raise IoTimeoutError("serial byte read timed out")
        return data[0]

    def read_available(self) -> bytes:
        serial_port = self._require_open()
        pending = getattr(serial_port, "in_waiting", 0) or 0
        if pending <= 0:
            return b""
        try:
            return bytes(serial_port.read(pending))
        except Exception as exc:
            raise IoDeviceError(f"serial read failed: {exc}") from exc

    def clear_input(self) -> None:
        serial_port = self._require_open()
        try:
            serial_port.reset_input_buffer()
        except Exception as exc:
            raise IoDeviceError(f"failed to clear serial buffers: {exc}") from exc

    def write_word(self, word: int) -> None:
        value = validate_word(word)
        self.write_bytes(bytes((value & 0xFF, value >> 8)))

    def write_bytes(self, data: bytes) -> int:
        serial_port = self._require_open()
        try:
            written = serial_port.write(data)
            if hasattr(serial_port, "flush"):
                serial_port.flush()
        except IoDeviceError:
            raise
        except Exception as exc:
            raise IoDeviceError(f"serial byte write failed: {exc}") from exc
        written = len(data) if written is None else written
        if written != len(data):
            raise IoDeviceError(f"serial write accepted {written} of {len(data)} bytes")
        return written

    def input_bytes_pending(self) -> int | None:
        pending = getattr(self._require_open(), "in_waiting", None)
        return int(pending) if pending is not None else None

    def close(self) -> None:
        serial_port, self._serial = self._serial, None
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception as exc:
                raise IoDeviceError(f"failed to close serial port: {exc}") from exc
