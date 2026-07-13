"""Command-level protocol client for ByteTransport."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Sequence

from .command_timeouts import DEFAULT_COMMAND_TIMEOUT_MS
from .constants import (
    CRC_TYPE_CCITT_FALSE,
    DEVICE_INFO_WORDS,
    ENDIAN_LITTLE,
    ERROR_DETAIL_WORDS,
    HEADER_WORDS,
    PROTOCOL_INFO_WORDS,
    PROTOCOL_VERSION,
    WRITE_DATA_ALIGNMENT_WORDS,
    BootSlot,
    Command,
    MetadataRecordType,
    PacketType,
    Status,
    Target,
)
from .frame import Frame
from .frame_reader import FrameReader
from .models import DeviceInfo, ErrorDetail, MetadataSummary, ServiceStatus, split_u32
from .sequence import next_sequence, validate_response_sequence
from ..core.client import ProtocolDecodeError, ProtocolStatusError
from ..transport.base import ByteTransport


BOOTSTRAP_MAX_PAYLOAD_WORDS = max(
    DEVICE_INFO_WORDS,
    PROTOCOL_INFO_WORDS,
    ERROR_DETAIL_WORDS,
)
_BOOTSTRAP_COMMANDS = {
    int(Command.PING),
    int(Command.GET_DEVICE_INFO),
    int(Command.GET_PROTOCOL_INFO),
    int(Command.GET_LAST_ERROR),
}


class ProtocolPayloadLimitError(ProtocolDecodeError):
    def __init__(
        self,
        command: int,
        actual_payload_words: int,
        effective_max_payload_words: int,
        device_max_payload_words: int | None,
        protocol_max_payload_words: int | None,
    ) -> None:
        super().__init__(
            f"command 0x{int(command):04X} payload has {actual_payload_words} words; "
            f"maximum is {effective_max_payload_words}"
        )
        self.command = int(command)
        self.actual_payload_words = actual_payload_words
        self.effective_max_payload_words = effective_max_payload_words
        self.device_max_payload_words = device_max_payload_words
        self.protocol_max_payload_words = protocol_max_payload_words


@dataclass(frozen=True)
class ProtocolInfo:
    protocol_ver: int
    min_supported_ver: int
    max_supported_ver: int
    header_words: int
    crc_type: int
    endian: int
    max_payload_words: int
    flags: int

    @classmethod
    def from_words(cls, words: Sequence[int]) -> ProtocolInfo:
        values = tuple(words)
        if len(values) != 8:
            raise ProtocolDecodeError("ProtocolInfo requires exactly 8 words")
        if any(word < 0 or word > 0xFFFF for word in values):
            raise ProtocolDecodeError("ProtocolInfo values must fit uint16")
        result = cls(*values)
        if result.max_payload_words <= 0:
            raise ProtocolDecodeError("ProtocolInfo max_payload_words must be positive")
        if result.protocol_ver != PROTOCOL_VERSION:
            raise ProtocolDecodeError("unsupported ProtocolInfo protocol_ver")
        if result.min_supported_ver > PROTOCOL_VERSION or result.max_supported_ver < PROTOCOL_VERSION:
            raise ProtocolDecodeError("host protocol version is outside the supported range")
        if result.header_words != HEADER_WORDS:
            raise ProtocolDecodeError("unsupported ProtocolInfo header_words")
        if result.crc_type != CRC_TYPE_CCITT_FALSE:
            raise ProtocolDecodeError("unsupported ProtocolInfo crc_type")
        if result.endian != ENDIAN_LITTLE:
            raise ProtocolDecodeError("unsupported ProtocolInfo endian")
        return result


class BootProtocolClient:
    def __init__(
        self,
        transport: ByteTransport,
        frame_reader: FrameReader | None = None,
    ) -> None:
        self.transport = transport
        self.frame_reader = frame_reader or FrameReader(transport)
        self._sequence = 0
        self._device_info: DeviceInfo | None = None
        self._protocol_info: ProtocolInfo | None = None
        self._transaction_lock = Lock()

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._device_info

    @property
    def protocol_info(self) -> ProtocolInfo | None:
        return self._protocol_info

    @property
    def effective_max_payload_words(self) -> int:
        if self._device_info is None or self._protocol_info is None:
            raise ProtocolDecodeError("device and protocol capabilities are required")
        limit = min(self._device_info.max_payload_words, self._protocol_info.max_payload_words)
        if limit <= 0:
            raise ProtocolDecodeError("effective max payload words must be positive")
        return limit

    @property
    def effective_max_data_words(self) -> int:
        if self._device_info is None:
            raise ProtocolDecodeError("device capabilities are required")
        limit = min(self._device_info.max_data_words, self.effective_max_payload_words - 5)
        if limit <= 0:
            raise ProtocolDecodeError("effective max DATA words must be positive")
        return limit

    @property
    def effective_max_write_data_words(self) -> int:
        data_words = self.effective_max_data_words
        limit = data_words - data_words % WRITE_DATA_ALIGNMENT_WORDS
        if limit <= 0 or limit % WRITE_DATA_ALIGNMENT_WORDS:
            raise ProtocolDecodeError("effective max Flash DATA words must be a positive aligned value")
        return limit

    def reset_connection_state(self) -> None:
        self._sequence = 0
        self._device_info = None
        self._protocol_info = None

    def _payload_limit(self, command: int) -> int:
        if self._device_info is not None and self._protocol_info is not None:
            return self.effective_max_payload_words
        if command not in _BOOTSTRAP_COMMANDS:
            return self.effective_max_payload_words
        limits = [BOOTSTRAP_MAX_PAYLOAD_WORDS]
        if self._device_info is not None and self._device_info.max_payload_words > 0:
            limits.append(self._device_info.max_payload_words)
        if self._protocol_info is not None and self._protocol_info.max_payload_words > 0:
            limits.append(self._protocol_info.max_payload_words)
        return min(limits)

    def _cache_capability(self, command: int, payload: tuple[int, ...]) -> None:
        try:
            if command == int(Command.GET_DEVICE_INFO):
                info = DeviceInfo.from_words(payload)
                if self._device_info is not None and (
                    info.device_id,
                    info.cpu_id,
                ) != (
                    self._device_info.device_id,
                    self._device_info.cpu_id,
                ):
                    raise ProtocolDecodeError(
                        "DeviceInfo target identity changed: "
                        f"cached device_id=0x{self._device_info.device_id:04X}, cpu_id={self._device_info.cpu_id}; "
                        f"received device_id=0x{info.device_id:04X}, cpu_id={info.cpu_id}"
                    )
                if self._protocol_info is not None and info.protocol_ver != self._protocol_info.protocol_ver:
                    raise ProtocolDecodeError("DeviceInfo and ProtocolInfo protocol versions do not match")
                self._device_info = info
            elif command == int(Command.GET_PROTOCOL_INFO):
                info = ProtocolInfo.from_words(payload)
                if self._device_info is not None and info.protocol_ver != self._device_info.protocol_ver:
                    raise ProtocolDecodeError("DeviceInfo and ProtocolInfo protocol versions do not match")
                self._protocol_info = info
        except ProtocolDecodeError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProtocolDecodeError(str(exc)) from exc

    def transact(
        self,
        command: int,
        payload: Sequence[int] = (),
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, ...]:
        with self._transaction_lock:
            command_id = int(command)
            request_payload = tuple(payload)
            max_payload = self._payload_limit(command_id)
            if len(request_payload) > max_payload:
                raise ProtocolPayloadLimitError(
                    command_id,
                    len(request_payload),
                    max_payload,
                    None if self._device_info is None else self._device_info.max_payload_words,
                    None if self._protocol_info is None else self._protocol_info.max_payload_words,
                )
            sequence = next_sequence(self._sequence)
            request = Frame(PacketType.REQUEST, command_id, sequence, request_payload)
            self.transport.write_all(request.encode_bytes())
            self._sequence = sequence
            timeout = timeout_ms or DEFAULT_COMMAND_TIMEOUT_MS.get(command_id, 1000)
            response = self.frame_reader.read_frame(
                timeout_ms=timeout,
                max_payload_words=max_payload,
            )
            validate_response_sequence(request.sequence, response.sequence)
            if response.command != request.command:
                raise ProtocolDecodeError("response command does not match request")
            if response.packet_type not in (PacketType.RESPONSE, PacketType.ERROR_RESPONSE):
                raise ProtocolDecodeError("unexpected response packet type")
            if response.status != Status.OK:
                raise ProtocolStatusError(response.command, response.status)
            if response.packet_type != PacketType.RESPONSE:
                raise ProtocolDecodeError("OK status requires a normal response packet")
            self._cache_capability(command_id, response.payload)
            return response.payload

    def ping(self) -> tuple[int, ...]:
        return self.transact(Command.PING)

    def get_device_info(self) -> DeviceInfo:
        self.transact(Command.GET_DEVICE_INFO)
        if self._device_info is None:
            raise ProtocolDecodeError("GET_DEVICE_INFO succeeded without cached DeviceInfo")
        return self._device_info

    def get_protocol_info(self) -> ProtocolInfo:
        self.transact(Command.GET_PROTOCOL_INFO)
        if self._protocol_info is None:
            raise ProtocolDecodeError("GET_PROTOCOL_INFO succeeded without cached ProtocolInfo")
        return self._protocol_info

    def get_last_error(self) -> ErrorDetail:
        return ErrorDetail.from_words(self.transact(Command.GET_LAST_ERROR))

    def get_metadata_summary(self) -> MetadataSummary:
        return MetadataSummary.from_words(self.transact(Command.GET_METADATA_SUMMARY))

    def get_service_status(self) -> ServiceStatus:
        return ServiceStatus.from_words(self.transact(Command.GET_SERVICE_STATUS))

    def service_attach(
        self,
        *,
        descriptor_address: int,
        expected_crc32: int,
        expected_total_words: int,
    ) -> tuple[int, ...]:
        return self.transact(
            Command.SERVICE_ATTACH,
            (*split_u32(descriptor_address), *split_u32(expected_crc32),
             *split_u32(expected_total_words), 0),
        )

    def ram_load_begin(
        self,
        *,
        packet_count: int,
        total_words: int,
        entry_point: int,
        image_crc32: int = 0,
    ) -> tuple[int, ...]:
        return self.transact(
            Command.RAM_LOAD_BEGIN,
            (Target.RAM_APP, packet_count, *split_u32(total_words),
             *split_u32(entry_point), *split_u32(image_crc32), 0),
        )

    def ram_load_data(
        self, *, address: int, words: Sequence[int], packet_index: int
    ) -> tuple[int, ...]:
        return self.transact(
            Command.RAM_LOAD_DATA,
            (*split_u32(address), len(words), *split_u32(packet_index), *words),
        )

    def ram_load_end(
        self, *, packet_count: int, total_words: int, image_crc32: int = 0
    ) -> tuple[int, ...]:
        return self.transact(
            Command.RAM_LOAD_END,
            (*split_u32(packet_count), *split_u32(total_words), *split_u32(image_crc32)),
        )

    def ram_check_crc(
        self, *, expected_crc32: int, expected_total_words: int
    ) -> tuple[int, ...]:
        return self.transact(
            Command.RAM_CHECK_CRC,
            (*split_u32(expected_crc32), *split_u32(expected_total_words), 0),
        )

    def erase(self, *, sector_mask: int) -> tuple[int, ...]:
        return self.transact(Command.ERASE, (*split_u32(sector_mask), 0))

    def program_begin(
        self, *, packet_count: int, total_words: int, entry_point: int, image_crc32: int = 0
    ) -> tuple[int, ...]:
        return self.transact(
            Command.PROGRAM_BEGIN,
            (Target.FLASH_APP, packet_count, *split_u32(total_words),
             *split_u32(entry_point), *split_u32(image_crc32), 0),
        )

    def program_data(
        self, *, address: int, words: Sequence[int], packet_index: int
    ) -> tuple[int, ...]:
        return self.transact(
            Command.PROGRAM_DATA,
            (*split_u32(address), len(words), *split_u32(packet_index), *words),
        )

    def program_end(
        self, *, packet_count: int, total_words: int, image_crc32: int = 0
    ) -> tuple[int, ...]:
        return self.transact(
            Command.PROGRAM_END,
            (*split_u32(packet_count), *split_u32(total_words), *split_u32(image_crc32)),
        )

    def verify_begin(
        self, *, packet_count: int, total_words: int, entry_point: int, image_crc32: int = 0
    ) -> tuple[int, ...]:
        return self.transact(
            Command.VERIFY_BEGIN,
            (Target.FLASH_APP, packet_count, *split_u32(total_words),
             *split_u32(entry_point), *split_u32(image_crc32), 0),
        )

    def verify_data(
        self, *, address: int, words: Sequence[int], packet_index: int
    ) -> tuple[int, ...]:
        return self.transact(
            Command.VERIFY_DATA,
            (*split_u32(address), len(words), *split_u32(packet_index), *words),
        )

    def verify_end(
        self, *, packet_count: int, total_words: int, image_crc32: int = 0
    ) -> tuple[int, ...]:
        return self.transact(
            Command.VERIFY_END,
            (*split_u32(packet_count), *split_u32(total_words), *split_u32(image_crc32)),
        )

    def _metadata_append(
        self,
        record_type: int,
        *,
        entry_point: int,
        image_size_words: int,
        image_crc32: int,
        app_end: int = 0,
    ) -> tuple[int, ...]:
        return self.transact(
            Command.METADATA_APPEND_RECORD,
            (record_type, BootSlot.SLOT_A, *split_u32(entry_point),
             *split_u32(image_size_words), *split_u32(image_crc32),
             0, 0, 0, 0, 0, *split_u32(app_end), 0),
        )

    def metadata_append_image_valid(self, **kwargs: int) -> tuple[int, ...]:
        return self._metadata_append(MetadataRecordType.IMAGE_VALID, **kwargs)

    def metadata_append_boot_attempt(self, **kwargs: int) -> tuple[int, ...]:
        return self._metadata_append(MetadataRecordType.BOOT_ATTEMPT, **kwargs)

    def metadata_append_app_confirmed(self, **kwargs: int) -> tuple[int, ...]:
        return self._metadata_append(MetadataRecordType.APP_CONFIRMED, **kwargs)

    def run(self, *, entry_point: int, target: int = int(Target.FLASH_APP)) -> tuple[int, ...]:
        return self.transact(Command.RUN, (target, *split_u32(entry_point), 0))

    def reset(self) -> tuple[int, ...]:
        return self.transact(Command.RESET)

    def run_ram(self, *, entry_point: int = 0) -> tuple[int, ...]:
        return self.transact(Command.RUN_RAM, (*split_u32(entry_point), 0))
