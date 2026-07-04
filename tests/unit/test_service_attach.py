import pytest

from bootloader_upgrade_tool.core import ProtocolClient, ProtocolStatusError, UpgradeWorkflow
from bootloader_upgrade_tool.core.workflow import calculate_ram_image_crc32
from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage, crc32_words
from bootloader_upgrade_tool.firmware.service_image import patch_flash_service_image
from bootloader_upgrade_tool.io import SimulatorIoDevice
from bootloader_upgrade_tool.protocol.constants import (
    Command,
    SERVICE_DESCRIPTOR_MAGIC,
    SERVICE_DESCRIPTOR_VERSION,
    SERVICE_DESCRIPTOR_WORDS,
    SERVICE_REQUIRED_CAPABILITIES,
    ServiceState,
    Status,
)
from bootloader_upgrade_tool.protocol.models import split_u32
from bootloader_upgrade_tool.simulator import SimulatorCore


DESCRIPTOR_ADDRESS = 0x010000
API_ADDRESS = DESCRIPTOR_ADDRESS + SERVICE_DESCRIPTOR_WORDS + 2
IMAGE_WORDS = SERVICE_DESCRIPTOR_WORDS + 4
TARGET_CRC = 0x12345678


def _solve_two_word_patch(words: list[int], patch_index: int, target_crc: int) -> tuple[int, int]:
    words[patch_index] = 0
    words[patch_index + 1] = 0
    base = crc32_words(words)
    columns: list[int] = []
    for bit in range(32):
        trial = words[:]
        trial[patch_index + (bit // 16)] ^= 1 << (bit % 16)
        columns.append(crc32_words(trial) ^ base)

    rows = [[(columns[column] >> row) & 1 for column in range(32)] + [((target_crc ^ base) >> row) & 1] for row in range(32)]
    pivot_row = 0
    pivots: list[int] = []
    for column in range(32):
        row = next((candidate for candidate in range(pivot_row, 32) if rows[candidate][column]), None)
        if row is None:
            continue
        rows[pivot_row], rows[row] = rows[row], rows[pivot_row]
        for candidate in range(32):
            if candidate != pivot_row and rows[candidate][column]:
                rows[candidate] = [left ^ right for left, right in zip(rows[candidate], rows[pivot_row])]
        pivots.append(column)
        pivot_row += 1
    assert pivot_row == 32
    value = 0
    for row, column in enumerate(pivots):
        value |= rows[row][32] << column
    return value & 0xFFFF, value >> 16


def service_words(
    *,
    magic: int = SERVICE_DESCRIPTOR_MAGIC,
    abi_major: int = 1,
    capabilities: int = int(SERVICE_REQUIRED_CAPABILITIES),
    image_crc32: int = TARGET_CRC,
    solve_patch: bool = True,
) -> tuple[int, ...]:
    words = [0] * IMAGE_WORDS
    words[0], words[1] = split_u32(magic)
    words[2] = SERVICE_DESCRIPTOR_VERSION
    words[3] = SERVICE_DESCRIPTOR_WORDS
    words[4] = abi_major
    words[5] = 0
    words[6] = 2
    words[7] = 4
    words[8], words[9] = split_u32(API_ADDRESS)
    words[10], words[11] = split_u32(DESCRIPTOR_ADDRESS)
    words[12], words[13] = split_u32(DESCRIPTOR_ADDRESS + IMAGE_WORDS)
    words[14], words[15] = split_u32(image_crc32)
    words[16], words[17] = split_u32(capabilities)
    words[18], words[19] = split_u32(crc32_words(words[:18]))
    if solve_patch and magic == SERVICE_DESCRIPTOR_MAGIC and abi_major == 1 and capabilities == int(SERVICE_REQUIRED_CAPABILITIES):
        words[20], words[21] = _solve_two_word_patch(words, 20, image_crc32)
    return tuple(words)


def service_image(words: tuple[int, ...] | None = None) -> FirmwareImage:
    payload = words or service_words()
    return FirmwareImage(
        source_out_file="flash_service_lib.out",
        generated_hex_file="flash_service_lib.txt",
        entry_point=DESCRIPTOR_ADDRESS,
        blocks=(FirmwareBlock(DESCRIPTOR_ADDRESS, payload),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )


def connected(*, require_service_for_flash_commands: bool = False) -> tuple[SimulatorCore, ProtocolClient, UpgradeWorkflow]:
    core = SimulatorCore(require_service_for_flash_commands=require_service_for_flash_commands)
    client = ProtocolClient(SimulatorIoDevice(core), default_timeout_ms=5)
    client.open(wait_slave_timeout_ms=5)
    return core, client, UpgradeWorkflow(client)


def test_get_service_status_initially_detached() -> None:
    _, client, _ = connected()
    status = client.get_service_status()
    assert status.service_state == ServiceState.DETACHED
    assert status.loaded_image_words == 0
    client.close()


def test_service_attach_rejects_before_ram_load() -> None:
    _, client, _ = connected()
    with pytest.raises(ProtocolStatusError) as captured:
        client.service_attach(
            descriptor_address=DESCRIPTOR_ADDRESS,
            expected_crc32=TARGET_CRC,
            expected_total_words=IMAGE_WORDS,
        )
    assert captured.value.status == Status.INVALID_STATE
    client.close()


def test_service_attach_rejects_before_ram_check_crc() -> None:
    _, client, workflow = connected()
    image = service_image()
    workflow.ram_load(image)
    with pytest.raises(ProtocolStatusError) as captured:
        client.service_attach(
            descriptor_address=DESCRIPTOR_ADDRESS,
            expected_crc32=TARGET_CRC,
            expected_total_words=image.total_words,
        )
    assert captured.value.status == Status.INVALID_STATE
    client.close()


@pytest.mark.parametrize(
    ("words", "descriptor_address", "expected_status"),
    (
        (service_words(), DESCRIPTOR_ADDRESS + 0x100, Status.RAM_REGION_ERROR),
        (service_words(image_crc32=0x87654321, solve_patch=False), DESCRIPTOR_ADDRESS, Status.UNSUPPORTED_FEATURE),
        (service_words(magic=0), DESCRIPTOR_ADDRESS, Status.METADATA_INVALID),
        (service_words(abi_major=2), DESCRIPTOR_ADDRESS, Status.UNSUPPORTED_PROTOCOL),
        (service_words(capabilities=0), DESCRIPTOR_ADDRESS, Status.UNSUPPORTED_FEATURE),
    ),
)
def test_service_attach_negative_cases(words, descriptor_address, expected_status) -> None:
    _, client, workflow = connected()
    image = service_image(words)
    crc = workflow.ram_load(image)
    workflow.ram_check_crc(image)
    with pytest.raises(ProtocolStatusError) as captured:
        client.service_attach(
            descriptor_address=descriptor_address,
            expected_crc32=crc,
            expected_total_words=image.total_words,
        )
    assert captured.value.status == expected_status
    client.close()


def test_service_attach_rejects_expected_crc_and_total_word_mismatch() -> None:
    _, client, workflow = connected()
    image = service_image()
    crc = workflow.ram_load(image)
    workflow.ram_check_crc(image)
    with pytest.raises(ProtocolStatusError) as captured:
        client.service_attach(
            descriptor_address=DESCRIPTOR_ADDRESS,
            expected_crc32=crc ^ 1,
            expected_total_words=image.total_words,
        )
    assert captured.value.status == Status.VERIFY_MISMATCH
    with pytest.raises(ProtocolStatusError) as captured:
        client.service_attach(
            descriptor_address=DESCRIPTOR_ADDRESS,
            expected_crc32=crc,
            expected_total_words=image.total_words + 1,
        )
    assert captured.value.status == Status.VERIFY_MISMATCH
    client.close()


def test_load_and_attach_service_success_and_flash_workflow_still_passes() -> None:
    core, client, workflow = connected()
    image = patch_flash_service_image(
        FirmwareImage(
            source_out_file="flash_service_lib.out",
            generated_hex_file="flash_service_lib.txt",
            entry_point=DESCRIPTOR_ADDRESS,
            blocks=(FirmwareBlock(DESCRIPTOR_ADDRESS, tuple(range(32))),),
            file_checksum="fixture",
            format_info={"format": "fixture"},
        ),
        descriptor_address=DESCRIPTOR_ADDRESS,
        api_table_address=API_ADDRESS,
        crc_patch_address=DESCRIPTOR_ADDRESS + SERVICE_DESCRIPTOR_WORDS,
        service_major=2,
        service_minor=4,
    )
    status = workflow.load_and_attach_service(image, DESCRIPTOR_ADDRESS)
    assert status.service_state == ServiceState.ATTACHED
    assert status.service_major == 2
    assert status.service_minor == 4
    assert status.capabilities == int(SERVICE_REQUIRED_CAPABILITIES)
    assert status.loaded_image_crc32 == calculate_ram_image_crc32(image, core.device_info.max_data_words)
    assert status.loaded_image_words == image.total_words
    assert core.pending_action.value != "run_ram"

    app = FirmwareImage(
        source_out_file="app.out",
        generated_hex_file="app.txt",
        entry_point=0x082400,
        blocks=(FirmwareBlock(0x082400, tuple(range(16))),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )
    workflow.erase(0x2)
    workflow.program(app)
    workflow.verify(app)
    assert workflow.verify_succeeded
    client.close()


def test_service_gated_simulator_rejects_flash_before_attach_and_allows_after() -> None:
    core, client, workflow = connected(require_service_for_flash_commands=True)
    app = FirmwareImage(
        source_out_file="app.out",
        generated_hex_file="app.txt",
        entry_point=0x082400,
        blocks=(FirmwareBlock(0x082400, tuple(range(16))),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )
    with pytest.raises(ProtocolStatusError) as captured:
        workflow.erase(0x2)
    assert captured.value.status == Status.UNSUPPORTED_FEATURE
    total_low, total_high = split_u32(16)
    entry_low, entry_high = split_u32(app.entry_point)
    begin_payload = (1, 1, total_low, total_high, entry_low, entry_high, 0, 0, 0)
    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.PROGRAM_BEGIN, begin_payload)
    assert captured.value.status == Status.UNSUPPORTED_FEATURE
    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.VERIFY_BEGIN, begin_payload)
    assert captured.value.status == Status.UNSUPPORTED_FEATURE

    service = patch_flash_service_image(
        FirmwareImage(
            source_out_file="flash_service_lib.out",
            generated_hex_file="flash_service_lib.txt",
            entry_point=DESCRIPTOR_ADDRESS,
            blocks=(FirmwareBlock(DESCRIPTOR_ADDRESS, tuple(range(32))),),
            file_checksum="fixture",
            format_info={"format": "fixture"},
        ),
        descriptor_address=DESCRIPTOR_ADDRESS,
        api_table_address=API_ADDRESS,
        crc_patch_address=DESCRIPTOR_ADDRESS + SERVICE_DESCRIPTOR_WORDS,
    )
    workflow.load_and_attach_service(service, DESCRIPTOR_ADDRESS)
    assert core.pending_action.value != "run_ram"
    workflow.erase(0x2)
    workflow.program(app)
    workflow.verify(app)
    assert workflow.verify_succeeded
    client.close()
