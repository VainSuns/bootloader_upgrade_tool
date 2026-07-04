"""Erase/Program/Verify/DFU/Run/Reset orchestration above ProtocolClient."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Sequence

from ..firmware import crc32_words, validate_app_firmware_image, validate_ram_firmware_image
from ..firmware.models import AddressRange, FirmwareBlock, FirmwareImage
from ..io.base import IoTimeoutError
from ..protocol.alignment import pad_write_data
from ..protocol.constants import Command, ServiceState, Target
from ..protocol.models import ErrorDetail, ServiceStatus, split_u32
from .client import ProtocolClient, ProtocolStatusError


class WorkflowError(RuntimeError):
    pass


class DeviceState(Enum):
    READY = "ready"
    UNKNOWN = "unknown"


ProgressCallback = Callable[[str, int, int], None]

_COMMAND_TIMEOUT_MS = {
    Command.ERASE: 60_000,
    Command.PROGRAM_BEGIN: 10_000,
    Command.PROGRAM_DATA: 10_000,
    Command.PROGRAM_END: 10_000,
    Command.VERIFY_BEGIN: 10_000,
    Command.VERIFY_DATA: 10_000,
    Command.VERIFY_END: 10_000,
    Command.METADATA_APPEND_RECORD: 10_000,
    Command.RUN: 5_000,
    Command.RESET: 5_000,
    Command.RAM_LOAD_BEGIN: 10_000,
    Command.RAM_LOAD_DATA: 10_000,
    Command.RAM_LOAD_END: 10_000,
    Command.RAM_CHECK_CRC: 10_000,
    Command.RUN_RAM: 5_000,
    Command.SERVICE_ATTACH: 10_000,
    Command.GET_SERVICE_STATUS: 5_000,
}


@dataclass(frozen=True, slots=True)
class _DataPacket:
    address: int
    words: tuple[int, ...]
    index: int


def _merge_contiguous(blocks: Sequence[FirmwareBlock]) -> tuple[FirmwareBlock, ...]:
    if not blocks:
        return ()
    ordered = sorted(blocks, key=lambda block: block.address)
    merged: list[FirmwareBlock] = []
    address = ordered[0].address
    words = list(ordered[0].words)
    for block in ordered[1:]:
        if address + len(words) == block.address:
            words.extend(block.words)
        else:
            merged.append(FirmwareBlock(address, words))
            address, words = block.address, list(block.words)
    merged.append(FirmwareBlock(address, words))
    return tuple(merged)


def _prepare_packets(image: FirmwareImage, max_data_words: int) -> tuple[_DataPacket, ...]:
    packets: list[_DataPacket] = []
    for block in _merge_contiguous(image.blocks):
        offset = 0
        while offset < len(block.words):
            raw = block.words[offset : offset + max_data_words]
            data = pad_write_data(raw, max_data_words=max_data_words)
            packets.append(_DataPacket(block.address + offset, data, len(packets)))
            offset += len(raw)
    if len(packets) > 0xFFFF:
        raise WorkflowError("firmware requires more than 65535 protocol packets")
    return tuple(packets)


def calculate_programmed_image_crc32(image: FirmwareImage, max_data_words: int) -> int:
    words: list[int] = []
    for packet in _prepare_packets(image, max_data_words):
        words.extend(packet.words)
    return crc32_words(words)


def _prepare_ram_packets(image: FirmwareImage, max_data_words: int) -> tuple[_DataPacket, ...]:
    packets: list[_DataPacket] = []
    for block in _merge_contiguous(image.blocks):
        offset = 0
        while offset < len(block.words):
            data = tuple(block.words[offset : offset + max_data_words])
            packets.append(_DataPacket(block.address + offset, data, len(packets)))
            offset += len(data)
    if len(packets) > 0xFFFF:
        raise WorkflowError("RAM image requires more than 65535 protocol packets")
    return tuple(packets)


def calculate_ram_image_crc32(image: FirmwareImage, max_data_words: int) -> int:
    words: list[int] = []
    for packet in _prepare_ram_packets(image, max_data_words):
        words.extend(packet.words)
    return crc32_words(words)


def _programmed_image_size_and_end(image: FirmwareImage, max_data_words: int) -> tuple[int, int]:
    packets = _prepare_packets(image, max_data_words)
    if not packets:
        raise WorkflowError("firmware image has no programmable data")
    return (
        sum(len(packet.words) for packet in packets),
        max(packet.address + len(packet.words) for packet in packets),
    )


class UpgradeWorkflow:
    def __init__(
        self,
        client: ProtocolClient,
        *,
        allowed_flash_ranges: Sequence[AddressRange] = (),
        progress: ProgressCallback | None = None,
    ) -> None:
        self.client = client
        self.allowed_flash_ranges = tuple(allowed_flash_ranges)
        self.progress = progress or (lambda operation, current, total: None)
        self.state = DeviceState.READY
        self.flash_modified = False
        self.verify_succeeded = False
        self.last_probe_succeeded: bool | None = None
        self.last_error_detail: ErrorDetail | None = None

    def _transact(
        self, command: Command, payload: Sequence[int] = (), *, modifying: bool = False
    ) -> tuple[int, ...]:
        try:
            return self.client.transact(
                command, payload, timeout_ms=_COMMAND_TIMEOUT_MS[command]
            )
        except ProtocolStatusError:
            try:
                self.last_error_detail = self.client.get_last_error()
            except Exception:
                self.last_error_detail = None
            raise
        except IoTimeoutError:
            self.state = DeviceState.UNKNOWN
            if modifying:
                self.flash_modified = True
                self.verify_succeeded = False
            try:
                self.client.ping(timeout_ms=5000)
                self.last_probe_succeeded = True
            except Exception:
                self.last_probe_succeeded = False
            raise

    def erase(self, sector_mask: int) -> None:
        if sector_mask <= 0 or sector_mask > 0xFFFFFFFF:
            raise ValueError("sector_mask must be a nonzero uint32")
        self.flash_modified = True
        self.verify_succeeded = False
        low, high = split_u32(sector_mask)
        self._transact(Command.ERASE, (low, high, 0), modifying=True)

    def _transfer(
        self,
        image: FirmwareImage,
        *,
        begin_command: Command,
        data_command: Command,
        end_command: Command,
        operation: str,
        modifying: bool,
    ) -> None:
        info = self.client.device_info
        if info is None:
            raise WorkflowError("device information is not available; connect first")
        packets = _prepare_packets(image, info.max_data_words)
        total_words = sum(len(packet.words) for packet in packets)
        total_low, total_high = split_u32(total_words)
        entry_low, entry_high = split_u32(image.entry_point)
        self._transact(
            begin_command,
            (
                Target.FLASH_APP,
                len(packets),
                total_low,
                total_high,
                entry_low,
                entry_high,
                0,
                0,
                0,
            ),
            modifying=modifying,
        )
        for packet in packets:
            address_low, address_high = split_u32(packet.address)
            index_low, index_high = split_u32(packet.index)
            self._transact(
                data_command,
                (
                    address_low,
                    address_high,
                    len(packet.words),
                    index_low,
                    index_high,
                    *packet.words,
                ),
                modifying=modifying,
            )
            self.progress(operation, packet.index + 1, len(packets))
        packet_low, packet_high = split_u32(len(packets))
        self._transact(
            end_command,
            (packet_low, packet_high, total_low, total_high, 0, 0),
            modifying=modifying,
        )

    def program(self, image: FirmwareImage) -> None:
        validate_app_firmware_image(image)
        self.flash_modified = True
        self.verify_succeeded = False
        self._transfer(
            image,
            begin_command=Command.PROGRAM_BEGIN,
            data_command=Command.PROGRAM_DATA,
            end_command=Command.PROGRAM_END,
            operation="Program",
            modifying=True,
        )

    def verify(self, image: FirmwareImage) -> None:
        validate_app_firmware_image(image)
        self.verify_succeeded = False
        self._transfer(
            image,
            begin_command=Command.VERIFY_BEGIN,
            data_command=Command.VERIFY_DATA,
            end_command=Command.VERIFY_END,
            operation="Verify",
            modifying=False,
        )
        self.verify_succeeded = True
        self.state = DeviceState.READY

    def dfu(self, sector_mask: int, image: FirmwareImage) -> None:
        validate_app_firmware_image(image)
        self.erase(sector_mask)
        self.program(image)
        self.verify(image)
        info = self.client.device_info
        if info is None:
            raise WorkflowError("device information is not available; connect first")
        image_size_words, app_end = _programmed_image_size_and_end(image, info.max_data_words)
        try:
            self.client.metadata_append_image_valid(
                entry_point=image.entry_point,
                image_size_words=image_size_words,
                image_crc32=calculate_programmed_image_crc32(image, info.max_data_words),
                app_end=app_end,
                timeout_ms=_COMMAND_TIMEOUT_MS[Command.METADATA_APPEND_RECORD],
            )
        except Exception:
            self.verify_succeeded = False
            raise
        self.progress("Metadata", 1, 1)

    def _entry_allowed(self, image: FirmwareImage) -> bool:
        ranges = self.allowed_flash_ranges or image.address_ranges
        return any(item.start <= image.entry_point < item.end_exclusive for item in ranges)

    def run(self, image: FirmwareImage) -> None:
        validate_app_firmware_image(image)
        if image.entry_point % 8:
            raise WorkflowError("FLASH_APP entry point must be 8-word aligned")
        if not self._entry_allowed(image):
            raise WorkflowError("FLASH_APP entry point is outside the allowed Flash range")
        if self.flash_modified and not self.verify_succeeded:
            raise WorkflowError("Verify must succeed after Erase/Program/DFU before Run")
        summary = self.client.get_metadata_summary()
        if not summary.metadata_valid:
            raise WorkflowError("valid IMAGE_VALID metadata is required before Run")
        if summary.entry_point != image.entry_point:
            raise WorkflowError("metadata entry point does not match firmware image")
        if not summary.app_confirmed:
            if summary.boot_attempt_count >= summary.boot_attempt_limit:
                raise WorkflowError("boot attempt limit reached")
            self.client.metadata_append_boot_attempt(
                entry_point=summary.entry_point,
                image_size_words=summary.image_size_words,
                image_crc32=summary.image_crc32,
                timeout_ms=_COMMAND_TIMEOUT_MS[Command.METADATA_APPEND_RECORD],
            )
            self.progress("BootAttempt", 1, 1)
        entry_low, entry_high = split_u32(image.entry_point)
        self._transact(Command.RUN, (Target.FLASH_APP, entry_low, entry_high, 0))

    def reset(self) -> None:
        self._transact(Command.RESET)

    def ram_load(self, image: FirmwareImage) -> int:
        validate_ram_firmware_image(image)
        info = self.client.device_info
        if info is None:
            raise WorkflowError("device information is not available; connect first")
        packets = _prepare_ram_packets(image, info.max_data_words)
        total_words = sum(len(packet.words) for packet in packets)
        image_crc32 = calculate_ram_image_crc32(image, info.max_data_words)
        self.client.ram_load_begin(
            packet_count=len(packets),
            total_words=total_words,
            entry_point=image.entry_point,
            image_crc32=image_crc32,
            timeout_ms=_COMMAND_TIMEOUT_MS[Command.RAM_LOAD_BEGIN],
        )
        for packet in packets:
            self.client.ram_load_data(
                address=packet.address,
                words=packet.words,
                packet_index=packet.index,
                timeout_ms=_COMMAND_TIMEOUT_MS[Command.RAM_LOAD_DATA],
            )
            self.progress("RamLoad", packet.index + 1, len(packets))
        self.client.ram_load_end(
            packet_count=len(packets),
            total_words=total_words,
            image_crc32=image_crc32,
            timeout_ms=_COMMAND_TIMEOUT_MS[Command.RAM_LOAD_END],
        )
        return image_crc32

    def ram_check_crc(self, image: FirmwareImage) -> int:
        validate_ram_firmware_image(image)
        info = self.client.device_info
        if info is None:
            raise WorkflowError("device information is not available; connect first")
        image_crc32 = calculate_ram_image_crc32(image, info.max_data_words)
        self.client.ram_check_crc(
            expected_crc32=image_crc32,
            expected_total_words=image.total_words,
            timeout_ms=_COMMAND_TIMEOUT_MS[Command.RAM_CHECK_CRC],
        )
        self.progress("RamCheckCrc", 1, 1)
        return image_crc32

    def run_ram(self, image: FirmwareImage, *, entry_point: int | None = None) -> None:
        validate_ram_firmware_image(image)
        self.client.run_ram(
            entry_point=image.entry_point if entry_point is None else entry_point,
            timeout_ms=_COMMAND_TIMEOUT_MS[Command.RUN_RAM],
        )

    def run_ram_image(self, image: FirmwareImage) -> int:
        image_crc32 = self.ram_load(image)
        self.ram_check_crc(image)
        self.run_ram(image)
        return image_crc32

    def load_and_attach_service(
        self, service_image: FirmwareImage, descriptor_address: int
    ) -> ServiceStatus:
        image_crc32 = self.ram_load(service_image)
        self.ram_check_crc(service_image)
        self.client.service_attach(
            descriptor_address=descriptor_address,
            expected_crc32=image_crc32,
            expected_total_words=service_image.total_words,
            timeout_ms=_COMMAND_TIMEOUT_MS[Command.SERVICE_ATTACH],
        )
        status = self.client.get_service_status(
            timeout_ms=_COMMAND_TIMEOUT_MS[Command.GET_SERVICE_STATUS]
        )
        if status.service_state != ServiceState.ATTACHED:
            raise WorkflowError(f"service attach did not reach ATTACHED state: {status!r}")
        self.progress("ServiceAttach", 1, 1)
        return status
