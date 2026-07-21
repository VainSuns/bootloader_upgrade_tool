from __future__ import annotations

from dataclasses import fields, replace
from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.images.models import (
    ImageIdentity,
    PreparedFlashImage,
    PreparedRamImage,
    PreparedServiceImage,
)
from bootloader_upgrade_tool.operations import (
    CheckRamCrcRequest,
    EraseFlashImageAreaRequest,
    EraseSectorMaskRequest,
    FlashOperationContext,
    LoadRamImageRequest,
    OperationContext,
    RunFlashAppRequest,
    check_ram_crc,
    erase_sector_mask,
    erase_flash_image_area,
    load_ram_image,
    run_flash_app,
)
from bootloader_upgrade_tool.protocol.constants import ServiceState
from bootloader_upgrade_tool.protocol.models import split_u32
from bootloader_upgrade_tool.targets import (
    AddressRange,
    CPU1_PROFILE,
    CommandSet,
    RamLayout,
    TargetProfile,
)


FAKE_COMMANDS = CommandSet(
    **{field.name: 0x7000 + index for index, field in enumerate(fields(CommandSet))}
)


class FakeClient:
    effective_max_data_words = 8
    effective_max_write_data_words = 8

    def __init__(self, responses: dict[int, list[tuple[int, ...]]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[int, tuple[int, ...]]] = []

    def transact(
        self,
        command: int,
        payload: tuple[int, ...] = (),
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, ...]:
        self.calls.append((command, tuple(payload)))
        queue = self.responses.get(command)
        return queue.pop(0) if queue else ()


def _profile(*, commands: CommandSet = FAKE_COMMANDS, memory_map=None) -> TargetProfile:
    return TargetProfile(
        "Fake CPU3",
        3,
        commands,
        CPU1_PROFILE.memory_map if memory_map is None else memory_map,
    )


def _firmware(address: int, words: tuple[int, ...]) -> FirmwareImage:
    return FirmwareImage(
        source_out_file="fake_cpu3.out",
        generated_hex_file="fake_cpu3.txt",
        entry_point=address,
        blocks=(FirmwareBlock(address, words),),
        file_checksum="fake",
        format_info={},
    )


def _flash_image() -> PreparedFlashImage:
    image = _firmware(0x082400, (1, 2, 3, 4, 5, 6, 7, 8))
    identity = ImageIdentity(image.entry_point, image.total_words, 0x12345678, 0x082408)
    return PreparedFlashImage(image, identity, 0x2)


def _ram_image(address: int = 0x008000, words: tuple[int, ...] = (1, 2, 3, 4)) -> PreparedRamImage:
    image = _firmware(address, words)
    return PreparedRamImage(image, image.entry_point, image.total_words, 0xCAFECAFE)


def _service_image() -> PreparedServiceImage:
    image = _firmware(0x010000, tuple(range(32)))
    return PreparedServiceImage(image, 0x010000, 0x010020, 0x010030, 32, 0xAABBCCDD, 0xF)


def _service_status(*, capabilities: int = 0xF) -> tuple[int, ...]:
    return (
        int(ServiceState.ATTACHED),
        1,
        0,
        0,
        1,
        *split_u32(capabilities),
        0,
        *split_u32(0xAABBCCDD),
        *split_u32(32),
    )


def _context(profile: TargetProfile, client: FakeClient) -> OperationContext:
    return OperationContext(SimpleNamespace(client=client), profile)


def _flash_context(profile: TargetProfile, client: FakeClient) -> FlashOperationContext:
    return FlashOperationContext(
        session=SimpleNamespace(client=client),
        target=profile,
        service=_service_image(),
    )


def _assert_local_rejection(result, client: FakeClient) -> None:
    assert not result.ok
    assert result.error is not None and result.error.code == "UNSUPPORTED_OPERATION"
    assert client.calls == []


def test_generic_operation_uses_active_fake_cpu3_command_and_target_name() -> None:
    client = FakeClient()
    result = run_flash_app(
        _context(_profile(), client),
        RunFlashAppRequest(0x082400),
    )

    assert result.ok
    assert result.target == "Fake CPU3"
    assert [command for command, _ in client.calls] == [FAKE_COMMANDS.run]
    assert CPU1_PROFILE.command_set.run not in [command for command, _ in client.calls]


def test_missing_command_is_rejected_without_protocol_transaction() -> None:
    client = FakeClient()
    result = run_flash_app(
        _context(_profile(commands=replace(FAKE_COMMANDS, run=None)), client),
        RunFlashAppRequest(0x082400),
    )

    _assert_local_rejection(result, client)


@pytest.mark.parametrize(
    ("operation", "request_value"),
    (
        (erase_sector_mask, EraseSectorMaskRequest(0x2)),
        (erase_flash_image_area, EraseFlashImageAreaRequest(_flash_image())),
    ),
)
def test_missing_flash_layout_is_rejected_without_protocol_transaction(operation, request_value) -> None:
    client = FakeClient({FAKE_COMMANDS.get_service_status: [_service_status()]})
    profile = _profile(memory_map=replace(CPU1_PROFILE.memory_map, flash=None))

    result = operation(_flash_context(profile, client), request_value)

    _assert_local_rejection(result, client)


@pytest.mark.parametrize(
    ("operation", "request_type"),
    ((load_ram_image, LoadRamImageRequest), (check_ram_crc, CheckRamCrcRequest)),
)
def test_missing_ram_layout_is_rejected_without_protocol_transaction(operation, request_type) -> None:
    client = FakeClient()
    profile = _profile(memory_map=replace(CPU1_PROFILE.memory_map, ram=None))

    result = operation(_context(profile, client), request_type(_ram_image()))

    _assert_local_rejection(result, client)


@pytest.mark.parametrize("sector_mask", (0, 0x1, 0x80000000))
def test_invalid_flash_sector_mask_is_rejected_before_service_attach(sector_mask: int) -> None:
    client = FakeClient({FAKE_COMMANDS.get_service_status: [_service_status()]})

    result = erase_sector_mask(
        _flash_context(_profile(), client),
        EraseSectorMaskRequest(sector_mask),
    )

    assert not result.ok
    assert result.error is not None and result.error.code == "FORBIDDEN_SECTOR"
    assert client.calls == []


@pytest.mark.parametrize(
    ("operation", "request_type"),
    ((load_ram_image, LoadRamImageRequest), (check_ram_crc, CheckRamCrcRequest)),
)
def test_ram_block_outside_app_ranges_is_rejected_locally(operation, request_type) -> None:
    client = FakeClient()
    ram = RamLayout((), (AddressRange(0x8000, 0x8004),), ())
    profile = _profile(memory_map=replace(CPU1_PROFILE.memory_map, ram=ram))

    result = operation(
        _context(profile, client),
        request_type(_ram_image(0x8002)),
    )

    assert not result.ok
    assert result.error is not None and result.error.code == "INVALID_RAM_IMAGE"
    assert client.calls == []


@pytest.mark.parametrize(("service", "reserved"), ((True, False), (False, True)))
def test_ram_block_overlapping_protected_ranges_is_rejected_locally(
    service: bool,
    reserved: bool,
) -> None:
    client = FakeClient()
    protected = (AddressRange(0x8100, 0x8200),)
    ram = RamLayout(
        protected if service else (),
        (AddressRange(0x8000, 0x9000),),
        protected if reserved else (),
    )
    profile = _profile(memory_map=replace(CPU1_PROFILE.memory_map, ram=ram))

    result = load_ram_image(
        _context(profile, client),
        LoadRamImageRequest(_ram_image(0x8100)),
    )

    assert not result.ok
    assert result.error is not None and result.error.code == "INVALID_RAM_IMAGE"
    assert client.calls == []


def test_service_capability_mismatch_blocks_flash_and_metadata_writes() -> None:
    client = FakeClient(
        {FAKE_COMMANDS.get_service_status: [_service_status(capabilities=1)] * 2}
    )

    result = erase_sector_mask(
        _flash_context(_profile(), client),
        EraseSectorMaskRequest(0x2),
    )

    assert not result.ok
    assert result.error is not None and result.error.code == "SERVICE_CAPABILITY_MISMATCH"
    commands = [command for command, _ in client.calls]
    assert FAKE_COMMANDS.erase not in commands
    assert FAKE_COMMANDS.metadata_append_record not in commands
