"""Stateful protocol-command simulator with sparse in-memory Flash."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from ..firmware.crc32 import crc32_words
from ..protocol.alignment import DataAlignmentError, validate_write_data
from ..firmware import (
    APP_FLASH_END_EXCLUSIVE,
    APP_FLASH_START,
    SLOT_A_METADATA_END,
    SLOT_A_METADATA_START,
)
from ..protocol.constants import (
    BootMode,
    Command,
    CpuId,
    DeviceId,
    ErrorOperation,
    ErrorStage,
    Feature,
    KernelLayout,
    PacketType,
    PROTOCOL_VERSION,
    BootSlot,
    MetadataRecordType,
    ReadTarget,
    SERVICE_DESCRIPTOR_MAGIC,
    SERVICE_DESCRIPTOR_VERSION,
    SERVICE_DESCRIPTOR_WORDS,
    SERVICE_REQUIRED_CAPABILITIES,
    Status,
    ServiceState,
    Target,
)
from ..protocol.frame import Frame
from ..protocol.models import DeviceInfo, ErrorDetail, MetadataSummary, join_u32, split_u32


METADATA_MAGIC0 = 0x4D42
METADATA_MAGIC1 = 0x4453
METADATA_RECORD_VERSION = 1
METADATA_RECORD_WORDS = 64
METADATA_RECORD_COUNT = 16
METADATA_BOOT_ATTEMPT_LIMIT = 3


@dataclass(frozen=True, slots=True)
class FlashSector:
    name: str
    start: int
    length_words: int

    def __post_init__(self) -> None:
        if not self.name or self.start < 0 or self.length_words <= 0:
            raise ValueError("invalid Flash sector")

    @property
    def end_exclusive(self) -> int:
        return self.start + self.length_words

    def contains(self, address: int) -> bool:
        return self.start <= address < self.end_exclusive


@dataclass(slots=True)
class SimulatorFaults:
    erase_fail: bool = False
    program_fail_at_address: int | None = None
    verify_fail_at_address: int | None = None
    bad_payload_crc: bool = False
    no_response: bool = False
    illegal_address: bool = False
    sequence_mismatch: bool = False
    bad_block_index: bool = False


class SimulatorAction(Enum):
    NONE = "none"
    RUN_APP = "run_app"
    RUN_RAM = "run_ram"
    RESET_DEVICE = "reset_device"


@dataclass(slots=True)
class _Session:
    block_count: int
    total_words: int
    entry_point: int
    crc_words: list[int]
    expected_index: int = 0
    packet_count: int = 0
    received_words: int = 0
    start: int | None = None
    end_exclusive: int | None = None


class SimulatorCore:
    def __init__(
        self,
        *,
        sectors: Sequence[FlashSector] | None = None,
        device_info: DeviceInfo | None = None,
        faults: SimulatorFaults | None = None,
        require_service_for_flash_commands: bool = False,
    ) -> None:
        self.sectors = tuple(
            sectors
            or (
                FlashSector("FLASHA", 0x080000, 0x002000),
                FlashSector("FLASHB", 0x082000, 0x002000),
                FlashSector("FLASHC", 0x084000, 0x002000),
                FlashSector("FLASHD", 0x086000, 0x002000),
                FlashSector("FLASHE", 0x088000, 0x008000),
                FlashSector("FLASHF", 0x090000, 0x008000),
                FlashSector("FLASHG", 0x098000, 0x008000),
                FlashSector("FLASHH", 0x0A0000, 0x008000),
                FlashSector("FLASHI", 0x0A8000, 0x008000),
                FlashSector("FLASHJ", 0x0B0000, 0x008000),
                FlashSector("FLASHK", 0x0B8000, 0x002000),
                FlashSector("FLASHL", 0x0BA000, 0x002000),
                FlashSector("FLASHM", 0x0BC000, 0x002000),
                FlashSector("FLASHN", 0x0BE000, 0x002000),
            )
        )
        if len(self.sectors) > 32:
            raise ValueError("MVP sector mask supports at most 32 sectors")
        self.device_info = device_info or DeviceInfo(
            DeviceId.F28377D,
            CpuId.CPU1,
            0,
            1,
            0,
            PROTOCOL_VERSION,
            int(Feature.ERASE | Feature.PROGRAM | Feature.VERIFY | Feature.RUN | Feature.RESET | Feature.RAM_LOAD),
            256,
            248,
            BootMode.FLASH_KERNEL,
            KernelLayout.MONOLITHIC,
        )
        self.faults = faults or SimulatorFaults()
        self.require_service_for_flash_commands = require_service_for_flash_commands
        self.flash: dict[int, int] = {}
        self.programmed_addresses: set[int] = set()
        self.last_error = ErrorDetail(0, 0, 0, 0, 0, 0, 0, 0)
        self.program_session: _Session | None = None
        self.verify_session: _Session | None = None
        self.ram_load_session: _Session | None = None
        self.ram_loaded: _Session | None = None
        self.ram_crc_ok = False
        self.ram: dict[int, int] = {}
        self.service_state = ServiceState.DETACHED
        self.service_last_attach_status = Status.OK
        self.service_major = 0
        self.service_minor = 0
        self.service_capabilities = 0
        self.pending_action = SimulatorAction.NONE
        self.verify_succeeded = False

    def _response(
        self,
        request: Frame,
        status: Status = Status.OK,
        payload: Sequence[int] = (),
    ) -> Frame:
        packet_type = PacketType.RESPONSE if status == Status.OK else PacketType.ERROR_RESPONSE
        return Frame(packet_type, request.command, request.sequence, payload, status=status)

    def _fail(
        self,
        request: Frame,
        status: Status,
        operation: ErrorOperation,
        stage: ErrorStage,
        *,
        address: int = 0,
        length_words: int = 0,
        extra0: int = 0,
    ) -> Frame:
        if operation != ErrorOperation.FRAME:
            self.last_error = ErrorDetail(
                operation, stage, address, length_words, 0, 0, extra0, 0
            )
        return self._response(request, status)

    def _addresses_allowed(self, address: int, count: int) -> bool:
        if self.faults.illegal_address or count <= 0:
            return False
        end = address + count
        return (
            APP_FLASH_START <= address
            and end <= APP_FLASH_END_EXCLUSIVE
            and not (address < SLOT_A_METADATA_END and end > SLOT_A_METADATA_START)
            and all(any(sector.contains(item) for sector in self.sectors) for item in range(address, end))
        )

    @staticmethod
    def _ram_allowed(address: int, count: int, *, executable: bool = False) -> bool:
        _ = executable
        if count <= 0:
            return False
        end = address + count
        if end < address:
            return False
        ranges = (
            (0x000000, 0x000002),
            (0x000123, 0x000400),
            (0x008000, 0x00C000),
            (0x010000, 0x01BFF8),
            (0x03F800, 0x040000),
            (0x049000, 0x049800),
            (0x04B000, 0x04B800),
        )
        return any(start <= address and end <= stop for start, stop in ranges)

    def _protocol_info(self) -> tuple[int, ...]:
        return (
            PROTOCOL_VERSION,
            PROTOCOL_VERSION,
            PROTOCOL_VERSION,
            10,
            1,
            1,
            self.device_info.max_payload_words,
            0,
        )

    def transact(self, request: Frame) -> Frame:
        if request.packet_type != PacketType.REQUEST:
            return self._fail(request, Status.BAD_PACKET_TYPE, ErrorOperation.FRAME, ErrorStage.HEADER)
        if request.protocol_version != PROTOCOL_VERSION:
            return self._fail(
                request, Status.UNSUPPORTED_PROTOCOL, ErrorOperation.FRAME, ErrorStage.HEADER
            )
        if request.flags:
            return self._fail(request, Status.BAD_FLAGS, ErrorOperation.FRAME, ErrorStage.HEADER)

        try:
            command = Command(request.command)
        except ValueError:
            return self._fail(
                request, Status.UNKNOWN_COMMAND, ErrorOperation.FRAME, ErrorStage.STATE
            )

        if self.require_service_for_flash_commands and command in {
            Command.ERASE,
            Command.PROGRAM_BEGIN,
            Command.PROGRAM_DATA,
            Command.PROGRAM_END,
            Command.VERIFY_BEGIN,
            Command.VERIFY_DATA,
            Command.VERIFY_END,
            Command.METADATA_APPEND_RECORD,
        } and self.service_state != ServiceState.ATTACHED:
            return self._fail(
                request,
                Status.UNSUPPORTED_FEATURE,
                ErrorOperation.FRAME,
                ErrorStage.STATE,
            )

        handlers = {
            Command.PING: self._ping,
            Command.GET_DEVICE_INFO: self._get_device_info,
            Command.GET_PROTOCOL_INFO: self._get_protocol_info,
            Command.GET_LAST_ERROR: self._get_last_error,
            Command.GET_SERVICE_STATUS: self._get_service_status,
            Command.SERVICE_ATTACH: self._service_attach,
            Command.RAM_LOAD_BEGIN: self._ram_load_begin,
            Command.RAM_LOAD_DATA: self._ram_load_data,
            Command.RAM_LOAD_END: self._ram_load_end,
            Command.RAM_CHECK_CRC: self._ram_check_crc,
            Command.RUN_RAM: self._run_ram,
            Command.GET_METADATA_SUMMARY: self._get_metadata_summary,
            Command.METADATA_APPEND_RECORD: self._metadata_append_record,
            Command.ERASE: self._erase,
            Command.PROGRAM_BEGIN: self._program_begin,
            Command.PROGRAM_DATA: self._program_data,
            Command.PROGRAM_END: self._program_end,
            Command.VERIFY_BEGIN: self._verify_begin,
            Command.VERIFY_DATA: self._verify_data,
            Command.VERIFY_END: self._verify_end,
            Command.FLASH_READ: self._flash_read,
            Command.RUN: self._run,
            Command.RESET: self._reset,
        }
        handler = handlers.get(command)
        if handler is None:
            return self._fail(
                request, Status.UNSUPPORTED_COMMAND, ErrorOperation.FRAME, ErrorStage.STATE
            )
        return handler(request)

    def _require_empty(self, request: Frame, operation: ErrorOperation) -> Frame | None:
        if request.payload:
            return self._fail(
                request, Status.BAD_PAYLOAD_LENGTH, operation, ErrorStage.PAYLOAD
            )
        return None

    def _ping(self, request: Frame) -> Frame:
        return self._require_empty(request, ErrorOperation.FRAME) or self._response(request)

    def _get_device_info(self, request: Frame) -> Frame:
        return self._require_empty(request, ErrorOperation.FRAME) or self._response(
            request, payload=self.device_info.to_words()
        )

    def _get_protocol_info(self, request: Frame) -> Frame:
        return self._require_empty(request, ErrorOperation.FRAME) or self._response(
            request, payload=self._protocol_info()
        )

    def _get_last_error(self, request: Frame) -> Frame:
        return self._require_empty(request, ErrorOperation.FRAME) or self._response(
            request, payload=self.last_error.to_words()
        )

    def _get_service_status(self, request: Frame) -> Frame:
        error = self._require_empty(request, ErrorOperation.FRAME)
        if error:
            return error
        cap_low, cap_high = split_u32(self.service_capabilities)
        crc = crc32_words(self.ram_loaded.crc_words) if self.ram_loaded is not None else 0
        words = self.ram_loaded.total_words if self.ram_loaded is not None else 0
        crc_low, crc_high = split_u32(crc)
        words_low, words_high = split_u32(words)
        return self._response(
            request,
            payload=(
                self.service_state,
                1,
                0,
                self.service_major,
                self.service_minor,
                cap_low,
                cap_high,
                self.service_last_attach_status,
                crc_low,
                crc_high,
                words_low,
                words_high,
            ),
        )

    def _service_fail(self, request: Frame, status: Status, *, address: int = 0) -> Frame:
        self.service_state = ServiceState.ERROR
        self.service_last_attach_status = status
        return self._fail(
            request,
            status,
            ErrorOperation.RAM_LOAD,
            ErrorStage.STATE,
            address=address,
        )

    def _read_ram_words(self, address: int, count: int) -> tuple[int, ...] | None:
        if self.ram_loaded is None or self.ram_loaded.start is None or self.ram_loaded.end_exclusive is None:
            return None
        if count <= 0 or address < self.ram_loaded.start or address + count > self.ram_loaded.end_exclusive:
            return None
        try:
            return tuple(self.ram[address + index] for index in range(count))
        except KeyError:
            return None

    def _service_attach(self, request: Frame) -> Frame:
        if len(request.payload) != 7:
            return self._service_fail(request, Status.BAD_PAYLOAD_LENGTH)
        if request.payload[6]:
            return self._service_fail(request, Status.BAD_FLAGS)
        session = self.ram_loaded
        descriptor_address = join_u32(request.payload[0], request.payload[1])
        expected_crc = join_u32(request.payload[2], request.payload[3])
        expected_words = join_u32(request.payload[4], request.payload[5])
        if session is None or not self.ram_crc_ok:
            return self._service_fail(request, Status.INVALID_STATE, address=descriptor_address)
        actual_crc = crc32_words(session.crc_words)
        if expected_crc != actual_crc or expected_words != session.total_words:
            return self._service_fail(request, Status.VERIFY_MISMATCH, address=descriptor_address)
        descriptor = self._read_ram_words(descriptor_address, SERVICE_DESCRIPTOR_WORDS)
        if descriptor is None:
            return self._service_fail(request, Status.RAM_REGION_ERROR, address=descriptor_address)
        if (
            join_u32(descriptor[0], descriptor[1]) != SERVICE_DESCRIPTOR_MAGIC
            or descriptor[2] != SERVICE_DESCRIPTOR_VERSION
            or descriptor[3] != SERVICE_DESCRIPTOR_WORDS
            or crc32_words(descriptor[:18]) != join_u32(descriptor[18], descriptor[19])
        ):
            return self._service_fail(request, Status.METADATA_INVALID, address=descriptor_address)
        if descriptor[4] != 1 or descriptor[5] > 0:
            return self._service_fail(request, Status.UNSUPPORTED_PROTOCOL, address=descriptor_address)
        api_address = join_u32(descriptor[8], descriptor[9])
        image_start = join_u32(descriptor[10], descriptor[11])
        image_end = join_u32(descriptor[12], descriptor[13])
        image_crc = join_u32(descriptor[14], descriptor[15])
        capabilities = join_u32(descriptor[16], descriptor[17])
        if (
            self._read_ram_words(api_address, 1) is None
            or image_end <= image_start
            or self._read_ram_words(image_start, image_end - image_start) is None
            or image_crc != actual_crc
            or (capabilities & int(SERVICE_REQUIRED_CAPABILITIES)) != int(SERVICE_REQUIRED_CAPABILITIES)
        ):
            return self._service_fail(request, Status.UNSUPPORTED_FEATURE, address=descriptor_address)
        self.service_state = ServiceState.ATTACHED
        self.service_last_attach_status = Status.OK
        self.service_major = descriptor[6]
        self.service_minor = descriptor[7]
        self.service_capabilities = capabilities
        return self._response(request)

    def _metadata_record(self, index: int) -> tuple[int, ...]:
        base = SLOT_A_METADATA_START + index * METADATA_RECORD_WORDS
        return tuple(self.flash.get(base + word, 0xFFFF) for word in range(METADATA_RECORD_WORDS))

    @staticmethod
    def _metadata_erased(record: Sequence[int]) -> bool:
        return all(word == 0xFFFF for word in record)

    def _metadata_summary_payload(self) -> tuple[int, ...]:
        erased = 0
        invalid = 0
        first_free = 0xFFFF
        latest: tuple[int, ...] | None = None
        latest_image: tuple[int, ...] | None = None
        valid_records: list[tuple[int, ...]] = []
        for index in range(METADATA_RECORD_COUNT):
            record = self._metadata_record(index)
            if self._metadata_erased(record):
                erased += 1
                if first_free == 0xFFFF:
                    first_free = index
                continue
            if (
                record[0] != METADATA_MAGIC0
                or record[1] != METADATA_MAGIC1
                or record[2] != METADATA_RECORD_VERSION
                or record[3] != METADATA_RECORD_WORDS
                or record[4] not in (MetadataRecordType.IMAGE_VALID, MetadataRecordType.BOOT_ATTEMPT)
                or crc32_words(record[:62]) != join_u32(record[62], record[63])
            ):
                invalid += 1
                continue
            valid_records.append(record)
            if latest is None or join_u32(record[5], record[6]) > join_u32(latest[5], latest[6]):
                latest = record
            if record[4] == MetadataRecordType.IMAGE_VALID and (
                latest_image is None
                or join_u32(record[5], record[6]) > join_u32(latest_image[5], latest_image[6])
            ):
                latest_image = record
        if latest_image is None:
            state = 0 if invalid == 0 else 2
            valid = 0
            metadata_valid = 0
            latest_type = 0
            entry_low = entry_high = crc_low = crc_high = size_low = size_high = 0
            version = (0, 0, 0, 0, 0)
            target = (0, 0)
        else:
            state = 1
            valid = len(valid_records)
            metadata_valid = 1
            assert latest is not None
            latest_type = latest[4]
            entry_low, entry_high = latest_image[14], latest_image[15]
            crc_low, crc_high = latest_image[18], latest_image[19]
            size_low, size_high = latest_image[16], latest_image[17]
            version = (latest_image[20], latest_image[21], latest_image[22], latest_image[23], latest_image[24])
            target = (latest_image[25], latest_image[26])
            image_sequence = join_u32(latest_image[5], latest_image[6])
            attempt_count = sum(
                1
                for record in valid_records
                if record[4] == MetadataRecordType.BOOT_ATTEMPT
                and join_u32(record[5], record[6]) > image_sequence
            )
        return (
            metadata_valid, BootSlot.SLOT_A if metadata_valid else 0, latest_type,
            attempt_count if metadata_valid else 0, 0, 3,
            *version,
            entry_low, entry_high,
            crc_low, crc_high,
            state,
            valid, invalid, erased, erased, first_free,
            size_low, size_high,
            *target,
        )

    def _summary(self) -> MetadataSummary:
        return MetadataSummary.from_words(self._metadata_summary_payload())

    def _get_metadata_summary(self, request: Frame) -> Frame:
        error = self._require_empty(request, ErrorOperation.FRAME)
        if error:
            return error
        return self._response(request, payload=self._metadata_summary_payload())

    @staticmethod
    def _build_image_valid_record(payload: Sequence[int], sequence: int, device: DeviceInfo) -> tuple[int, ...]:
        record = [0xFFFF] * METADATA_RECORD_WORDS
        record[0] = METADATA_MAGIC0
        record[1] = METADATA_MAGIC1
        record[2] = METADATA_RECORD_VERSION
        record[3] = METADATA_RECORD_WORDS
        record[4] = MetadataRecordType.IMAGE_VALID
        record[5], record[6] = split_u32(sequence)
        record[7] = BootSlot.SLOT_A
        record[8] = BootSlot.SLOT_A
        record[9] = 0
        record[10], record[11] = split_u32(APP_FLASH_START)
        record[12], record[13] = payload[13], payload[14]
        record[14], record[15] = payload[2], payload[3]
        record[16], record[17] = payload[4], payload[5]
        record[18], record[19] = payload[6], payload[7]
        record[20], record[21], record[22] = payload[8], payload[9], payload[10]
        record[23], record[24] = payload[11], payload[12]
        record[25] = int(device.device_id)
        record[26] = int(device.cpu_id)
        record[27] = METADATA_BOOT_ATTEMPT_LIMIT
        record[28] = 0
        record[62], record[63] = split_u32(crc32_words(record[:62]))
        return tuple(record)

    @staticmethod
    def _build_boot_attempt_record(summary, sequence: int) -> tuple[int, ...]:
        record = [0xFFFF] * METADATA_RECORD_WORDS
        record[0] = METADATA_MAGIC0
        record[1] = METADATA_MAGIC1
        record[2] = METADATA_RECORD_VERSION
        record[3] = METADATA_RECORD_WORDS
        record[4] = MetadataRecordType.BOOT_ATTEMPT
        record[5], record[6] = split_u32(sequence)
        record[7] = BootSlot.SLOT_A
        record[8] = BootSlot.SLOT_A
        record[9] = 0
        record[10], record[11] = split_u32(APP_FLASH_START)
        record[12], record[13] = split_u32(APP_FLASH_END_EXCLUSIVE)
        record[14], record[15] = split_u32(summary.entry_point)
        record[16], record[17] = split_u32(summary.image_size_words)
        record[18], record[19] = split_u32(summary.image_crc32)
        record[20] = summary.app_version_major
        record[21] = summary.app_version_minor
        record[22] = summary.app_version_patch
        record[23], record[24] = split_u32(summary.app_version_build)
        record[25] = summary.target_device_id
        record[26] = summary.target_cpu_id
        record[27] = summary.boot_attempt_limit
        record[28] = summary.boot_attempt_count + 1
        record[62], record[63] = split_u32(crc32_words(record[:62]))
        return tuple(record)

    def _metadata_append_record(self, request: Frame) -> Frame:
        if len(request.payload) != 16:
            return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.PROGRAM, ErrorStage.PAYLOAD)
        if request.payload[0] not in (MetadataRecordType.IMAGE_VALID, MetadataRecordType.BOOT_ATTEMPT):
            return self._fail(request, Status.UNSUPPORTED_FEATURE, ErrorOperation.PROGRAM, ErrorStage.PAYLOAD)
        if request.payload[1] != BootSlot.SLOT_A:
            return self._fail(request, Status.UNSUPPORTED_FEATURE, ErrorOperation.PROGRAM, ErrorStage.PAYLOAD)
        if request.payload[15]:
            return self._fail(request, Status.BAD_FLAGS, ErrorOperation.PROGRAM, ErrorStage.PAYLOAD)
        if request.payload[0] == MetadataRecordType.BOOT_ATTEMPT:
            if any(request.payload[index] for index in range(8, 15)):
                return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.PROGRAM, ErrorStage.PAYLOAD)
            summary = self._summary()
            if not summary.metadata_valid:
                return self._fail(request, Status.METADATA_INVALID, ErrorOperation.PROGRAM, ErrorStage.STATE)
            if summary.app_confirmed:
                return self._response(request)
            if summary.boot_attempt_count >= summary.boot_attempt_limit:
                return self._fail(request, Status.ATTEMPT_LIMIT_REACHED, ErrorOperation.PROGRAM, ErrorStage.STATE)
            if (
                join_u32(request.payload[2], request.payload[3]) != summary.entry_point
                or join_u32(request.payload[4], request.payload[5]) != summary.image_size_words
                or join_u32(request.payload[6], request.payload[7]) != summary.image_crc32
            ):
                return self._fail(request, Status.METADATA_INVALID, ErrorOperation.PROGRAM, ErrorStage.STATE)
            first_free = next(
                (index for index in range(METADATA_RECORD_COUNT) if self._metadata_erased(self._metadata_record(index))),
                None,
            )
            if first_free is None:
                return self._fail(request, Status.METADATA_FULL, ErrorOperation.PROGRAM, ErrorStage.STATE)
            sequence = 1 + max(
                (join_u32(self._metadata_record(index)[5], self._metadata_record(index)[6])
                 for index in range(METADATA_RECORD_COUNT)
                 if not self._metadata_erased(self._metadata_record(index))),
                default=0,
            )
            record = self._build_boot_attempt_record(summary, sequence)
            base = SLOT_A_METADATA_START + first_free * METADATA_RECORD_WORDS
            self.flash.update({base + index: word for index, word in enumerate(record)})
            return self._response(request)
        entry_point = join_u32(request.payload[2], request.payload[3])
        image_size_words = join_u32(request.payload[4], request.payload[5])
        app_end = join_u32(request.payload[13], request.payload[14])
        if image_size_words == 0:
            return self._fail(request, Status.BAD_WORD_COUNT, ErrorOperation.PROGRAM, ErrorStage.PAYLOAD)
        if entry_point < APP_FLASH_START or entry_point >= APP_FLASH_END_EXCLUSIVE or entry_point % 8:
            return self._fail(request, Status.BAD_ADDRESS, ErrorOperation.PROGRAM, ErrorStage.ADDRESS_CHECK)
        if app_end <= APP_FLASH_START or app_end > APP_FLASH_END_EXCLUSIVE:
            return self._fail(request, Status.BAD_ADDRESS, ErrorOperation.PROGRAM, ErrorStage.ADDRESS_CHECK)
        if not self.verify_succeeded:
            return self._fail(request, Status.INVALID_STATE, ErrorOperation.PROGRAM, ErrorStage.STATE)
        first_free = next(
            (index for index in range(METADATA_RECORD_COUNT) if self._metadata_erased(self._metadata_record(index))),
            None,
        )
        if first_free is None:
            return self._fail(request, Status.METADATA_FULL, ErrorOperation.PROGRAM, ErrorStage.STATE)
        sequence = 1 + max(
            (join_u32(self._metadata_record(index)[5], self._metadata_record(index)[6])
             for index in range(METADATA_RECORD_COUNT)
             if not self._metadata_erased(self._metadata_record(index))),
            default=0,
        )
        record = self._build_image_valid_record(request.payload, sequence, self.device_info)
        base = SLOT_A_METADATA_START + first_free * METADATA_RECORD_WORDS
        self.flash.update({base + index: word for index, word in enumerate(record)})
        self.verify_succeeded = False
        return self._response(request)

    def _ram_load_begin(self, request: Frame) -> Frame:
        if len(request.payload) != 9:
            return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.RAM_LOAD, ErrorStage.PAYLOAD)
        target, block_count = request.payload[:2]
        total_words = join_u32(request.payload[2], request.payload[3])
        entry_point = join_u32(request.payload[4], request.payload[5])
        if request.payload[8]:
            return self._fail(request, Status.BAD_FLAGS, ErrorOperation.RAM_LOAD, ErrorStage.PAYLOAD)
        if self.ram_load_session is not None:
            return self._fail(request, Status.BUSY, ErrorOperation.RAM_LOAD, ErrorStage.STATE)
        if target != Target.RAM_APP:
            return self._fail(request, Status.TARGET_MISMATCH, ErrorOperation.RAM_LOAD, ErrorStage.STATE)
        if block_count == 0 or total_words == 0:
            return self._fail(request, Status.BAD_WORD_COUNT, ErrorOperation.RAM_LOAD, ErrorStage.PAYLOAD)
        if not self._ram_allowed(entry_point, 1, executable=True):
            return self._fail(request, Status.RAM_REGION_ERROR, ErrorOperation.RAM_LOAD, ErrorStage.ADDRESS_CHECK, address=entry_point)
        self.ram_load_session = _Session(block_count, total_words, entry_point, [])
        self.ram_loaded = None
        self.ram_crc_ok = False
        self.service_state = ServiceState.DETACHED
        self.service_last_attach_status = Status.OK
        self.service_major = 0
        self.service_minor = 0
        self.service_capabilities = 0
        return self._response(request)

    def _ram_load_data(self, request: Frame) -> Frame:
        session = self.ram_load_session
        if session is None:
            return self._fail(request, Status.MISSING_BEGIN, ErrorOperation.RAM_LOAD, ErrorStage.STATE)
        if len(request.payload) < 5:
            self.ram_load_session = None
            return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.RAM_LOAD, ErrorStage.PAYLOAD)
        address = join_u32(request.payload[0], request.payload[1])
        word_count = request.payload[2]
        block_index = join_u32(request.payload[3], request.payload[4])
        data = tuple(request.payload[5:])
        if len(data) != word_count:
            self.ram_load_session = None
            return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.RAM_LOAD, ErrorStage.PAYLOAD, address=address, length_words=word_count)
        if word_count == 0:
            self.ram_load_session = None
            return self._fail(request, Status.BAD_WORD_COUNT, ErrorOperation.RAM_LOAD, ErrorStage.PAYLOAD, address=address)
        if block_index != session.expected_index:
            self.ram_load_session = None
            return self._fail(request, Status.BLOCK_INDEX_ERROR, ErrorOperation.RAM_LOAD, ErrorStage.STATE, address=address, length_words=word_count, extra0=session.expected_index)
        if session.packet_count >= session.block_count or session.received_words + word_count > session.total_words:
            self.ram_load_session = None
            return self._fail(request, Status.TOTAL_COUNT_MISMATCH, ErrorOperation.RAM_LOAD, ErrorStage.STATE, address=address, length_words=word_count)
        if not self._ram_allowed(address, word_count):
            self.ram_load_session = None
            return self._fail(request, Status.RAM_REGION_ERROR, ErrorOperation.RAM_LOAD, ErrorStage.ADDRESS_CHECK, address=address, length_words=word_count)
        self.ram.update({address + index: word for index, word in enumerate(data)})
        session.crc_words.extend(data)
        session.expected_index += 1
        session.packet_count += 1
        session.received_words += word_count
        session.start = address if session.start is None else min(session.start, address)
        session.end_exclusive = (
            address + word_count if session.end_exclusive is None
            else max(session.end_exclusive, address + word_count)
        )
        return self._response(request)

    def _ram_load_end(self, request: Frame) -> Frame:
        session = self.ram_load_session
        if session is None:
            return self._fail(request, Status.MISSING_BEGIN, ErrorOperation.RAM_LOAD, ErrorStage.STATE)
        if len(request.payload) != 6:
            self.ram_load_session = None
            return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.RAM_LOAD, ErrorStage.PAYLOAD)
        packets = join_u32(request.payload[0], request.payload[1])
        words = join_u32(request.payload[2], request.payload[3])
        if (
            packets != session.block_count
            or packets != session.packet_count
            or words != session.total_words
            or words != session.received_words
            or session.start is None
            or session.end_exclusive is None
            or not (session.start <= session.entry_point < session.end_exclusive)
        ):
            self.ram_load_session = None
            return self._fail(request, Status.TOTAL_COUNT_MISMATCH, ErrorOperation.RAM_LOAD, ErrorStage.STATE)
        self.ram_loaded = session
        self.ram_load_session = None
        self.ram_crc_ok = False
        self.service_state = ServiceState.RAM_LOADED
        return self._response(request)

    def _ram_check_crc(self, request: Frame) -> Frame:
        if len(request.payload) != 5:
            return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.RAM_LOAD, ErrorStage.PAYLOAD)
        if request.payload[4]:
            return self._fail(request, Status.BAD_FLAGS, ErrorOperation.RAM_LOAD, ErrorStage.PAYLOAD)
        session = self.ram_loaded
        if session is None:
            return self._fail(request, Status.INVALID_STATE, ErrorOperation.RAM_LOAD, ErrorStage.STATE)
        expected_crc = join_u32(request.payload[0], request.payload[1])
        expected_words = join_u32(request.payload[2], request.payload[3])
        actual_crc = crc32_words(session.crc_words)
        if expected_words != session.total_words or expected_crc != actual_crc:
            self.ram_crc_ok = False
            return self._fail(request, Status.VERIFY_MISMATCH, ErrorOperation.RAM_LOAD, ErrorStage.VERIFY, length_words=session.total_words, extra0=actual_crc & 0xFFFF)
        self.ram_crc_ok = True
        self.service_state = ServiceState.RAM_LOADED
        return self._response(request)

    def _run_ram(self, request: Frame) -> Frame:
        if len(request.payload) != 3:
            return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.RUN, ErrorStage.PAYLOAD)
        if request.payload[2]:
            return self._fail(request, Status.BAD_FLAGS, ErrorOperation.RUN, ErrorStage.PAYLOAD)
        session = self.ram_loaded
        if session is None or not self.ram_crc_ok:
            return self._fail(request, Status.INVALID_STATE, ErrorOperation.RUN, ErrorStage.STATE)
        entry_point = join_u32(request.payload[0], request.payload[1]) or session.entry_point
        if (
            session.start is None
            or session.end_exclusive is None
            or not (session.start <= entry_point < session.end_exclusive)
            or not self._ram_allowed(entry_point, 1, executable=True)
        ):
            return self._fail(request, Status.RAM_REGION_ERROR, ErrorOperation.RUN, ErrorStage.ADDRESS_CHECK, address=entry_point)
        self.pending_action = SimulatorAction.RUN_RAM
        return self._response(request)

    def _erase(self, request: Frame) -> Frame:
        if len(request.payload) != 3:
            return self._fail(
                request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.ERASE, ErrorStage.PAYLOAD
            )
        mask = join_u32(request.payload[0], request.payload[1])
        if request.payload[2]:
            return self._fail(request, Status.BAD_FLAGS, ErrorOperation.ERASE, ErrorStage.PAYLOAD)
        valid_mask = (1 << len(self.sectors)) - 1
        if mask == 0 or mask & ~valid_mask:
            return self._fail(
                request, Status.BAD_ADDRESS, ErrorOperation.ERASE, ErrorStage.ADDRESS_CHECK
            )
        if self.faults.erase_fail:
            return self._fail(
                request, Status.ERASE_FAILED, ErrorOperation.ERASE, ErrorStage.API_CALL
            )
        selected = [sector for index, sector in enumerate(self.sectors) if mask & (1 << index)]
        for address in tuple(self.flash):
            if any(sector.contains(address) for sector in selected):
                del self.flash[address]
        self.programmed_addresses.difference_update(
            address
            for sector in selected
            for address in range(sector.start, sector.end_exclusive)
        )
        self.program_session = None
        self.verify_session = None
        self.verify_succeeded = False
        return self._response(request)

    def _begin(self, request: Frame, operation: ErrorOperation) -> tuple[_Session | None, Frame | None]:
        if len(request.payload) != 9:
            return None, self._fail(
                request, Status.BAD_PAYLOAD_LENGTH, operation, ErrorStage.PAYLOAD
            )
        target, block_count = request.payload[:2]
        total_words = join_u32(request.payload[2], request.payload[3])
        entry_point = join_u32(request.payload[4], request.payload[5])
        flags = request.payload[8]
        if flags:
            return None, self._fail(request, Status.BAD_FLAGS, operation, ErrorStage.PAYLOAD)
        if target != Target.FLASH_APP:
            return None, self._fail(
                request, Status.TARGET_MISMATCH, operation, ErrorStage.STATE
            )
        if block_count == 0 or total_words == 0:
            return None, self._fail(
                request, Status.BAD_WORD_COUNT, operation, ErrorStage.PAYLOAD
            )
        if not self._addresses_allowed(entry_point, 1):
            return None, self._fail(
                request,
                Status.ADDRESS_OUT_OF_RANGE,
                operation,
                ErrorStage.ADDRESS_CHECK,
                address=entry_point,
            )
        return _Session(block_count, total_words, entry_point, []), None

    def _program_begin(self, request: Frame) -> Frame:
        if self.program_session is not None:
            return self._fail(
                request, Status.BUSY, ErrorOperation.PROGRAM, ErrorStage.STATE
            )
        session, error = self._begin(request, ErrorOperation.PROGRAM)
        if error:
            return error
        self.program_session = session
        return self._response(request)

    def _data(
        self,
        request: Frame,
        session: _Session | None,
        operation: ErrorOperation,
    ) -> tuple[int, tuple[int, ...], int, Frame | None]:
        if session is None:
            return 0, (), 0, self._fail(
                request, Status.MISSING_BEGIN, operation, ErrorStage.STATE
            )
        if len(request.payload) < 5:
            return 0, (), 0, self._fail(
                request, Status.BAD_PAYLOAD_LENGTH, operation, ErrorStage.PAYLOAD
            )
        address = join_u32(request.payload[0], request.payload[1])
        data_words = request.payload[2]
        block_index = join_u32(request.payload[3], request.payload[4])
        data = tuple(request.payload[5:])
        if len(request.payload) != 5 + data_words:
            return address, data, block_index, self._fail(
                request,
                Status.BAD_PAYLOAD_LENGTH,
                operation,
                ErrorStage.PAYLOAD,
                address=address,
                length_words=data_words,
            )
        try:
            validate_write_data(data, max_data_words=self.device_info.max_data_words)
        except DataAlignmentError:
            return address, data, block_index, self._fail(
                request,
                Status.BAD_WORD_COUNT,
                operation,
                ErrorStage.PAYLOAD,
                address=address,
                length_words=data_words,
            )
        if self.faults.bad_block_index or block_index != session.expected_index:
            return address, data, block_index, self._fail(
                request,
                Status.BLOCK_INDEX_ERROR,
                operation,
                ErrorStage.STATE,
                address=address,
                length_words=data_words,
                extra0=session.expected_index & 0xFFFF,
            )
        if not self._addresses_allowed(address, data_words):
            return address, data, block_index, self._fail(
                request,
                Status.ADDRESS_OUT_OF_RANGE,
                operation,
                ErrorStage.ADDRESS_CHECK,
                address=address,
                length_words=data_words,
            )
        return address, data, block_index, None

    @staticmethod
    def _advance(session: _Session, data_words: int) -> None:
        session.expected_index += 1
        session.packet_count += 1
        session.received_words += data_words

    def _program_data(self, request: Frame) -> Frame:
        session = self.program_session
        address, data, _, error = self._data(request, session, ErrorOperation.PROGRAM)
        if error:
            self.program_session = None
            return error
        assert session is not None
        if self.faults.program_fail_at_address is not None and (
            address <= self.faults.program_fail_at_address < address + len(data)
        ):
            self.program_session = None
            return self._fail(
                request,
                Status.PROGRAM_FAILED,
                ErrorOperation.PROGRAM,
                ErrorStage.API_CALL,
                address=self.faults.program_fail_at_address,
                length_words=len(data),
            )
        if any(address + index in self.programmed_addresses for index in range(len(data))):
            self.program_session = None
            return self._fail(
                request,
                Status.REPROGRAM_FORBIDDEN,
                ErrorOperation.PROGRAM,
                ErrorStage.ADDRESS_CHECK,
                address=address,
                length_words=len(data),
            )
        self.flash.update({address + index: word for index, word in enumerate(data)})
        self.programmed_addresses.update(range(address, address + len(data)))
        self._advance(session, len(data))
        self.verify_succeeded = False
        return self._response(request)

    def _end(
        self, request: Frame, session: _Session | None, operation: ErrorOperation
    ) -> Frame:
        if session is None:
            return self._fail(request, Status.MISSING_BEGIN, operation, ErrorStage.STATE)
        if len(request.payload) != 6:
            return self._fail(
                request, Status.BAD_PAYLOAD_LENGTH, operation, ErrorStage.PAYLOAD
            )
        packets = join_u32(request.payload[0], request.payload[1])
        words = join_u32(request.payload[2], request.payload[3])
        if (
            packets != session.block_count
            or packets != session.packet_count
            or words != session.total_words
            or words != session.received_words
        ):
            return self._fail(
                request, Status.TOTAL_COUNT_MISMATCH, operation, ErrorStage.STATE
            )
        return self._response(request)

    def _program_end(self, request: Frame) -> Frame:
        response = self._end(request, self.program_session, ErrorOperation.PROGRAM)
        self.program_session = None
        if response.status == Status.OK:
            self.verify_succeeded = False
        return response

    def _verify_begin(self, request: Frame) -> Frame:
        if self.verify_session is not None:
            return self._fail(request, Status.BUSY, ErrorOperation.VERIFY, ErrorStage.STATE)
        session, error = self._begin(request, ErrorOperation.VERIFY)
        if error:
            return error
        self.verify_session = session
        return self._response(request)

    def _verify_data(self, request: Frame) -> Frame:
        session = self.verify_session
        address, data, _, error = self._data(request, session, ErrorOperation.VERIFY)
        if error:
            self.verify_session = None
            self.verify_succeeded = False
            return error
        assert session is not None
        for index, expected in enumerate(data):
            current = address + index
            if self.faults.verify_fail_at_address == current or self.flash.get(current, 0xFFFF) != expected:
                self.verify_session = None
                self.verify_succeeded = False
                return self._fail(
                    request,
                    Status.VERIFY_MISMATCH,
                    ErrorOperation.VERIFY,
                    ErrorStage.VERIFY,
                    address=current,
                    length_words=1,
                    extra0=self.flash.get(current, 0xFFFF),
                )
        self._advance(session, len(data))
        return self._response(request)

    def _verify_end(self, request: Frame) -> Frame:
        response = self._end(request, self.verify_session, ErrorOperation.VERIFY)
        self.verify_session = None
        self.verify_succeeded = response.status == Status.OK
        return response

    def _flash_read(self, request: Frame) -> Frame:
        if len(request.payload) != 5:
            return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.FRAME, ErrorStage.PAYLOAD)
        read_target = request.payload[0]
        address = join_u32(request.payload[1], request.payload[2])
        word_count = request.payload[3]
        if request.payload[4]:
            return self._fail(request, Status.BAD_FLAGS, ErrorOperation.FRAME, ErrorStage.PAYLOAD)
        if read_target != ReadTarget.METADATA:
            return self._fail(request, Status.UNSUPPORTED_FEATURE, ErrorOperation.FRAME, ErrorStage.STATE)
        if word_count == 0 or word_count > self.device_info.max_payload_words - 3:
            return self._fail(request, Status.BAD_WORD_COUNT, ErrorOperation.FRAME, ErrorStage.PAYLOAD)
        end = address + word_count
        if address < SLOT_A_METADATA_START or end > SLOT_A_METADATA_END:
            return self._fail(
                request,
                Status.ADDRESS_OUT_OF_RANGE,
                ErrorOperation.FRAME,
                ErrorStage.ADDRESS_CHECK,
                address=address,
                length_words=word_count,
            )
        return self._response(
            request,
            payload=(request.payload[1], request.payload[2], word_count, *(
                self.flash.get(address + index, 0xFFFF) for index in range(word_count)
            )),
        )

    def _run(self, request: Frame) -> Frame:
        if len(request.payload) != 4:
            return self._fail(request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.RUN, ErrorStage.PAYLOAD)
        target = request.payload[0]
        entry_point = join_u32(request.payload[1], request.payload[2])
        if request.payload[3]:
            return self._fail(request, Status.BAD_FLAGS, ErrorOperation.RUN, ErrorStage.PAYLOAD)
        if target != Target.FLASH_APP:
            return self._fail(request, Status.TARGET_MISMATCH, ErrorOperation.RUN, ErrorStage.STATE)
        if entry_point % 8:
            return self._fail(
                request,
                Status.BAD_ALIGNMENT,
                ErrorOperation.RUN,
                ErrorStage.ADDRESS_CHECK,
                address=entry_point,
            )
        if not self._addresses_allowed(entry_point, 1):
            return self._fail(
                request,
                Status.ADDRESS_OUT_OF_RANGE,
                ErrorOperation.RUN,
                ErrorStage.ADDRESS_CHECK,
                address=entry_point,
            )
        summary = self._summary()
        if not summary.metadata_valid or summary.entry_point != entry_point:
            return self._fail(request, Status.METADATA_INVALID, ErrorOperation.RUN, ErrorStage.STATE)
        if not summary.app_confirmed:
            if summary.boot_attempt_count == 0:
                return self._fail(request, Status.INVALID_STATE, ErrorOperation.RUN, ErrorStage.STATE)
            if summary.boot_attempt_count > summary.boot_attempt_limit:
                return self._fail(
                    request,
                    Status.ATTEMPT_LIMIT_REACHED,
                    ErrorOperation.RUN,
                    ErrorStage.STATE,
                )
        self.pending_action = SimulatorAction.RUN_APP
        return self._response(request)

    def _reset(self, request: Frame) -> Frame:
        error = self._require_empty(request, ErrorOperation.RESET)
        if error:
            return error
        self.pending_action = SimulatorAction.RESET_DEVICE
        return self._response(request)
