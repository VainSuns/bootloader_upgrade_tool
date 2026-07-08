"""Command-level protocol client for ByteTransport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .command_timeouts import DEFAULT_COMMAND_TIMEOUT_MS
from .constants import BootSlot, Command, MetadataRecordType, PacketType, Status, Target
from .frame import Frame
from .frame_reader import FrameReader
from .models import DeviceInfo, ErrorDetail, MetadataSummary, ServiceStatus, split_u32
from .sequence import next_sequence, validate_response_sequence
from ..core.client import ProtocolDecodeError, ProtocolStatusError
from ..transport.base import ByteTransport


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
            raise ValueError("ProtocolInfo requires exactly 8 words")
        if any(word < 0 or word > 0xFFFF for word in values):
            raise ValueError("ProtocolInfo values must fit uint16")
        return cls(*values)


class BootProtocolClient:
    def __init__(
        self,
        transport: ByteTransport,
        frame_reader: FrameReader | None = None,
    ) -> None:
        self.transport = transport
        self.frame_reader = frame_reader or FrameReader(transport)
        self._sequence = 0
        self.device_info: DeviceInfo | None = None

    def transact(
        self,
        command: int,
        payload: Sequence[int] = (),
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, ...]:
        self._sequence = next_sequence(self._sequence)
        request = Frame(PacketType.REQUEST, int(command), self._sequence, payload)
        self.transport.write_all(request.encode_bytes())
        timeout = timeout_ms or DEFAULT_COMMAND_TIMEOUT_MS.get(int(command), 1000)
        max_payload = self.device_info.max_payload_words if self.device_info else 0xFFFF
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
        return response.payload

    def ping(self) -> tuple[int, ...]:
        return self.transact(Command.PING)

    def get_device_info(self) -> DeviceInfo:
        self.device_info = DeviceInfo.from_words(self.transact(Command.GET_DEVICE_INFO))
        return self.device_info

    def get_protocol_info(self) -> ProtocolInfo:
        return ProtocolInfo.from_words(self.transact(Command.GET_PROTOCOL_INFO))

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
