"""Stateful protocol-command simulator with sparse in-memory Flash."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from ..protocol.alignment import DataAlignmentError, validate_write_data
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
    Status,
    Target,
)
from ..protocol.frame import Frame
from ..protocol.models import DeviceInfo, ErrorDetail, join_u32


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
    RESET_DEVICE = "reset_device"


@dataclass(slots=True)
class _Session:
    block_count: int
    total_words: int
    entry_point: int
    expected_index: int = 0
    packet_count: int = 0
    received_words: int = 0


class SimulatorCore:
    def __init__(
        self,
        *,
        sectors: Sequence[FlashSector] | None = None,
        device_info: DeviceInfo | None = None,
        faults: SimulatorFaults | None = None,
    ) -> None:
        self.sectors = tuple(
            sectors
            or (
                FlashSector("FLASHA", 0x080000, 0x002000),
                FlashSector("FLASHB", 0x082000, 0x002000),
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
            int(Feature.ERASE | Feature.PROGRAM | Feature.VERIFY | Feature.RUN | Feature.RESET),
            256,
            248,
            BootMode.FLASH_KERNEL,
            KernelLayout.MONOLITHIC,
        )
        self.faults = faults or SimulatorFaults()
        self.flash: dict[int, int] = {}
        self.programmed_addresses: set[int] = set()
        self.last_error = ErrorDetail(0, 0, 0, 0, 0, 0, 0, 0)
        self.program_session: _Session | None = None
        self.verify_session: _Session | None = None
        self.pending_action = SimulatorAction.NONE

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
        return all(any(sector.contains(item) for sector in self.sectors) for item in range(address, address + count))

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

        handlers = {
            Command.PING: self._ping,
            Command.GET_DEVICE_INFO: self._get_device_info,
            Command.GET_PROTOCOL_INFO: self._get_protocol_info,
            Command.GET_LAST_ERROR: self._get_last_error,
            Command.ERASE: self._erase,
            Command.PROGRAM_BEGIN: self._program_begin,
            Command.PROGRAM_DATA: self._program_data,
            Command.PROGRAM_END: self._program_end,
            Command.VERIFY_BEGIN: self._verify_begin,
            Command.VERIFY_DATA: self._verify_data,
            Command.VERIFY_END: self._verify_end,
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
        return _Session(block_count, total_words, entry_point), None

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
            return error
        assert session is not None
        for index, expected in enumerate(data):
            current = address + index
            if self.faults.verify_fail_at_address == current or self.flash.get(current, 0xFFFF) != expected:
                self.verify_session = None
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
        return response

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
        self.pending_action = SimulatorAction.RUN_APP
        return self._response(request)

    def _reset(self, request: Frame) -> Frame:
        error = self._require_empty(request, ErrorOperation.RESET)
        if error:
            return error
        self.pending_action = SimulatorAction.RESET_DEVICE
        return self._response(request)
