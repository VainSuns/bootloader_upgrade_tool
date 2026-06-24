import pytest

from bootloader_upgrade_tool.core import ProtocolClient, ProtocolStatusError, UpgradeWorkflow
from bootloader_upgrade_tool.core.client import ProtocolDecodeError
from bootloader_upgrade_tool.core.workflow import DeviceState, WorkflowError
from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.io import IoTimeoutError, SimulatorIoDevice
from bootloader_upgrade_tool.protocol.constants import Command, Status
from bootloader_upgrade_tool.core import workflow as workflow_module
from bootloader_upgrade_tool.simulator import SimulatorAction, SimulatorCore


def make_image(*, entry_point: int = 0x080000) -> FirmwareImage:
    return FirmwareImage(
        source_out_file="app.out",
        generated_hex_file="app.txt",
        entry_point=entry_point,
        blocks=(FirmwareBlock(0x080000, tuple(range(10))),),
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

    workflow.dfu(0x1, image)

    assert workflow.verify_succeeded
    assert [core.flash[0x080000 + index] for index in range(10)] == list(range(10))
    assert [core.flash[0x080000 + index] for index in range(10, 16)] == [0xFFFF] * 6
    assert progress == [("Program", 1, 1), ("Verify", 1, 1)]
    workflow.run(image)
    assert core.pending_action is SimulatorAction.RUN_APP
    workflow.reset()
    assert core.pending_action is SimulatorAction.RESET_DEVICE
    client.close()


def test_run_requires_verify_after_flash_change() -> None:
    _, client, workflow = connected()
    image = make_image()
    workflow.erase(1)
    workflow.program(image)
    with pytest.raises(WorkflowError, match="Verify"):
        workflow.run(image)
    client.close()


def test_programmed_ffff_padding_cannot_be_programmed_again_before_erase() -> None:
    _, client, workflow = connected()
    image = make_image()
    workflow.erase(1)
    workflow.program(image)
    with pytest.raises(ProtocolStatusError) as captured:
        workflow.program(image)
    assert captured.value.status == Status.REPROGRAM_FORBIDDEN
    client.close()


def test_run_checks_entry_alignment() -> None:
    _, client, workflow = connected()
    with pytest.raises(WorkflowError, match="aligned"):
        workflow.run(make_image(entry_point=0x080002))
    client.close()


def test_simulator_program_failure_uses_protocol_status_and_error_detail() -> None:
    core, client, workflow = connected()
    core.faults.program_fail_at_address = 0x080004
    workflow.erase(1)
    with pytest.raises(ProtocolStatusError) as captured:
        workflow.program(make_image())
    assert captured.value.status == Status.PROGRAM_FAILED
    detail = workflow.last_error_detail
    assert detail is not None
    assert detail.address == 0x080004
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

        def ping(self, *, timeout_ms):
            self.calls.append((Command.PING, (), timeout_ms))

    client = RecordingClient()
    workflow = UpgradeWorkflow(client)  # type: ignore[arg-type]
    image = make_image()

    workflow.erase(1)
    workflow.program(image)
    workflow.verify(image)
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
    workflow.erase(1)
    with pytest.raises(ProtocolStatusError) as captured:
        workflow.program(make_image())
    assert captured.value.status == Status.BLOCK_INDEX_ERROR
    assert core.program_session is None
    client.close()


def test_unsupported_ram_load_is_not_implemented_in_mvp_simulator() -> None:
    _, client, _ = connected()
    with pytest.raises(ProtocolStatusError) as captured:
        client.transact(Command.RAM_LOAD_BEGIN, (0,) * 9)
    assert captured.value.status == Status.UNSUPPORTED_COMMAND
    assert client.get_last_error().operation == 0
    client.close()
