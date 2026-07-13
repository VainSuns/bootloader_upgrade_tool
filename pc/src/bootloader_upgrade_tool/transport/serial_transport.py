"""pySerial byte transport with SCI autobaud in open()."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import time
from typing import Any, Callable

from ..cancellation import CancellationToken, cancellation_requested
from .base import (
    ByteTransport,
    TransportClosedError,
    TransportError,
    TransportOpenResult,
    TransportOpenStatus,
    TransportTimeoutError,
)


SerialFactory = Callable[..., Any]

_AUTOBAUD_INTERVAL_MS = 50
_POST_AUTOBAUD_DELAY_MS = 100
_OPEN_SETTLE_MS = 500
_CANCELLATION_POLL_MS = 25


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

    def open(
        self,
        cancellation: CancellationToken | None = None,
    ) -> TransportOpenResult:
        if self._serial is not None:
            return TransportOpenResult(TransportOpenStatus.OPENED, False, "ALREADY_OPEN")
        if cancellation_requested(cancellation):
            return TransportOpenResult(TransportOpenStatus.CANCELLED, True, "BEFORE_SERIAL_OPEN")
        factory = self._serial_factory or self._default_factory()
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
        if cancellation_requested(cancellation):
            return self._cancel_open("AFTER_SERIAL_OPEN")
        try:
            self._serial.dtr = False
            self._serial.rts = False
            stage = self._finish_open(cancellation)
        except Exception as open_error:
            if self._serial is None:
                raise
            try:
                self.close()
            except TransportError as cleanup_error:
                raise TransportError(
                    f"serial open failed: {open_error}; cleanup failed: {cleanup_error}"
                ) from open_error
            raise
        if stage is not None:
            return self._cancel_open(stage)
        return TransportOpenResult(TransportOpenStatus.OPENED, False, "OPEN_COMPLETE")

    def _cancel_open(self, stage: str) -> TransportOpenResult:
        try:
            self.close()
        except TransportError as cleanup_error:
            raise TransportError(
                f"serial open cancellation at {stage}; cleanup failed: {cleanup_error}"
            ) from cleanup_error
        return TransportOpenResult(TransportOpenStatus.CANCELLED, True, stage)

    @staticmethod
    def _cancellable_wait(
        delay_ms: int,
        cancellation: CancellationToken | None,
    ) -> bool:
        deadline = time.monotonic() + delay_ms / 1000.0
        interval = _CANCELLATION_POLL_MS / 1000.0
        while True:
            if cancellation_requested(cancellation):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return cancellation_requested(cancellation)
            time.sleep(min(interval, remaining))

    def _finish_open(self, cancellation: CancellationToken | None) -> str | None:
        if self._cancellable_wait(_OPEN_SETTLE_MS, cancellation):
            return "OPEN_SETTLE"
        stage = self._autobaud(cancellation)
        if stage is not None:
            return stage
        if self._cancellable_wait(_POST_AUTOBAUD_DELAY_MS, cancellation):
            return "POST_AUTOBAUD_DELAY"
        if cancellation_requested(cancellation):
            return "BEFORE_OPEN_RETURN"
        return None

    def _require_open(self) -> Any:
        if self._serial is None:
            raise TransportClosedError("serial transport is not open")
        return self._serial

    @staticmethod
    def _set_timeout(serial_port: Any, timeout_seconds: float) -> None:
        serial_port.timeout = max(0.0, timeout_seconds)

    def _autobaud_attempt(self, serial_port: Any, timeout_seconds: float) -> bool:
        serial_port.write(b"A")
        if hasattr(serial_port, "flush"):
            serial_port.flush()
        self._set_timeout(serial_port, timeout_seconds)
        return serial_port.read(1) == b"A"

    def _autobaud(self, cancellation: CancellationToken | None) -> str | None:
        serial_port = self._require_open()
        deadline = time.monotonic() + self.config.autobaud_timeout_ms / 1000.0
        interval = _AUTOBAUD_INTERVAL_MS / 1000.0
        while True:
            if cancellation_requested(cancellation):
                return "AUTOBAUD_BEFORE_ATTEMPT"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportTimeoutError("SCI autobaud handshake timed out")
            try:
                if self._autobaud_attempt(serial_port, min(interval, remaining)):
                    self._set_timeout(serial_port, self.config.rx_timeout_ms / 1000.0)
                    if cancellation_requested(cancellation):
                        return "AUTOBAUD_AFTER_ECHO"
                    return None
            except TransportTimeoutError:
                raise
            except Exception as exc:
                raise TransportError(f"SCI autobaud handshake failed: {exc}") from exc
            if cancellation_requested(cancellation):
                return "AUTOBAUD_AFTER_ATTEMPT"

    def close(self) -> None:
        serial_port = self._serial
        if serial_port is None:
            return
        try:
            serial_port.close()
        except Exception as exc:
            raise TransportError(f"failed to close serial port: {exc}") from exc
        self._serial = None

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
