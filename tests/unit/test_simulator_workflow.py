import pytest

from bootloader_upgrade_tool.core import ProtocolClient, ProtocolStatusError, UpgradeWorkflow
from bootloader_upgrade_tool.core.client import ProtocolDecodeError
from bootloader_upgrade_tool.core.workflow import (
    DeviceState,
    WorkflowError,
    calculate_programmed_image_crc32,
)
from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage, crc32_words
from bootloader_upgrade_tool.io import IoTimeoutError, SimulatorIoDevice
from bootloader_upgrade_tool.protocol.constants import (
    BootSlot,
    Command,
    MetadataRecordType,
    ReadTarget,
    Status,
    Target,
)
from bootloader_upgrade_tool.protocol.models import split_u32
from bootloader_upgrade_tool.core import workflow as workflow_module
from bootloader_upgrade_tool.simulator import SimulatorAction, SimulatorCore


def make_image(*, entry_point: int = 0x082400, address: int = 0x082400) -> FirmwareImage:
    return FirmwareImage(
        source_out_file="app.out",
        generated_hex_file="app.txt",
        entry_point=entry_point,
        blocks=(FirmwareBlock(address, tuple(range(10))),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )


def connected() -> tuple[SimulatorCore, ProtocolClient, UpgradeWorkflow]:
    core = SimulatorCore()
    client = ProtocolClient(SimulatorIoDevice(core), default_timeout_ms=5)
    info = client.open(wait_slave_timeout_ms=5)
    assert info.max_data_words == 248
    return core, client, UpgradeWorkflow(client)


def test_simulator_ping_device_info_and_last_error() -> None:
    core, client, _ = connected()
    client.ping()
    assert client.get_device_info() == core.device_info
    assert client.get_last_error().operation == 0
    client.close()


def test_complete_dfu_padding_run_and_reset() -> None:
    core, client, workflow = connected()
    image = make_image()
    progress: list[tuple[str, int, int]] = []
    workflow.progress = lambda operation, current, total: progress.append(
        (operation, current, total)
    )

    workflow.dfu(0x2, image)

    assert workflow.verify_succeeded
    assert [core.flash[0x082400 + index] for index in range(10)] == list(range(10))
    assert [core.flash[0x082400 + index] for index in range(10, 16)] == [0xFFFF] * 6
    assert progress == [("Program", 1, 1), ("Verify", 1, 1), ("Metadata", 1, 1)]
    summary = client.get_metadata_summary()
    assert summary.metadata_valid == 1
    assert summary.latest_record_type == MetadataRecordType.IMAGE_VALID
    assert summary.boot_attempt_count == 0
    assert summary.app_confirmed == 0
    assert summary.entry_point == image.entry_point
    assert summary.image_crc32 == calculate_programmed_image_crc32(
        image, core.device_info.max_data_words
    )
    workflow.run(image)
    assert core.pending_action is SimulatorAction.RUN_APP
    workflow.reset()
    assert core.pending_action is SimulatorAction.RESET_DEVICE
    client.close()


def test_run_requires_verify_after_flash_change() -> None:
    _, client, workflow = connected()
    image = make_image()
    workflow.erase(2)
    workflow.program(image)
    with pytest.raises(WorkflowError, match="Verify"):
        workflow.run(image)
    client.close()


def test_programmed_ffff_padding_cannot_be_programmed_again_before_erase() -> None:
    _, client, workflow = connected()
    image = make_image()
    workflow.erase(2)
    workflow.program(image)
    with pytest.raises(ProtocolStatusError) as captured:
        workflow.program(image)
    assert captured.value.status == Status.REPROGRAM_FORBIDDEN
    client.close()


def test_run_checks_entry_alignment() -> None:
    _, client, workflow = connected()
    with pytest.raises(ValueError, match="aligned"):
        workflow.run(make_image(entry_point=0x082402))
    client.close()


def test_simulator_program_failure_uses_protocol_status_and_error_detail() -> None:
    core, client, workflow = connected()
    core.faults.program_fail_at_address = 0x082404
    workflow.erase(2)
    with pytest.raises(ProtocolStatusError) as captured:
        workflow.program(make_image())
    assert captured.value.status == Status.PROGRAM_FAILED
    detail = workflow.last_error_detail
    assert detail is not None
    assert detail.address == 0x082404
    client.close()


def test_response_crc_and_sequence_faults_are_local_errors() -> None:
    core, client, _ = connected()
    core.faults.bad_payload_crc = True
    with pytest.raises(ProtocolDecodeError, match="CRC"):
        client.ping()
    core.faults.bad_payload_crc = False
    core.faults.sequence_mismatch = True
    with pytest.raises(ProtocolDecodeError, match="sequence"):
        client.ping()
    client.close()


def test_timeout_marks_workflow_unknown_and_probes_without_retrying_command(
    monkeypatch,
) -> None:
    monkeypatch.setitem(workflow_module._COMMAND_TIMEOUT_MS, Command.ERASE, 5)
    core, client, workflow = connected()
    core.faults.no_response = True
    monkeypatch.setattr(
        client,
        "ping",
        lambda **kwargs: (_ for _ in ()).throw(IoTimeoutError("probe timed out")),
    )
    with pytest.raises(IoTimeoutError):
        workflow.erase(1)
    assert workflow.state is DeviceState.UNKNOWN
    assert workflow.last_probe_succeeded is False
    client.close()


def test_workflow_uses_operation_timeouts_and_aligned_data_payloads() -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.device_info = SimulatorCore().device_info
            self.calls: list[tuple[Command, tuple[int, ...], int]] = []

        def transact(self, command, payload=(), *, timeout_ms):
            self.calls.append((command, tuple(payload), timeout_ms))
            return ()

        def metadata_append_image_valid(self, **kwargs):
            self.calls.append((Command.METADATA_APPEND_RECORD, (), kwargs["timeout_ms"]))

        def ping(self, *, timeout_ms):
            self.calls.append((Command.PING, (), timeout_ms))

    client = RecordingClient()
    workflow = UpgradeWorkflow(client)  # type: ignore[arg-type]
    image = make_image()

    workflow.dfu(2, image)
    workflow.run(image)
    workflow.reset()

    timeouts = {command: timeout for command, _, timeout in client.calls}
    assert timeouts[Command.ERASE] == 60_000
    assert timeouts[Command.PROGRAM_BEGIN] == 10_000
    assert timeouts[Command.PROGRAM_DATA] == 10_000
    assert timeouts[Command.PROGRAM_END] == 10_000
    assert timeouts[Command.VERIFY_BEGIN] == 10_000
    assert timeouts[Command.VERIFY_DATA] == 10_000
    assert timeouts[Command.VERIFY_END] == 10_000
    assert timeouts[Command.METADATA_APPEND_RECORD] == 10_000
    assert timeouts[Command.RUN] == 5_000
    assert timeouts[Command.RESET] == 5_000

    program_payload = next(
        payload for command, payload, _ in client.calls
        if command == Command.PROGRAM_DATA
    )
    assert program_payload[2] == 16
    assert len(program_payload) == 5 + program_payload[2]
    assert program_payload[-6:] == (0xFFFF,) * 6


def test_bad_block_index_injection_ends_program_session() -> None:
    core, client, workflow = connected()
    core.faults.bad_block_index = True
    workflow.erase(2)
    with pytest.raises(ProtocolStatusError) as captured:
        workflow.program(make_image())
    assert captured.value.status == Status.BLOCK_INDEX_ERROR
    assert core.program_session is None
    client.close()


def test_workflow_rejects_invalid_image_before_dfu_erase() -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.device_info = SimulatorCore().device_info
            self.calls: list[Command] = []

        def transact(self, command, payload=(), *, timeout_ms):
            self.calls.append(command)
            return ()

    client = RecordingClient()
    workflow = UpgradeWorkflow(client)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="metadata"):
        workflow.dfu(0x2, make_image(entry_point=0x082000, address=0x082000))
    assert client.calls == []


def test_simulator_rejects_metadata_program_verify_and_run() -> None:
    _core, client, _workflow = connected()
    total_low, total_high = split_u32(8)
    old_low, old_high = split_u32(0x082000)
    app_low, app_high = split_u32(0x082400)

    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(
            Command.PROGRAM_BEGIN,
            (Target.FLASH_APP, 1, total_low, total_high, old_low, old_high, 0, 0, 0),
        )
    assert captured.value.status == Status.ADDRESS_OUT_OF_RANGE

    client.transact(
        Command.PROGRAM_BEGIN,
        (Target.FLASH_APP, 1, total_low, total_high, app_low, app_high, 0, 0, 0),
    )
    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.PROGRAM_DATA, (old_low, old_high, 8, 0, 0, *range(8)))
    assert captured.value.status == Status.ADDRESS_OUT_OF_RANGE

    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(
            Command.VERIFY_BEGIN,
            (Target.FLASH_APP, 1, total_low, total_high, old_low, old_high, 0, 0, 0),
        )
    assert captured.value.status == Status.ADDRESS_OUT_OF_RANGE

    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.RUN, (Target.FLASH_APP, old_low, old_high, 0))
    assert captured.value.status == Status.ADDRESS_OUT_OF_RANGE
    client.close()


def test_unsupported_ram_load_is_not_implemented_in_mvp_simulator() -> None:
    _, client, _ = connected()
    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.RAM_LOAD_BEGIN, (0,) * 9)
    assert captured.value.status == Status.UNSUPPORTED_COMMAND
    assert client.get_last_error().operation == 0
    client.close()


def test_flash_read_metadata_valid_boundaries_and_blank_words() -> None:
    core, client, _ = connected()

    assert client.flash_read_metadata(0x082000, 16) == (0xFFFF,) * 16
    assert client.flash_read_metadata(0x082000, 1) == (0xFFFF,)
    assert client.flash_read_metadata(0x0823FF, 1) == (0xFFFF,)

    core.flash[0x082000] = 0x1234
    assert client.flash_read_metadata(0x082000, 1) == (0x1234,)
    client.close()


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ((ReadTarget.METADATA, *split_u32(0x0823FF), 2, 0), Status.ADDRESS_OUT_OF_RANGE),
        ((ReadTarget.METADATA, *split_u32(0x082400), 1, 0), Status.ADDRESS_OUT_OF_RANGE),
        ((ReadTarget.APP, *split_u32(0x082000), 1, 0), Status.UNSUPPORTED_FEATURE),
        ((ReadTarget.RAW_FLASH, *split_u32(0x082000), 1, 0), Status.UNSUPPORTED_FEATURE),
        ((ReadTarget.METADATA, *split_u32(0x082000), 0, 0), Status.BAD_WORD_COUNT),
        ((ReadTarget.METADATA, *split_u32(0x082000), 254, 0), Status.BAD_WORD_COUNT),
    ],
)
def test_flash_read_metadata_rejects_invalid_requests(
    payload: tuple[int, ...], status: Status
) -> None:
    _core, client, _ = connected()
    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.FLASH_READ, payload)
    assert captured.value.status == status
    client.close()


def test_get_metadata_summary_blank_metadata() -> None:
    _core, client, _ = connected()
    summary = client.get_metadata_summary()

    assert summary.metadata_valid == 0
    assert summary.state == 0
    assert summary.erased_record_count == 16
    assert summary.free_record_count == 16
    assert summary.valid_record_count == 0
    assert summary.invalid_record_count == 0
    assert summary.next_record_index == 0
    client.close()


def test_get_metadata_summary_rejects_payload() -> None:
    _core, client, _ = connected()
    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.GET_METADATA_SUMMARY, (1,))
    assert captured.value.status == Status.BAD_PAYLOAD_LENGTH
    client.close()


def test_get_metadata_summary_rejects_bad_payload_length() -> None:
    _core, client, _ = connected()
    client.transact = lambda *args, **kwargs: (0,)  # type: ignore[method-assign]
    with pytest.raises(ProtocolDecodeError, match="MetadataSummary"):
        client.get_metadata_summary()
    client.close()


def test_programmed_image_crc32_uses_padded_written_words() -> None:
    image = make_image()
    assert calculate_programmed_image_crc32(image, 248) == crc32_words(
        (*range(10), *((0xFFFF,) * 6))
    )


def test_failed_verify_does_not_append_image_valid() -> None:
    core, client, workflow = connected()
    core.faults.verify_fail_at_address = 0x082404
    with pytest.raises(ProtocolStatusError) as captured:
        workflow.dfu(0x2, make_image())
    assert captured.value.status == Status.VERIFY_MISMATCH
    assert client.get_metadata_summary().metadata_valid == 0
    client.close()


def test_metadata_append_rejects_unsupported_record_type() -> None:
    _core, client, _ = connected()
    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(
            Command.METADATA_APPEND_RECORD,
            (MetadataRecordType.BOOT_ATTEMPT, BootSlot.SLOT_A, *split_u32(0x082400),
             *split_u32(1), *split_u32(0), 0, 0, 0, *split_u32(0), *split_u32(0x082408), 0),
        )
    assert captured.value.status == Status.UNSUPPORTED_FEATURE
    client.close()


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"entry_point": 0x082000, "image_size_words": 1, "app_end": 0x082408}, Status.BAD_ADDRESS),
        ({"entry_point": 0x082400, "image_size_words": 1, "app_end": 0x0C0001}, Status.BAD_ADDRESS),
        ({"entry_point": 0x082400, "image_size_words": 0, "app_end": 0x082408}, Status.BAD_WORD_COUNT),
    ],
)
def test_metadata_append_rejects_invalid_range(kwargs: dict[str, int], status: Status) -> None:
    _core, client, _ = connected()
    with pytest.raises(ProtocolStatusError) as captured:
        client.metadata_append_image_valid(image_crc32=0, **kwargs)
    assert captured.value.status == status
    client.close()


def test_metadata_append_rejects_full_journal() -> None:
    _core, client, _ = connected()
    for _ in range(16):
        client.metadata_append_image_valid(
            entry_point=0x082400,
            image_size_words=8,
            image_crc32=0,
            app_end=0x082408,
        )
    with pytest.raises(ProtocolStatusError) as captured:
        client.metadata_append_image_valid(
            entry_point=0x082400,
            image_size_words=8,
            image_crc32=0,
            app_end=0x082408,
        )
    assert captured.value.status == Status.METADATA_FULL
    client.close()
