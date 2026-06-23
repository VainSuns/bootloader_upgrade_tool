"""Erase/Program/Verify/DFU/Run/Reset orchestration above ProtocolClient."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Sequence

from ..firmware.models import AddressRange, FirmwareBlock, FirmwareImage
from ..io.base import IoTimeoutError
from ..protocol.alignment import pad_write_data
from ..protocol.constants import Command, Target
from ..protocol.models import split_u32
from .client import ProtocolClient


class WorkflowError(RuntimeError):
    pass


class DeviceState(Enum):
    READY = "ready"
    UNKNOWN = "unknown"


ProgressCallback = Callable[[str, int, int], None]


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

    def _transact(
        self, command: Command, payload: Sequence[int] = (), *, modifying: bool = False
    ) -> tuple[int, ...]:
        try:
            return self.client.transact(command, payload)
        except IoTimeoutError:
            self.state = DeviceState.UNKNOWN
            if modifying:
                self.flash_modified = True
                self.verify_succeeded = False
            try:
                self.client.ping()
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
        self.erase(sector_mask)
        self.program(image)
        self.verify(image)

    def _entry_allowed(self, image: FirmwareImage) -> bool:
        ranges = self.allowed_flash_ranges or image.address_ranges
        return any(item.start <= image.entry_point < item.end_exclusive for item in ranges)

    def run(self, image: FirmwareImage) -> None:
        if image.entry_point % 8:
            raise WorkflowError("FLASH_APP entry point must be 8-word aligned")
        if not self._entry_allowed(image):
            raise WorkflowError("FLASH_APP entry point is outside the allowed Flash range")
        if self.flash_modified and not self.verify_succeeded:
            raise WorkflowError("Verify must succeed after Erase/Program/DFU before Run")
        entry_low, entry_high = split_u32(image.entry_point)
        self._transact(Command.RUN, (Target.FLASH_APP, entry_low, entry_high, 0))

    def reset(self) -> None:
        self._transact(Command.RESET)
