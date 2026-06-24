"""Synchronous master-side request/response protocol client."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
import time
from typing import Sequence

from ..io.base import IoTimeoutError, PcIoDevice
from ..protocol.constants import Command, PacketType, Status
from ..protocol.crc import crc16_words
from ..protocol.frame import Frame, PayloadCrcError, decode_frame
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


@dataclass(slots=True)
class DeviceInfoDebugResult:
    request_words: list[int]
    request_bytes: bytes
    bytes_written: int
    flush_done: bool
    rx_bytes: bytes
    input_bytes_pending_before_clear: int | None = None
    device_info: DeviceInfo | None = None
    error_stage: str | None = None
    error_message: str | None = None


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
        self.device.write_bytes(request.encode_bytes())

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
            return self._response_payload(request, response)

    @staticmethod
    def _response_payload(request: Frame, response: Frame) -> tuple[int, ...]:
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

    def get_device_info_debug(
        self, *, timeout_ms: int = 5000
    ) -> DeviceInfoDebugResult:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        pending = self.device.input_bytes_pending()
        self.device.clear_input()
        self._sequence = next_sequence(self._sequence)
        request = Frame(PacketType.REQUEST, Command.GET_DEVICE_INFO, self._sequence)
        request_words = list(request.encode_words())
        request_bytes = request.encode_bytes()
        try:
            bytes_written = self.device.write_bytes(request_bytes)
        except Exception as exc:
            return DeviceInfoDebugResult(
                request_words,
                request_bytes,
                0,
                False,
                b"",
                pending,
                error_stage="writing_request",
                error_message=str(exc),
            )

        time.sleep(0.1)

        raw = bytearray()
        magic = bytes((0x5A, 0xA5, 0xA5, 0x5A))
        frame_start: int | None = None
        frame_size: int | None = None
        deadline = time.monotonic() + timeout_ms / 1000.0
        try:
            while True:
                remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                if time.monotonic() >= deadline:
                    raise IoTimeoutError("serial byte read timed out")
                raw.append(self.device.read_byte(remaining_ms))
                if frame_start is None:
                    found = raw.find(magic)
                    if found >= 0:
                        frame_start = found
                if frame_start is None or len(raw) - frame_start < 20:
                    continue
                if frame_size is None:
                    header_bytes = raw[frame_start : frame_start + 20]
                    header = tuple(
                        header_bytes[index] | (header_bytes[index + 1] << 8)
                        for index in range(0, 20, 2)
                    )
                    if crc16_words(header[:9]) != header[9]:
                        raise ProtocolDecodeError("response header CRC mismatch")
                    max_payload = (
                        self.device_info.max_payload_words
                        if self.device_info is not None
                        else 0xFFFF
                    )
                    if header[8] > max_payload:
                        raise ProtocolDecodeError("response payload exceeds configured maximum")
                    frame_size = (10 + header[8] + 1) * 2
                if len(raw) - frame_start >= frame_size:
                    break
        except Exception as exc:
            no_response = not raw
            return DeviceInfoDebugResult(
                request_words,
                request_bytes,
                bytes_written,
                True,
                bytes(raw),
                pending,
                error_stage="waiting_for_response" if no_response else "receiving_response",
                error_message=(
                    "No response bytes received after writing and flushing request."
                    if no_response
                    else str(exc)
                ),
            )

        try:
            frame_bytes = raw[frame_start : frame_start + frame_size]
            words = tuple(
                frame_bytes[index] | (frame_bytes[index + 1] << 8)
                for index in range(0, len(frame_bytes), 2)
            )
            response = decode_frame(words)
            info = DeviceInfo.from_words(self._response_payload(request, response))
        except Exception as exc:
            return DeviceInfoDebugResult(
                request_words,
                request_bytes,
                bytes_written,
                True,
                bytes(raw),
                pending,
                error_stage="decoding_response",
                error_message=str(exc),
            )

        self.device_info = info
        self._reader = ResyncReader(info.max_payload_words)
        return DeviceInfoDebugResult(
            request_words,
            request_bytes,
            bytes_written,
            True,
            bytes(raw),
            pending,
            device_info=info,
        )

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
