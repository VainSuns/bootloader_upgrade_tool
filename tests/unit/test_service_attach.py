import pytest

from bootloader_upgrade_tool.core import ProtocolClient, ProtocolStatusError, UpgradeWorkflow
from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.firmware.service_image import (
    calculate_service_ram_load_crc32,
    patch_flash_service_image,
    patch_words,
)
from bootloader_upgrade_tool.firmware.ti_map import TiMapSymbols
from bootloader_upgrade_tool.io import SimulatorIoDevice
from bootloader_upgrade_tool.protocol.constants import (
    Command,
    SERVICE_ABI_MAJOR,
    SERVICE_ABI_MINOR,
    SERVICE_REQUIRED_CAPABILITIES,
    ServiceState,
    Status,
)
from bootloader_upgrade_tool.protocol.models import split_u32
from bootloader_upgrade_tool.simulator import SimulatorCore
from bootloader_upgrade_tool.simulator.core import (
    FLASH_SERVICE_END_EXCLUSIVE,
    FLASH_SERVICE_PUBLISH,
    FLASH_SERVICE_START,
)


HEADER = 0x013000
IMMUTABLE_START = 0x013080
IMMUTABLE_END = 0x013092
SYMBOLS = TiMapSymbols(
    HEADER, 0x013020, 0x013022, 0x013080, IMMUTABLE_START, IMMUTABLE_END,
    IMMUTABLE_START + 2, IMMUTABLE_START + 8, IMMUTABLE_START + 12,
)


def service_image() -> FirmwareImage:
    raw = FirmwareImage(
        source_out_file="flash_service_lib.out",
        generated_hex_file="flash_service_lib.txt",
        entry_point=SYMBOLS.boot_init_address,
        blocks=(
            FirmwareBlock(HEADER, tuple(range(32))),
            FirmwareBlock(SYMBOLS.app_export_address, split_u32(SYMBOLS.confirm_current_image_address)),
            FirmwareBlock(IMMUTABLE_START + 2, tuple(range(8))),
            FirmwareBlock(IMMUTABLE_END - 2, (0xAAAA, 0xBBBB)),
        ),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )
    return patch_flash_service_image(raw, symbols=SYMBOLS)


def connected(*, require_service_for_flash_commands: bool = False):
    core = SimulatorCore(require_service_for_flash_commands=require_service_for_flash_commands)
    client = ProtocolClient(SimulatorIoDevice(core), default_timeout_ms=5)
    client.open(wait_slave_timeout_ms=5)
    return core, client, UpgradeWorkflow(client)


def test_get_service_status_initially_detached() -> None:
    _, client, _ = connected()
    status = client.get_service_status()
    assert status.service_state == ServiceState.DETACHED
    assert (status.abi_major, status.abi_minor) == (SERVICE_ABI_MAJOR, SERVICE_ABI_MINOR)
    assert status.loaded_image_words == 0
    client.close()


def test_service_attach_rejects_before_ram_load() -> None:
    _, client, _ = connected()
    with pytest.raises(ProtocolStatusError) as captured:
        client.service_attach(
            header_address=HEADER, expected_crc32=0, expected_total_words=1
        )
    assert captured.value.status == Status.INVALID_STATE
    client.close()


def test_service_attach_rejects_invalid_header_crc() -> None:
    _, client, workflow = connected()
    image = patch_words(service_image(), HEADER + 26, (0, 0))
    crc = workflow.ram_load(image)
    workflow.ram_check_crc(image)
    with pytest.raises(ProtocolStatusError) as captured:
        client.service_attach(
            header_address=HEADER,
            expected_crc32=crc,
            expected_total_words=image.total_words,
        )
    assert captured.value.status == Status.METADATA_INVALID
    client.close()


def test_load_and_attach_service_success_and_flash_workflow_still_passes() -> None:
    core, client, workflow = connected()
    image = service_image()
    status = workflow.load_and_attach_service(image, HEADER)

    assert status.service_state == ServiceState.ATTACHED
    assert (status.abi_major, status.abi_minor) == (SERVICE_ABI_MAJOR, SERVICE_ABI_MINOR)
    assert status.capabilities == int(SERVICE_REQUIRED_CAPABILITIES)
    assert status.loaded_image_crc32 == calculate_service_ram_load_crc32(
        image, core.device_info.max_data_words
    )
    assert status.loaded_image_words == image.total_words

    app = FirmwareImage(
        source_out_file="app.out", generated_hex_file="app.txt", entry_point=0x082400,
        blocks=(FirmwareBlock(0x082400, tuple(range(16))),),
        file_checksum="fixture", format_info={},
    )
    workflow.erase(0x2)
    workflow.program(app)
    workflow.verify(app)
    assert workflow.verify_succeeded
    client.close()


def test_service_gated_simulator_allows_flash_after_attach() -> None:
    _, client, workflow = connected(require_service_for_flash_commands=True)
    with pytest.raises(ProtocolStatusError) as captured:
        workflow.erase(0x2)
    assert captured.value.status == Status.UNSUPPORTED_FEATURE

    workflow.load_and_attach_service(service_image(), HEADER)
    workflow.erase(0x2)
    client.close()


def test_plain_ram_load_preserves_attached_service() -> None:
    core, client, workflow = connected()
    before = workflow.load_and_attach_service(service_image(), HEADER)
    app = FirmwareImage(
        source_out_file="ram_app.out",
        generated_hex_file="ram_app.txt",
        entry_point=0x010000,
        blocks=(FirmwareBlock(0x010000, (1, 2, 3, 4)),),
        file_checksum="fixture",
        format_info={},
    )

    workflow.ram_load(app)
    workflow.ram_check_crc(app)
    after = client.get_service_status()

    assert core.ram_crc_ok
    assert core.service_header_address == HEADER
    assert (
        after.service_state,
        after.abi_major,
        after.abi_minor,
        after.capabilities,
        after.loaded_image_crc32,
        after.loaded_image_words,
        after.last_attach_status,
    ) == (
        before.service_state,
        before.abi_major,
        before.abi_minor,
        before.capabilities,
        before.loaded_image_crc32,
        before.loaded_image_words,
        before.last_attach_status,
    )
    client.close()


def test_service_header_write_invalidates_attached_service() -> None:
    core, client, workflow = connected()
    attached = workflow.load_and_attach_service(service_image(), HEADER)
    payload = (
        *split_u32(HEADER),
        *split_u32(attached.loaded_image_crc32),
        *split_u32(attached.loaded_image_words),
        1,
    )

    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.SERVICE_ATTACH, payload)
    assert captured.value.status == Status.BAD_FLAGS
    assert client.get_service_status().service_state == ServiceState.ATTACHED

    client.ram_load_begin(packet_count=1, total_words=1, entry_point=HEADER)
    client.ram_load_data(address=HEADER, words=(0,), packet_index=0)
    status = client.get_service_status()

    assert status.service_state == ServiceState.DETACHED
    assert status.capabilities == 0
    assert status.loaded_image_crc32 == attached.loaded_image_crc32
    assert status.loaded_image_words == attached.loaded_image_words
    assert status.last_attach_status == Status.BAD_FLAGS
    assert core.service_header_address == 0
    client.close()


@pytest.mark.parametrize(
    ("address", "words"),
    (
        (0x013000, (0,)),
        (0x013020, (0,)),
        (0x013022, (0,)),
        (0x013060, (0,)),
        (0x013080, (0,)),
        (0x013082, (0,)),
        (0x015B00, (0,)),
        (FLASH_SERVICE_END_EXCLUSIVE - 1, (0,)),
        (FLASH_SERVICE_START - 1, (0, 0)),
        (FLASH_SERVICE_END_EXCLUSIVE - 1, (0, 0)),
    ),
)
def test_service_envelope_write_invalidates_attached_service(
    address: int, words: tuple[int, ...]
) -> None:
    _, client, workflow = connected()
    workflow.load_and_attach_service(service_image(), HEADER)

    client.ram_load_begin(packet_count=1, total_words=len(words), entry_point=address)
    client.ram_load_data(address=address, words=words, packet_index=0)

    assert client.get_service_status().service_state == ServiceState.DETACHED
    client.close()


def test_service_end_exclusive_write_preserves_attached_service() -> None:
    _, client, workflow = connected()
    workflow.load_and_attach_service(service_image(), HEADER)

    client.ram_load_begin(
        packet_count=1, total_words=1, entry_point=FLASH_SERVICE_END_EXCLUSIVE
    )
    client.ram_load_data(
        address=FLASH_SERVICE_END_EXCLUSIVE, words=(0,), packet_index=0
    )

    assert client.get_service_status().service_state == ServiceState.ATTACHED
    client.close()


def test_publish_words_cannot_revalidate_service_during_ram_write() -> None:
    core, client, workflow = connected()
    workflow.load_and_attach_service(service_image(), HEADER)

    client.ram_load_begin(packet_count=1, total_words=2, entry_point=FLASH_SERVICE_PUBLISH)
    client.ram_load_data(
        address=FLASH_SERVICE_PUBLISH, words=(0xA55A, 0x5AA5), packet_index=0
    )

    assert core.ram[FLASH_SERVICE_PUBLISH] == 0
    assert core.ram[FLASH_SERVICE_PUBLISH + 1] == 0
    assert client.get_service_status().service_state == ServiceState.DETACHED
    client.close()


def test_failed_attach_preserves_attached_service() -> None:
    core, client, workflow = connected()
    before = workflow.load_and_attach_service(service_image(), HEADER)
    payload = (
        *split_u32(HEADER),
        *split_u32(before.loaded_image_crc32),
        *split_u32(before.loaded_image_words),
        1,
    )

    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.SERVICE_ATTACH, payload)
    after = client.get_service_status()

    assert captured.value.status == Status.BAD_FLAGS
    assert after.service_state == ServiceState.ATTACHED
    assert core.service_header_address == HEADER
    assert after.capabilities == before.capabilities
    assert after.loaded_image_crc32 == before.loaded_image_crc32
    assert after.loaded_image_words == before.loaded_image_words
    assert after.last_attach_status == Status.BAD_FLAGS
    client.close()


def test_failed_attach_without_service_enters_error() -> None:
    core, client, _ = connected()
    payload = (*split_u32(HEADER), *split_u32(0), *split_u32(1), 1)

    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.SERVICE_ATTACH, payload)
    status = client.get_service_status()

    assert captured.value.status == Status.BAD_FLAGS
    assert status.service_state == ServiceState.ERROR
    assert status.last_attach_status == Status.BAD_FLAGS
    assert core.service_header_address == 0
    client.close()
