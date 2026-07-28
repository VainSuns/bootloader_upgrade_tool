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
    SERVICE_ABI_MAJOR,
    SERVICE_ABI_MINOR,
    SERVICE_REQUIRED_CAPABILITIES,
    ServiceState,
    Status,
)
from bootloader_upgrade_tool.simulator import SimulatorCore


HEADER = 0x013000
IMMUTABLE_START = 0x013082
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
            FirmwareBlock(SYMBOLS.app_export_address, (0xFFFF, 0xFFFF)),
            FirmwareBlock(IMMUTABLE_START, tuple(range(8))),
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
