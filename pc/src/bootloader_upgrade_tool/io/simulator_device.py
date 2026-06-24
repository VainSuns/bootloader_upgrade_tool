"""PcIoDevice adapter around the in-process simulator core."""

from __future__ import annotations

from collections import deque
from threading import Event
import time

from .base import IoDeviceNotOpenError, IoTimeoutError, PcIoDevice, validate_timeout, validate_word
from ..protocol.frame import Frame
from ..protocol.resync import ResyncReader
from ..protocol.sequence import next_sequence
from ..simulator.core import SimulatorCore


class SimulatorIoDevice(PcIoDevice):
    def __init__(self, core: SimulatorCore | None = None) -> None:
        self.core = core or SimulatorCore()
        self._open = False
        self._reader = ResyncReader(self.core.device_info.max_payload_words)
        self._response_words: deque[int] = deque()

    def open(self) -> None:
        if not self._open:
            self._reader = ResyncReader(self.core.device_info.max_payload_words)
            self._response_words.clear()
        self._open = True

    def _require_open(self) -> None:
        if not self._open:
            raise IoDeviceNotOpenError("simulator device is not open")

    def wait_slave(
        self, timeout_ms: int | None, cancel_event: Event | None = None
    ) -> None:
        self._require_open()
        if timeout_ms is not None:
            validate_timeout(timeout_ms)

    def read_word(self, timeout_ms: int) -> int:
        self._require_open()
        deadline = time.monotonic() + validate_timeout(timeout_ms)
        while not self._response_words:
            if time.monotonic() >= deadline:
                raise IoTimeoutError("simulator response timed out")
            time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))
        return self._response_words.popleft()

    def clear_input(self) -> None:
        self._require_open()
        self._response_words.clear()

    def write_word(self, word: int) -> None:
        self._require_open()
        frames = self._reader.feed(validate_word(word))
        for request in frames:
            response = self.core.transact(request)
            faults = self.core.faults
            if faults.no_response:
                continue
            if faults.sequence_mismatch:
                response = Frame(
                    response.packet_type,
                    response.command,
                    next_sequence(response.sequence),
                    response.payload,
                    flags=response.flags,
                    status=response.status,
                    protocol_version=response.protocol_version,
                )
            encoded = list(response.encode_words())
            if faults.bad_payload_crc:
                encoded[-1] ^= 1
            self._response_words.extend(encoded)

    def close(self) -> None:
        self._open = False
        self._response_words.clear()
