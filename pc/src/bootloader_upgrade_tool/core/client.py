"""Synchronous master-side request/response protocol client."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Sequence

from ..io.base import IoTimeoutError, PcIoDevice
from ..protocol.constants import Command, PacketType, Status
from ..protocol.frame import Frame, PayloadCrcError
from ..protocol.models import DeviceInfo, ErrorDetail
from ..protocol.resync import ResyncReader
from ..protocol.sequence import SequenceMismatchError, next_sequence, validate_response_sequence


class ProtocolClientError(RuntimeError):
    pass


class ProtocolDecodeError(ProtocolClientError):
    pass


@dataclass(slots=True)
class ProtocolStatusError(ProtocolClientError):
    command: int
    status: int

    def __str__(self) -> str:
        try:
            status_name = Status(self.status).name
        except ValueError:
            status_name = f"0x{self.status:04X}"
        return f"command 0x{self.command:04X} failed: {status_name}"


class ProtocolClient:
    def __init__(self, device: PcIoDevice, *, default_timeout_ms: int = 1000) -> None:
        if default_timeout_ms <= 0:
            raise ValueError("default_timeout_ms must be positive")
        self.device = device
        self.default_timeout_ms = default_timeout_ms
        self._sequence = 0
        self._reader = ResyncReader(0xFFFF)
        self.device_info: DeviceInfo | None = None

    def connect(
        self,
        *,
        wait_slave_timeout_ms: int | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        self.device.open()
        try:
            self.device.wait_slave(wait_slave_timeout_ms, cancel_event)
            self.device.clear_input()
        except Exception:
            self.device.close()
            raise
        self._sequence = 0
        self.device_info = None
        self._reader = ResyncReader(0xFFFF)

    def open(
        self,
        *,
        wait_slave_timeout_ms: int | None = None,
        device_info_timeout_ms: int = 5000,
        cancel_event: Event | None = None,
    ) -> DeviceInfo:
        self.connect(
            wait_slave_timeout_ms=wait_slave_timeout_ms,
            cancel_event=cancel_event,
        )
        try:
            return self.get_device_info(timeout_ms=device_info_timeout_ms)
        except IoTimeoutError as exc:
            self.device.close()
            raise IoTimeoutError(
                f"GetDeviceInfo response timed out after {device_info_timeout_ms} ms"
            ) from exc

    def close(self) -> None:
        self.device.close()

    def transact(
        self,
        command: int,
        payload: Sequence[int] = (),
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, ...]:
        self.device.clear_input()
        max_payload_words = (
            self.device_info.max_payload_words if self.device_info is not None else 0xFFFF
        )
        self._reader = ResyncReader(max_payload_words)
        self._sequence = next_sequence(self._sequence)
        request = Frame(PacketType.REQUEST, command, self._sequence, payload)
        for word in request.encode_words():
            self.device.write_word(word)

        timeout = self.default_timeout_ms if timeout_ms is None else timeout_ms
        error_count = len(self._reader.errors)
        while True:
            try:
                frames = self._reader.feed(self.device.read_word(timeout))
            except IoTimeoutError:
                raise
            for error in self._reader.errors[error_count:]:
                if isinstance(error, PayloadCrcError):
                    raise ProtocolDecodeError("response payload CRC mismatch") from error
            error_count = len(self._reader.errors)
            if not frames:
                continue
            response = frames[0]
            try:
                validate_response_sequence(request.sequence, response.sequence)
            except SequenceMismatchError as exc:
                raise ProtocolDecodeError(str(exc)) from exc
            if response.command != request.command:
                raise ProtocolDecodeError("response command does not match request")
            if response.packet_type not in (PacketType.RESPONSE, PacketType.ERROR_RESPONSE):
                raise ProtocolDecodeError("unexpected response packet type")
            if response.status != Status.OK:
                raise ProtocolStatusError(response.command, response.status)
            if response.packet_type != PacketType.RESPONSE:
                raise ProtocolDecodeError("OK status requires a normal response packet")
            return response.payload

    def ping(self, *, timeout_ms: int | None = None) -> None:
        self.transact(Command.PING, timeout_ms=timeout_ms)

    def get_device_info(self, *, timeout_ms: int | None = None) -> DeviceInfo:
        info = DeviceInfo.from_words(
            self.transact(Command.GET_DEVICE_INFO, timeout_ms=timeout_ms)
        )
        self.device_info = info
        self._reader = ResyncReader(info.max_payload_words)
        return info

    def get_last_error(self) -> ErrorDetail:
        return ErrorDetail.from_words(self.transact(Command.GET_LAST_ERROR))
