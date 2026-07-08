"""pySerial byte transport with SCI autobaud in open()."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import time
from typing import Any, Callable

from .base import ByteTransport, TransportClosedError, TransportError, TransportTimeoutError


SerialFactory = Callable[..., Any]

_AUTOBAUD_INTERVAL_MS = 50
_POST_AUTOBAUD_DELAY_MS = 100
_OPEN_SETTLE_MS = 500


@dataclass(frozen=True)
class SerialTransportConfig:
    port: str
    baudrate: int = 9600
    tx_timeout_ms: int = 1000
    rx_timeout_ms: int = 1000
    autobaud_timeout_ms: int = 5000


class SerialTransport(ByteTransport):
    def __init__(
        self,
        config: SerialTransportConfig,
        serial_factory: SerialFactory | None = None,
    ) -> None:
        if not config.port:
            raise ValueError("serial port must not be empty")
        if config.baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if min(config.tx_timeout_ms, config.rx_timeout_ms, config.autobaud_timeout_ms) <= 0:
            raise ValueError("timeouts must be positive")
        self.config = config
        self._serial_factory = serial_factory
        self._serial: Any | None = None

    def _default_factory(self) -> SerialFactory:
        try:
            return importlib.import_module("serial").Serial
        except ImportError as exc:
            raise TransportError("SerialTransport requires the pyserial package") from exc

    def open(self) -> None:
        if self._serial is not None:
            return
        factory = self._serial_factory or self._default_factory()
        try:
            self._serial = factory(
                port=self.config.port,
                baudrate=self.config.baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=self.config.rx_timeout_ms / 1000.0,
                write_timeout=self.config.tx_timeout_ms / 1000.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            self._serial.dtr = False
            self._serial.rts = False
            time.sleep(_OPEN_SETTLE_MS / 1000.0)
            self._autobaud()
        except Exception:
            serial_port, self._serial = self._serial, None
            if serial_port is not None:
                try:
                    serial_port.close()
                except Exception:
                    pass
            raise

    def _require_open(self) -> Any:
        if self._serial is None:
            raise TransportClosedError("serial transport is not open")
        return self._serial

    @staticmethod
    def _set_timeout(serial_port: Any, timeout_seconds: float) -> None:
        try:
            serial_port.timeout = max(0.0, timeout_seconds)
        except Exception:
            pass

    def _autobaud(self) -> None:
        serial_port = self._require_open()
        deadline = time.monotonic() + self.config.autobaud_timeout_ms / 1000.0
        interval = _AUTOBAUD_INTERVAL_MS / 1000.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportTimeoutError("SCI autobaud handshake timed out")
            try:
                serial_port.write(b"A")
                if hasattr(serial_port, "flush"):
                    serial_port.flush()
                self._set_timeout(serial_port, min(interval, remaining))
                if serial_port.read(1) == b"A":
                    time.sleep(_POST_AUTOBAUD_DELAY_MS / 1000.0)
                    return
            except TransportTimeoutError:
                raise
            except Exception as exc:
                raise TransportError(f"SCI autobaud handshake failed: {exc}") from exc

    def close(self) -> None:
        serial_port, self._serial = self._serial, None
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception as exc:
                raise TransportError(f"failed to close serial port: {exc}") from exc

    def write_all(self, data: bytes) -> None:
        serial_port = self._require_open()
        try:
            written = serial_port.write(data)
            if hasattr(serial_port, "flush"):
                serial_port.flush()
        except Exception as exc:
            raise TransportError(f"serial write failed: {exc}") from exc
        written = len(data) if written is None else written
        if written != len(data):
            raise TransportError(f"serial write accepted {written} of {len(data)} bytes")

    def read_some(self, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        try:
            return bytes(self._require_open().read(max_bytes))
        except Exception as exc:
            raise TransportError(f"serial read failed: {exc}") from exc
