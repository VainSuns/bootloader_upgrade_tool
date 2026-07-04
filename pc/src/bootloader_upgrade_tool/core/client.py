"""Synchronous master-side request/response protocol client."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
import time
from typing import Callable, Sequence

from ..io.base import IoTimeoutError, PcIoDevice
from ..protocol.constants import BootSlot, Command, MetadataRecordType, PacketType, ReadTarget, Status, Target
from ..protocol.crc import crc16_words
from ..protocol.frame import Frame, FrameError, decode_frame
from ..protocol.models import DeviceInfo, ErrorDetail, MetadataSummary, join_u32, split_u32
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
    def __init__(
        self,
        device: PcIoDevice,
        *,
        default_timeout_ms: int = 1000,
        post_write_delay_ms: int = 0,
        clear_input_before_request: bool = False,
    ) -> None:
        if default_timeout_ms <= 0:
            raise ValueError("default_timeout_ms must be positive")
        if post_write_delay_ms < 0:
            raise ValueError("post_write_delay_ms must be non-negative")
        self.device = device
        self.default_timeout_ms = default_timeout_ms
        self.post_write_delay_ms = post_write_delay_ms
        self.clear_input_before_request = clear_input_before_request
        self._sequence = 0
        self.device_info: DeviceInfo | None = None
        self.trace_bytes: Callable[[str, bytes], None] | None = None

    def connect(
        self,
        *,
        wait_slave_timeout_ms: int | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        self.device.open()
        try:
            self.device.wait_slave(wait_slave_timeout_ms, cancel_event)
        except Exception:
            self.device.close()
            raise
        self._sequence = 0
        self.device_info = None

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
        if self.clear_input_before_request:
            self.device.clear_input()
        self._sequence = next_sequence(self._sequence)
        request = Frame(PacketType.REQUEST, command, self._sequence, payload)
        request_bytes = request.encode_bytes()
        self._trace(f"TX {self._command_name(command)} seq={self._sequence}", request_bytes)
        self.device.write_bytes(request_bytes)
        if self.post_write_delay_ms:
            time.sleep(self.post_write_delay_ms / 1000.0)

        timeout = self.default_timeout_ms if timeout_ms is None else timeout_ms
        raw = bytearray()
        try:
            response = self._read_response_frame(timeout, raw)
        except FrameError as exc:
            self._trace(f"RX {self._command_name(command)} decode-error", raw)
            raise ProtocolDecodeError(str(exc)) from exc
        except IoTimeoutError as exc:
            self._trace(f"RX {self._command_name(command)} timeout", raw)
            raise IoTimeoutError(
                f"{self._command_name(command)} response timed out after {timeout} ms; "
                f"TX bytes: {self._format_bytes(request_bytes)}; "
                f"RX bytes: {self._format_bytes(raw)}"
            ) from exc
        self._trace(f"RX {self._command_name(command)}", raw)
        return self._response_payload(request, response)

    def _trace(self, label: str, data: bytes | bytearray) -> None:
        if self.trace_bytes is not None:
            self.trace_bytes(label, bytes(data))

    @staticmethod
    def _command_name(command: int) -> str:
        try:
            return Command(command).name
        except ValueError:
            return f"0x{command:04X}"

    @staticmethod
    def _format_bytes(data: bytes | bytearray) -> str:
        return " ".join(f"{byte:02X}" for byte in data) or "<empty>"

    def _read_response_frame(
        self, timeout_ms: int, raw_bytes: bytearray | None = None
    ) -> Frame:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        max_payload = (
            self.device_info.max_payload_words if self.device_info is not None else 0xFFFF
        )
        magic = bytes((0x5A, 0xA5, 0xA5, 0x5A))
        buffer = bytearray()
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            if time.monotonic() >= deadline:
                raise IoTimeoutError("response byte read timed out")
            chunk = self.device.read_available()
            if not chunk:
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
                continue
            buffer.extend(chunk)
            if raw_bytes is not None:
                raw_bytes.extend(chunk)

            while True:
                start = buffer.find(magic)
                if start < 0:
                    if len(buffer) > 3:
                        del buffer[:-3]
                    break
                if start:
                    del buffer[:start]
                if len(buffer) < 20:
                    break
                header = tuple(
                    buffer[index] | (buffer[index + 1] << 8)
                    for index in range(0, 20, 2)
                )
                if crc16_words(header[:9]) != header[9]:
                    del buffer[0]
                    continue
                if header[8] > max_payload:
                    raise FrameError("response payload exceeds configured maximum")
                frame_size = (10 + header[8] + 1) * 2
                if len(buffer) < frame_size:
                    break
                frame_bytes = buffer[:frame_size]
                words = tuple(
                    frame_bytes[index] | (frame_bytes[index + 1] << 8)
                    for index in range(0, frame_size, 2)
                )
                return decode_frame(words, max_payload_words=max_payload)

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
        try:
            response = self._read_response_frame(timeout_ms, raw)
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
        self.transact(Command.PING, timeout_ms=5000 if timeout_ms is None else timeout_ms)

    def get_device_info(self, *, timeout_ms: int | None = None) -> DeviceInfo:
        info = DeviceInfo.from_words(
            self.transact(
                Command.GET_DEVICE_INFO,
                timeout_ms=5000 if timeout_ms is None else timeout_ms,
            )
        )
        self.device_info = info
        return info

    def get_last_error(self) -> ErrorDetail:
        return ErrorDetail.from_words(
            self.transact(Command.GET_LAST_ERROR, timeout_ms=5000)
        )

    def get_metadata_summary(self, *, timeout_ms: int | None = None) -> MetadataSummary:
        try:
            return MetadataSummary.from_words(
                self.transact(
                    Command.GET_METADATA_SUMMARY,
                    timeout_ms=5000 if timeout_ms is None else timeout_ms,
                )
            )
        except ValueError as exc:
            raise ProtocolDecodeError(str(exc)) from exc

    def metadata_append_image_valid(
        self,
        *,
        entry_point: int,
        image_size_words: int,
        image_crc32: int,
        app_end: int,
        app_version_major: int = 0,
        app_version_minor: int = 0,
        app_version_patch: int = 0,
        app_version_build: int = 0,
        timeout_ms: int | None = None,
    ) -> None:
        entry_low, entry_high = split_u32(entry_point)
        size_low, size_high = split_u32(image_size_words)
        crc_low, crc_high = split_u32(image_crc32)
        build_low, build_high = split_u32(app_version_build)
        end_low, end_high = split_u32(app_end)
        self.transact(
            Command.METADATA_APPEND_RECORD,
            (
                MetadataRecordType.IMAGE_VALID,
                BootSlot.SLOT_A,
                entry_low,
                entry_high,
                size_low,
                size_high,
                crc_low,
                crc_high,
                app_version_major,
                app_version_minor,
                app_version_patch,
                build_low,
                build_high,
                end_low,
                end_high,
                0,
            ),
            timeout_ms=timeout_ms,
        )

    def metadata_append_boot_attempt(
        self,
        *,
        entry_point: int,
        image_size_words: int,
        image_crc32: int,
        timeout_ms: int | None = None,
    ) -> None:
        entry_low, entry_high = split_u32(entry_point)
        size_low, size_high = split_u32(image_size_words)
        crc_low, crc_high = split_u32(image_crc32)
        self.transact(
            Command.METADATA_APPEND_RECORD,
            (
                MetadataRecordType.BOOT_ATTEMPT,
                BootSlot.SLOT_A,
                entry_low,
                entry_high,
                size_low,
                size_high,
                crc_low,
                crc_high,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ),
            timeout_ms=timeout_ms,
        )

    def flash_read(
        self,
        read_target: int,
        address: int,
        word_count: int,
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, tuple[int, ...]]:
        low, high = split_u32(address)
        payload = self.transact(
            Command.FLASH_READ,
            (read_target, low, high, word_count, 0),
            timeout_ms=timeout_ms,
        )
        if len(payload) < 3:
            raise ProtocolDecodeError("FLASH_READ response is too short")
        response_address = join_u32(payload[0], payload[1])
        response_words = payload[2]
        data = payload[3:]
        if response_address != address:
            raise ProtocolDecodeError("FLASH_READ response address mismatch")
        if response_words != word_count or response_words != len(data):
            raise ProtocolDecodeError("FLASH_READ response word count mismatch")
        return response_address, data

    def flash_read_metadata(
        self, address: int, word_count: int, *, timeout_ms: int | None = None
    ) -> tuple[int, ...]:
        _address, data = self.flash_read(
            ReadTarget.METADATA, address, word_count, timeout_ms=timeout_ms
        )
        return data

    def ram_load_begin(
        self,
        *,
        packet_count: int,
        total_words: int,
        entry_point: int,
        image_crc32: int = 0,
        timeout_ms: int | None = None,
    ) -> None:
        total_low, total_high = split_u32(total_words)
        entry_low, entry_high = split_u32(entry_point)
        crc_low, crc_high = split_u32(image_crc32)
        self.transact(
            Command.RAM_LOAD_BEGIN,
            (Target.RAM_APP, packet_count, total_low, total_high, entry_low, entry_high,
             crc_low, crc_high, 0),
            timeout_ms=timeout_ms,
        )

    def ram_load_data(
        self,
        *,
        address: int,
        words: Sequence[int],
        packet_index: int,
        timeout_ms: int | None = None,
    ) -> None:
        address_low, address_high = split_u32(address)
        index_low, index_high = split_u32(packet_index)
        self.transact(
            Command.RAM_LOAD_DATA,
            (address_low, address_high, len(words), index_low, index_high, *words),
            timeout_ms=timeout_ms,
        )

    def ram_load_end(
        self,
        *,
        packet_count: int,
        total_words: int,
        image_crc32: int = 0,
        timeout_ms: int | None = None,
    ) -> None:
        packet_low, packet_high = split_u32(packet_count)
        total_low, total_high = split_u32(total_words)
        crc_low, crc_high = split_u32(image_crc32)
        self.transact(
            Command.RAM_LOAD_END,
            (packet_low, packet_high, total_low, total_high, crc_low, crc_high),
            timeout_ms=timeout_ms,
        )

    def ram_check_crc(
        self,
        *,
        expected_crc32: int,
        expected_total_words: int,
        timeout_ms: int | None = None,
    ) -> None:
        crc_low, crc_high = split_u32(expected_crc32)
        words_low, words_high = split_u32(expected_total_words)
        self.transact(
            Command.RAM_CHECK_CRC,
            (crc_low, crc_high, words_low, words_high, 0),
            timeout_ms=timeout_ms,
        )

    def run_ram(self, *, entry_point: int = 0, timeout_ms: int | None = None) -> None:
        entry_low, entry_high = split_u32(entry_point)
        self.transact(Command.RUN_RAM, (entry_low, entry_high, 0), timeout_ms=timeout_ms)
