from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Callable

import pytest

from bootloader_upgrade_tool.core.client import ProtocolDecodeError, ProtocolStatusError
from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.images.models import ImageIdentity, PreparedFlashImage, PreparedRamImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import (
    AppendAppConfirmedRequest,
    AppendBootAttemptRequest,
    AppendImageValidRequest,
    BootCpu2RunCpu1Request,
    CheckRamCrcRequest,
    ErrorDomain,
    EraseFlashImageAreaRequest,
    EraseSectorMaskRequest,
    FlashOperationContext,
    LoadRamImageRequest,
    MemoryReadRequest,
    OperationContext,
    OperationCancellationInfo,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
    ProgramFlashImageRequest,
    ProgressEvent,
    ResetTargetRequest,
    RunFlashAppRequest,
    RunRamImageRequest,
    VerifyFlashImageRequest,
    append_app_confirmed,
    append_boot_attempt,
    append_image_valid,
    boot_cpu2_run_cpu1,
    check_ram_crc,
    erase_flash_image_area,
    erase_sector_mask,
    load_ram_image,
    memory_read,
    operation_result_to_dict,
    ping,
    program_flash_image,
    reset_target,
    run_flash_app,
    run_ram_image,
    verify_flash_image,
    get_metadata_summary,
)
import bootloader_upgrade_tool.operations.metadata_ops as metadata_ops
import bootloader_upgrade_tool.operations.status_ops as status_ops
import bootloader_upgrade_tool.protocol.constants as protocol_constants
from bootloader_upgrade_tool.operations._service_runtime import ServiceRuntimeCancellation, ensure_service_attached
from bootloader_upgrade_tool.operations.results import OperationFailure
from bootloader_upgrade_tool.protocol.boot_protocol_client import ProtocolInfo
from bootloader_upgrade_tool.protocol.constants import Command, Feature, MetadataRecordType, ServiceState, Status, Target
from bootloader_upgrade_tool.protocol.models import DeviceInfo, MetadataSummary, split_u32
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE
from bootloader_upgrade_tool.transport import TransportError


def firmware(address: int = 0x082400, words: tuple[int, ...] = (1, 2, 3, 4)) -> FirmwareImage:
    return FirmwareImage(
        source_out_file="x.out",
        generated_hex_file="x.txt",
        entry_point=address,
        blocks=(FirmwareBlock(address, words),),
        file_checksum="sha",
        format_info={},
    )


IDENTITY = ImageIdentity(0x082400, 8, 0x12345678, 0x082408)


def prepared_flash(sector_mask: int = 0x2) -> PreparedFlashImage:
    return PreparedFlashImage(firmware(), IDENTITY, sector_mask)


def prepared_flash_words(word_count: int) -> PreparedFlashImage:
    image = firmware(words=tuple(range(word_count)))
    identity = ImageIdentity(image.entry_point, word_count, 0x12345678, image.entry_point + word_count)
    return PreparedFlashImage(image, identity, 0x2)


def prepared_ram(words: tuple[int, ...] = (1, 2, 3, 4)) -> PreparedRamImage:
    image = firmware(0x008000, words)
    return PreparedRamImage(image, image.entry_point, image.total_words, 0xCAFECAFE)


def prepared_service() -> PreparedServiceImage:
    image = firmware(0x010000, tuple(range(32)))
    return PreparedServiceImage(image, 0x010000, 32, 0xAABBCCDD, 0xF)


def device_info() -> DeviceInfo:
    return DeviceInfo(0x377D, 1, 1, 0, 0, 1, int(Feature.MEMORY_READ), 256, 8, 2, 2)


def metadata(**overrides: int) -> MetadataSummary:
    values = dict(
        metadata_valid=1,
        active_slot=1,
        latest_record_type=1,
        boot_attempt_count=0,
        app_confirmed=0,
        boot_attempt_limit=3,
        app_version_major=0,
        app_version_minor=0,
        app_version_patch=0,
        app_version_build=0,
        entry_point=IDENTITY.entry_point,
        image_crc32=IDENTITY.image_crc32,
        state=1,
        valid_record_count=1,
        invalid_record_count=0,
        erased_record_count=0,
        free_record_count=1,
        next_record_index=1,
        image_size_words=IDENTITY.image_size_words,
        target_device_id=0x377D,
        target_cpu_id=1,
    )
    values.update(overrides)
    return MetadataSummary(**values)


def metadata_words(**overrides: int) -> tuple[int, ...]:
    item = metadata(**overrides)
    build_low, build_high = split_u32(item.app_version_build)
    entry_low, entry_high = split_u32(item.entry_point)
    crc_low, crc_high = split_u32(item.image_crc32)
    size_low, size_high = split_u32(item.image_size_words)
    return (
        item.metadata_valid,
        item.active_slot,
        item.latest_record_type,
        item.boot_attempt_count,
        item.app_confirmed,
        item.boot_attempt_limit,
        item.app_version_major,
        item.app_version_minor,
        item.app_version_patch,
        build_low,
        build_high,
        entry_low,
        entry_high,
        crc_low,
        crc_high,
        item.state,
        item.valid_record_count,
        item.invalid_record_count,
        item.erased_record_count,
        item.free_record_count,
        item.next_record_index,
        size_low,
        size_high,
        item.target_device_id,
        item.target_cpu_id,
    )


def service_words(
    *,
    state: int = int(ServiceState.ATTACHED),
    abi_major: int = 2,
    abi_minor: int = 0,
    capabilities: int = 0xF,
    crc32: int = 0xAABBCCDD,
    words: int = 32,
) -> tuple[int, ...]:
    return (
        state,
        abi_major,
        abi_minor,
        0,
        0,
        *split_u32(capabilities),
        0,
        *split_u32(crc32),
        *split_u32(words),
    )


class FakeClient:
    def __init__(self, responses: dict[int, list[tuple[int, ...]]] | None = None) -> None:
        self.device_info = device_info()
        self.protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, 256, 0)
        self.responses = responses or {}
        self.calls: list[tuple[int, tuple[int, ...]]] = []
        self.fail_on: set[int] = set()
        self.callbacks: dict[int, list[Callable[[], None] | None]] = {}
        self.failures: dict[int, list[Exception | None]] = {}

    @property
    def effective_max_payload_words(self) -> int:
        return min(self.device_info.max_payload_words, self.protocol_info.max_payload_words)

    @property
    def effective_max_data_words(self) -> int:
        value = min(self.device_info.max_data_words, self.effective_max_payload_words - 5)
        if value <= 0:
            raise ProtocolDecodeError("effective max DATA words must be positive")
        return value

    @property
    def effective_max_write_data_words(self) -> int:
        value = self.effective_max_data_words - self.effective_max_data_words % 8
        if value <= 0:
            raise ProtocolDecodeError("effective max Flash DATA words must be positive")
        return value

    def transact(
        self,
        command: int,
        payload: tuple[int, ...] = (),
        *,
        timeout_ms: int | None = None,
        wire_attempt_observer: Callable[[int], None] | None = None,
    ) -> tuple[int, ...]:
        assert type(command) is int
        self.calls.append((command, tuple(payload)))
        if wire_attempt_observer is not None:
            wire_attempt_observer(command)
        callbacks = self.callbacks.get(command)
        if callbacks:
            callback = callbacks.pop(0)
            if callback is not None:
                callback()
        failures = self.failures.get(command)
        if failures:
            failure = failures.pop(0)
            if failure is not None:
                raise failure
        if command in self.fail_on:
            raise ProtocolStatusError(command, 0x0202)
        queue = self.responses.get(command)
        return queue.pop(0) if queue else ()

    def __getattr__(self, name: str):
        raise AssertionError(f"operation used convenience method {name}")


class NoFlashCapacityClient(FakeClient):
    @property
    def effective_max_write_data_words(self) -> int:
        raise AssertionError("Flash DATA capacity must not be read after pre-cancellation")


class TinyPayloadClient(FakeClient):
    @property
    def effective_max_payload_words(self) -> int:
        return 3


class ScriptedCancellation:
    def __init__(self, requested: bool = False) -> None:
        self.requested = requested

    def request(self) -> None:
        self.requested = True

    def is_cancel_requested(self) -> bool:
        return self.requested


def ctx(client: FakeClient | None = None, *, progress=None, cancellation=None) -> OperationContext:
    return OperationContext(SimpleNamespace(client=client or FakeClient()), CPU1_PROFILE, progress, cancellation)


def flash_ctx(
    client: FakeClient | None = None,
    *,
    progress=None,
    force: bool = False,
    cancellation=None,
) -> FlashOperationContext:
    responses = {int(Command.GET_SERVICE_STATUS): [service_words()]}
    item = client or FakeClient(responses)
    return FlashOperationContext(
        SimpleNamespace(client=item),
        CPU1_PROFILE,
        progress,
        cancellation,
        service=prepared_service(),
        force_service_attach=force,
    )


def command_ids(client: FakeClient) -> list[int]:
    return [command for command, _ in client.calls]


def memory_response(address: int, words: tuple[int, ...]) -> tuple[int, ...]:
    return (*split_u32(address), len(words), *words)


def test_memory_read_command_capability_and_profiles() -> None:
    assert Command.MEMORY_READ == 0x0230
    assert "FLASH_READ" not in Command.__members__
    assert not hasattr(protocol_constants, "ReadTarget")
    assert Command(0x0230).name == "MEMORY_READ"
    assert Feature.MEMORY_READ == 1 << 10
    assert CPU1_PROFILE.command_set.memory_read == Command.MEMORY_READ
    assert CPU2_PROFILE.command_set.memory_read is None


@pytest.mark.parametrize(
    ("start_address", "word_count", "exception"),
    (
        (True, 1, TypeError),
        (0, True, TypeError),
        (-1, 1, ValueError),
        (0, 0, ValueError),
        (0xFFFFFFFF, 2, ValueError),
    ),
)
def test_memory_read_request_validation(start_address, word_count, exception) -> None:
    with pytest.raises(exception):
        MemoryReadRequest(start_address, word_count)


def test_memory_read_preflight_failures_send_nothing() -> None:
    client = FakeClient()
    client.device_info = None
    result = memory_read(ctx(client), MemoryReadRequest(0, 1))
    assert not result.ok and result.error and result.error.code == "CAPABILITY_UNAVAILABLE"
    assert result.stage == "MEMORY_READ_PREFLIGHT" and client.calls == []

    client = FakeClient()
    client.device_info = replace(device_info(), feature_flags=0)
    result = memory_read(ctx(client), MemoryReadRequest(0, 1))
    assert not result.ok and result.error and result.error.code == "UNSUPPORTED_FEATURE"
    assert client.calls == []

    client = TinyPayloadClient()
    result = memory_read(ctx(client), MemoryReadRequest(0, 1))
    assert not result.ok and result.error and result.error.code == "INVALID_PAYLOAD_CAPACITY"
    assert client.calls == []

    client = FakeClient()
    cpu2_ctx = OperationContext(SimpleNamespace(client=client), CPU2_PROFILE)
    result = memory_read(cpu2_ctx, MemoryReadRequest(0, 1))
    assert not result.ok and result.error and result.error.code == "UNSUPPORTED_OPERATION"
    assert client.calls == []


def test_memory_read_single_frame_uses_four_word_request_and_high_address() -> None:
    address = 0x12345678
    client = FakeClient({int(Command.MEMORY_READ): [memory_response(address, (1, 2, 3))]})
    result = memory_read(ctx(client), MemoryReadRequest(address, 3))
    assert result.ok
    assert client.calls == [(int(Command.MEMORY_READ), (*split_u32(address), 3, 0))]
    assert result.summary == {
        "start_address": address,
        "end_address": address + 2,
        "word_count": 3,
        "frame_count": 1,
    }
    assert "words" not in result.summary
    assert result.details == {"words": (1, 2, 3)}


def test_memory_read_uses_payload_capacity_and_shortens_last_frame() -> None:
    address = 0x20000000
    first = tuple(range(253))
    client = FakeClient({
        int(Command.MEMORY_READ): [
            memory_response(address, first),
            memory_response(address + 253, (0xBEEF,)),
        ]
    })
    result = memory_read(ctx(client), MemoryReadRequest(address, 254))
    assert result.ok and result.summary["frame_count"] == 2
    assert client.calls == [
        (int(Command.MEMORY_READ), (*split_u32(address), 253, 0)),
        (int(Command.MEMORY_READ), (*split_u32(address + 253), 1, 0)),
    ]
    assert result.details["words"] == (*first, 0xBEEF)


def test_memory_read_allows_unclassified_address() -> None:
    address = 0xDEAD0000
    client = FakeClient({int(Command.MEMORY_READ): [memory_response(address, (0xCAFE,))]})
    assert memory_read(ctx(client), MemoryReadRequest(address, 1)).ok
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "response",
    (
        (),
        memory_response(0x1001, (1, 2)),
        (*split_u32(0x1000), 1, 1),
        (*split_u32(0x1000), 2, 1),
        (*split_u32(0x1000), 2, 1, 0x10000),
    ),
)
def test_memory_read_rejects_invalid_frame_response(response) -> None:
    client = FakeClient({int(Command.MEMORY_READ): [response]})
    result = memory_read(ctx(client), MemoryReadRequest(0x1000, 2))
    assert not result.ok and result.error and result.error.code == "PROTOCOL_ERROR"
    assert "frame 0" in result.error.message


def test_memory_read_cancellation_stops_between_frames() -> None:
    token = ScriptedCancellation()
    address = 0x1000
    first = tuple(range(253))
    client = FakeClient({int(Command.MEMORY_READ): [memory_response(address, first)]})
    client.callbacks[int(Command.MEMORY_READ)] = [token.request]
    result = memory_read(
        ctx(client, cancellation=token),
        MemoryReadRequest(address, 254),
    )
    assert result.completion is OperationCompletion.CANCELLED
    assert len(client.calls) == 1
    assert result.details == {}
    assert result.cancellation and result.cancellation.current_words == 253
    assert result.cancellation.total_words == 254
    assert result.cancellation.protocol_state_clean
    assert not result.cancellation.outcome_uncertain
    assert not result.cancellation.connection_recovery_required
    assert result.cancellation.recovery_action == "NONE"


def test_operation_result_serialization() -> None:
    result = OperationResult(
        False,
        "op",
        "target",
        "stage",
        {},
        error=OperationErrorInfo("CODE", "message", "stage", details={"x": 1}),
    )
    assert operation_result_to_dict(result)["error"]["code"] == "CODE"


def test_metadata_summary_location_and_absent_metadata_helpers() -> None:
    assert hasattr(status_ops, "get_metadata_summary")
    assert not hasattr(metadata_ops, "get_metadata_summary")
    assert not hasattr(metadata_ops, "compare_image_with_metadata")
    client = FakeClient({int(Command.GET_METADATA_SUMMARY): [metadata_words()]})
    result = get_metadata_summary(ctx(client))
    assert isinstance(result, OperationResult)
    assert result.ok


def test_ping_uses_target_command_binding() -> None:
    client = FakeClient()

    result = ping(ctx(client))

    assert result.completion is OperationCompletion.SUCCEEDED
    assert client.calls == [(int(Command.PING), ())]


def test_ping_communication_failure_uses_formal_error_domain() -> None:
    client = FakeClient()
    client.failures[int(Command.PING)] = [TransportError("ping failed")]

    result = ping(ctx(client))

    assert not result.ok
    assert result.error is not None
    assert result.error.domain is ErrorDomain.COMMUNICATION


def test_ping_unsupported_target_does_not_transact() -> None:
    client = FakeClient()
    context = replace(ctx(client), target=CPU2_PROFILE)

    result = ping(context)

    assert not result.ok
    assert result.error is not None
    assert result.error.code == "UNSUPPORTED_OPERATION"
    assert result.error.domain is ErrorDomain.OPERATION
    assert client.calls == []


def test_ram_ops_use_operation_context_and_commands_only() -> None:
    client = FakeClient()
    result = load_ram_image(ctx(client), LoadRamImageRequest(prepared_ram()))
    assert result.ok
    assert command_ids(client) == [
        int(Command.RAM_LOAD_BEGIN),
        int(Command.RAM_LOAD_DATA),
        int(Command.RAM_LOAD_END),
    ]
    client = FakeClient()
    assert check_ram_crc(ctx(client), CheckRamCrcRequest(prepared_ram())).ok
    assert command_ids(client) == [int(Command.RAM_CHECK_CRC)]


def test_execution_ops_send_only_their_command() -> None:
    client = FakeClient()
    assert run_flash_app(ctx(client), RunFlashAppRequest(0x082400)).ok
    assert command_ids(client) == [int(Command.RUN)]
    assert client.calls[0][1] == (int(Target.FLASH_APP), *split_u32(0x082400), 0)
    client = FakeClient()
    entry_point = prepared_ram().entry_point
    result = run_ram_image(ctx(client), RunRamImageRequest(entry_point))
    assert result.ok
    assert command_ids(client) == [int(Command.RUN_RAM)]
    assert client.calls[0][1] == (*split_u32(entry_point), 0)
    assert result.summary == {"entry_point": entry_point}
    client = FakeClient()
    assert reset_target(ctx(client), ResetTargetRequest()).ok
    assert command_ids(client) == [int(Command.RESET)]


def test_run_operations_forward_wire_attempt_observer_to_their_transaction() -> None:
    flash_events: list[int] = []
    flash_client = FakeClient()
    assert run_flash_app(
        ctx(flash_client),
        RunFlashAppRequest(0x082400),
        wire_attempt_observer=flash_events.append,
    ).ok
    assert flash_events == [int(Command.RUN)]

    ram_events: list[int] = []
    ram_client = FakeClient()
    assert run_ram_image(
        ctx(ram_client),
        RunRamImageRequest(0x8000),
        wire_attempt_observer=ram_events.append,
    ).ok
    assert ram_events == [int(Command.RUN_RAM)]


@pytest.mark.parametrize("entry_point", [True, -1, 1.0])
def test_run_ram_request_rejects_invalid_entry_point(entry_point) -> None:
    with pytest.raises(ValueError):
        RunRamImageRequest(entry_point)


@pytest.mark.parametrize("entry_point", [True, -1, 1.0])
def test_run_flash_request_rejects_invalid_entry_point(entry_point) -> None:
    with pytest.raises(ValueError):
        RunFlashAppRequest(entry_point)


def test_unsupported_cpu2_command_returns_operation_error() -> None:
    result = boot_cpu2_run_cpu1(
        OperationContext(SimpleNamespace(client=FakeClient()), CPU2_PROFILE),
        BootCpu2RunCpu1Request(),
    )
    assert not result.ok
    assert result.error and result.error.code == "UNSUPPORTED_OPERATION"


def test_run_unsupported_target_does_not_invoke_wire_attempt_observer() -> None:
    events: list[int] = []
    result = run_flash_app(
        OperationContext(SimpleNamespace(client=FakeClient()), CPU2_PROFILE),
        RunFlashAppRequest(0x082400),
        wire_attempt_observer=events.append,
    )

    assert not result.ok
    assert result.error and result.error.code == "UNSUPPORTED_OPERATION"
    assert events == []


def test_service_reuse_force_reload_load_attach_and_checks() -> None:
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    reused = ensure_service_attached(flash_ctx(client))
    assert reused.reused and command_ids(client) == [int(Command.GET_SERVICE_STATUS)]

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(), service_words()]})
    reloaded = ensure_service_attached(flash_ctx(client, force=True))
    assert reloaded.attach_performed
    assert int(Command.SERVICE_ATTACH) in command_ids(client)
    assert command_ids(client)[1:7] == [
        int(Command.RAM_LOAD_BEGIN),
        *([int(Command.RAM_LOAD_DATA)] * 4),
        int(Command.RAM_LOAD_END),
    ]
    attach = next(payload for command, payload in client.calls if command == int(Command.SERVICE_ATTACH))
    assert attach == (*split_u32(prepared_service().header_address), *split_u32(0xAABBCCDD), *split_u32(32), 0)

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0), service_words()]})
    assert ensure_service_attached(flash_ctx(client)).attach_performed
    assert command_ids(client)[1:7] == [
        int(Command.RAM_LOAD_BEGIN),
        *([int(Command.RAM_LOAD_DATA)] * 4),
        int(Command.RAM_LOAD_END),
    ]
    attach = next(payload for command, payload in client.calls if command == int(Command.SERVICE_ATTACH))
    assert attach == (*split_u32(prepared_service().header_address), *split_u32(0xAABBCCDD), *split_u32(32), 0)

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(abi_major=3), service_words(abi_major=3)]})
    result = erase_sector_mask(flash_ctx(client), EraseSectorMaskRequest(0x2))
    assert not result.ok and result.error and result.error.code == "SERVICE_ABI_MISMATCH"

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(capabilities=1), service_words(capabilities=1)]})
    result = erase_sector_mask(flash_ctx(client), EraseSectorMaskRequest(0x2))
    assert not result.ok and result.error and result.error.code == "SERVICE_CAPABILITY_MISMATCH"


def test_flash_ops_attach_order_protection_and_no_extra_work() -> None:
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    assert erase_flash_image_area(flash_ctx(client), EraseFlashImageAreaRequest(prepared_flash(0x6))).ok
    assert command_ids(client)[1:] == [int(Command.ERASE), int(Command.ERASE)]
    assert client.calls[1][1][0] == CPU1_PROFILE.memory_map.flash.metadata_sector_mask

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    result = erase_sector_mask(flash_ctx(client), EraseSectorMaskRequest(0x1))
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "FORBIDDEN_SECTOR"
    assert command_ids(client) == []

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    assert program_flash_image(flash_ctx(client), ProgramFlashImageRequest(prepared_flash())).ok
    assert command_ids(client) == [int(Command.GET_SERVICE_STATUS), int(Command.PROGRAM_BEGIN), int(Command.PROGRAM_DATA), int(Command.PROGRAM_END)]

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    assert verify_flash_image(flash_ctx(client), VerifyFlashImageRequest(prepared_flash())).ok
    assert command_ids(client) == [int(Command.GET_SERVICE_STATUS), int(Command.VERIFY_BEGIN), int(Command.VERIFY_DATA), int(Command.VERIFY_END)]


def test_metadata_business_states_are_ok() -> None:
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words(metadata_valid=0, state=0, valid_record_count=0)]})
    result = append_boot_attempt(flash_ctx(client), AppendBootAttemptRequest())
    assert result.ok and result.summary["reason"] == "IMAGE_VALID_REQUIRED"
    assert int(Command.METADATA_APPEND_RECORD) not in command_ids(client)


def test_metadata_only_requests_reject_caller_identity() -> None:
    with pytest.raises(TypeError):
        AppendBootAttemptRequest(IDENTITY)
    with pytest.raises(TypeError):
        AppendAppConfirmedRequest(IDENTITY)

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words(metadata_valid=0, state=0, valid_record_count=0)]})
    result = append_app_confirmed(flash_ctx(client), AppendAppConfirmedRequest())
    assert result.ok and result.summary["reason"] == "IMAGE_VALID_REQUIRED"
    assert int(Command.METADATA_APPEND_RECORD) not in command_ids(client)

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words()]})
    result = append_app_confirmed(flash_ctx(client), AppendAppConfirmedRequest())
    assert result.ok and result.summary["reason"] == "BOOT_ATTEMPT_REQUIRED"
    assert int(Command.METADATA_APPEND_RECORD) not in command_ids(client)

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words(boot_attempt_count=1, app_confirmed=1)]})
    result = append_app_confirmed(flash_ctx(client), AppendAppConfirmedRequest())
    assert result.ok and result.summary["reason"] == "APP_CONFIRMED_ALREADY_EXISTS"
    assert int(Command.METADATA_APPEND_RECORD) not in command_ids(client)


def test_image_valid_only_writes_empty_metadata() -> None:
    same = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words()],
    })
    result = append_image_valid(flash_ctx(same), AppendImageValidRequest(prepared_flash()))
    assert result.ok and result.summary == {
        "written": False,
        "already_exists": True,
        "reason": "IMAGE_VALID_ALREADY_EXISTS",
    }
    assert int(Command.METADATA_APPEND_RECORD) not in command_ids(same)

    different = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words(entry_point=1)],
    })
    result = append_image_valid(
        flash_ctx(different), AppendImageValidRequest(prepared_flash())
    )
    assert result.ok and result.summary["reason"] == "IMAGE_VALID_ALREADY_EXISTS"
    assert int(Command.METADATA_APPEND_RECORD) not in command_ids(different)

    empty = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words(metadata_valid=0, state=0, valid_record_count=0)],
    })
    assert append_image_valid(flash_ctx(empty), AppendImageValidRequest(prepared_flash())).summary["written"]

    for state in (2, 3):
        invalid = FakeClient({
            int(Command.GET_SERVICE_STATUS): [service_words()],
            int(Command.GET_METADATA_SUMMARY): [metadata_words(metadata_valid=0, state=state)],
        })
        result = append_image_valid(flash_ctx(invalid), AppendImageValidRequest(prepared_flash()))
        assert result.summary["reason"] == "METADATA_INVALID"
        assert int(Command.METADATA_APPEND_RECORD) not in command_ids(invalid)


@pytest.mark.parametrize(
    ("count", "written"), ((0, True), (1, True), (2, True), (3, False)),
)
def test_boot_attempt_enforces_three_attempt_limit_and_metadata_payload(count, written) -> None:
    client = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words(boot_attempt_count=count, entry_point=0x088000)],
    })
    result = append_boot_attempt(flash_ctx(client), AppendBootAttemptRequest())
    assert result.ok and result.summary["written"] is written
    append_calls = [payload for command, payload in client.calls if command == int(Command.METADATA_APPEND_RECORD)]
    if written:
        assert append_calls[0][2:4] == split_u32(0x088000)
        assert append_calls[0][4:6] == split_u32(IDENTITY.image_size_words)
        assert append_calls[0][6:8] == split_u32(IDENTITY.image_crc32)
        assert append_calls[0][8:16] == (0,) * 8
    else:
        assert result.summary["reason"] == "BOOT_ATTEMPT_LIMIT_REACHED"
        assert not append_calls


@pytest.mark.parametrize(
    ("operation", "overrides", "reason"),
    (
        (append_boot_attempt, {"metadata_valid": 0, "state": 2}, "METADATA_INVALID"),
        (append_boot_attempt, {"boot_attempt_count": 1, "app_confirmed": 1}, "APP_CONFIRMED_ALREADY_EXISTS"),
        (append_app_confirmed, {"metadata_valid": 0, "state": 0, "valid_record_count": 0}, "IMAGE_VALID_REQUIRED"),
        (append_app_confirmed, {"boot_attempt_count": 0}, "BOOT_ATTEMPT_REQUIRED"),
        (append_app_confirmed, {"boot_attempt_count": 1, "app_confirmed": 1}, "APP_CONFIRMED_ALREADY_EXISTS"),
    ),
)
def test_metadata_append_business_rejections(operation, overrides, reason) -> None:
    client = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words(**overrides)],
    })
    result = operation(flash_ctx(client), AppendBootAttemptRequest() if operation is append_boot_attempt else AppendAppConfirmedRequest())
    assert result.ok and result.summary["reason"] == reason
    assert int(Command.METADATA_APPEND_RECORD) not in command_ids(client)


def test_metadata_writes_only_requested_record_type() -> None:
    for operation, request, expected, summary_words in (
        (
            append_image_valid,
            AppendImageValidRequest(prepared_flash()),
            MetadataRecordType.IMAGE_VALID,
            metadata_words(metadata_valid=0, state=0, valid_record_count=0),
        ),
        (
            append_boot_attempt,
            AppendBootAttemptRequest(),
            MetadataRecordType.BOOT_ATTEMPT,
            metadata_words(),
        ),
        (
            append_app_confirmed,
            AppendAppConfirmedRequest(),
            MetadataRecordType.APP_CONFIRMED,
            metadata_words(boot_attempt_count=1),
        ),
    ):
        client = FakeClient({
            int(Command.GET_SERVICE_STATUS): [service_words()],
            int(Command.GET_METADATA_SUMMARY): [summary_words],
        })
        assert operation(flash_ctx(client), request).ok
        append_calls = [payload for command, payload in client.calls if command == int(Command.METADATA_APPEND_RECORD)]
        assert len(append_calls) == 1
        assert append_calls[0][0] == int(expected)


def test_known_fatal_protocol_error_and_stop() -> None:
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.fail_on.add(int(Command.PROGRAM_DATA))
    result = program_flash_image(flash_ctx(client), ProgramFlashImageRequest(prepared_flash()))
    assert not result.ok
    assert result.error and result.error.code == "DSP_STATUS_ERROR"
    assert int(Command.PROGRAM_END) not in command_ids(client)


def test_progress_events_include_word_counts() -> None:
    events: list[ProgressEvent] = []
    client = FakeClient()
    assert load_ram_image(ctx(client, progress=events.append), LoadRamImageRequest(prepared_ram())).ok
    assert events[-1].stage == "RAM_LOAD_DATA"
    assert events[-1].current_words is not None and events[-1].total_words is not None and events[-1].chunk_words is not None

    for operation, request, stage in (
        (program_flash_image, ProgramFlashImageRequest(prepared_flash()), "PROGRAM_DATA"),
        (verify_flash_image, VerifyFlashImageRequest(prepared_flash()), "VERIFY_DATA"),
    ):
        events.clear()
        client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
        assert operation(flash_ctx(client, progress=events.append), request).ok
        assert events[-1].stage == stage
        assert events[-1].current_words and events[-1].total_words and events[-1].chunk_words

    events.clear()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0), service_words()]})
    assert ensure_service_attached(flash_ctx(client, progress=events.append)).attach_performed
    assert events[-1].stage == "RAM_LOAD_SERVICE"
    assert events[-1].current_words and events[-1].total_words and events[-1].chunk_words


@pytest.mark.parametrize(
    ("operation", "operation_request", "stage"),
    (
        (program_flash_image, ProgramFlashImageRequest(prepared_flash_words(16)), "PROGRAM_DATA"),
        (verify_flash_image, VerifyFlashImageRequest(prepared_flash_words(16)), "VERIFY_DATA"),
    ),
)
def test_flash_transfer_progress_reports_each_packet(operation, operation_request, stage) -> None:
    events: list[ProgressEvent] = []
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})

    assert operation(flash_ctx(client, progress=events.append), operation_request).ok

    transfer = [event for event in events if event.stage == stage]
    assert [(event.current_words, event.total_words, event.chunk_words) for event in transfer] == [
        (8, 16, 8),
        (16, 16, 8),
    ]


def test_service_load_progress_is_real_and_reuse_emits_none() -> None:
    events: list[ProgressEvent] = []
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0), service_words()]})
    assert ensure_service_attached(flash_ctx(client, progress=events.append)).attach_performed
    load = [event for event in events if event.stage == "RAM_LOAD_SERVICE"]
    assert len(load) > 1
    assert load[0].current_words < load[0].total_words
    assert load[-1].current_words == load[-1].total_words == prepared_service().total_words

    events.clear()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    assert ensure_service_attached(flash_ctx(client, progress=events.append)).reused
    assert not events


def test_erase_progress_uses_cpu1_sector_words_without_splitting_commands() -> None:
    flash = CPU1_PROFILE.memory_map.flash
    effective_mask = 0x6
    metadata_mask = flash.metadata_sector_mask
    total = sum(
        sector.end_exclusive - sector.start
        for sector in flash.sectors
        if effective_mask & (1 << sector.bit_index)
    )
    metadata_words = sum(
        sector.end_exclusive - sector.start
        for sector in flash.sectors
        if metadata_mask & (1 << sector.bit_index)
    )
    events: list[ProgressEvent] = []
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})

    assert erase_flash_image_area(
        flash_ctx(client, progress=events.append),
        EraseFlashImageAreaRequest(prepared_flash(effective_mask)),
    ).ok

    erase_events = [event for event in events if event.stage == "ERASE"]
    assert [(event.current_words, event.total_words) for event in erase_events] == [
        (0, total),
        (metadata_words, total),
        (total, total),
    ]
    assert all(event.details["current_bytes"] == event.current_words * 2 for event in erase_events)
    assert sum(command == int(Command.ERASE) for command in command_ids(client)) == 2


def test_erase_sector_mask_progress_and_failed_command_boundary() -> None:
    flash = CPU1_PROFILE.memory_map.flash
    mask = 0x4
    total = sum(
        sector.end_exclusive - sector.start
        for sector in flash.sectors
        if mask & (1 << sector.bit_index)
    )
    events: list[ProgressEvent] = []
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    assert erase_sector_mask(
        flash_ctx(client, progress=events.append), EraseSectorMaskRequest(mask)
    ).ok
    assert [(event.current_words, event.total_words) for event in events] == [(0, total), (total, total)]
    assert command_ids(client).count(int(Command.ERASE)) == 1

    events.clear()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.fail_on.add(int(Command.ERASE))
    assert not erase_sector_mask(
        flash_ctx(client, progress=events.append), EraseSectorMaskRequest(mask)
    ).ok
    assert [(event.current_words, event.total_words) for event in events] == [(0, total)]


def test_erase_progress_falls_back_when_selected_sector_mapping_is_missing() -> None:
    flash = CPU1_PROFILE.memory_map.flash
    incomplete = replace(flash, sectors=tuple(sector for sector in flash.sectors if sector.bit_index != 2))
    target = replace(CPU1_PROFILE, memory_map=replace(CPU1_PROFILE.memory_map, flash=incomplete))
    events: list[ProgressEvent] = []
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    context = replace(flash_ctx(client, progress=events.append), target=target)

    assert erase_sector_mask(context, EraseSectorMaskRequest(0x4)).ok
    assert all(event.current_words is None and event.total_words is None for event in events)


@pytest.mark.parametrize(
    ("operation", "operation_request", "summary", "record_type"),
    (
        (
            append_image_valid,
            AppendImageValidRequest(prepared_flash()),
            metadata_words(metadata_valid=0, state=0, valid_record_count=0),
            MetadataRecordType.IMAGE_VALID,
        ),
        (append_boot_attempt, AppendBootAttemptRequest(), metadata_words(), MetadataRecordType.BOOT_ATTEMPT),
        (
            append_app_confirmed,
            AppendAppConfirmedRequest(),
            metadata_words(boot_attempt_count=1),
            MetadataRecordType.APP_CONFIRMED,
        ),
    ),
)
def test_metadata_write_progress_is_zero_to_fixed_record_words(
    operation, operation_request, summary, record_type
) -> None:
    events: list[ProgressEvent] = []
    client = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [summary],
    })

    assert operation(flash_ctx(client, progress=events.append), operation_request).summary["written"]
    assert [(event.current_words, event.total_words, event.chunk_words) for event in events] == [
        (0, 64, 0),
        (64, 64, 64),
    ]
    assert all(event.details["record_type"] == record_type.name for event in events)
    assert all(event.details["current_bytes"] == event.current_words * 2 for event in events)
    assert all(event.details["total_bytes"] == 128 for event in events)
    assert command_ids(client).count(int(Command.METADATA_APPEND_RECORD)) == 1


def test_metadata_no_write_and_failed_write_do_not_emit_completion_progress() -> None:
    for summary in (
        metadata_words(metadata_valid=0, state=0, valid_record_count=0),
        metadata_words(metadata_valid=0, state=2),
        metadata_words(boot_attempt_count=1, app_confirmed=1),
        metadata_words(boot_attempt_count=3),
    ):
        events: list[ProgressEvent] = []
        client = FakeClient({
            int(Command.GET_SERVICE_STATUS): [service_words()],
            int(Command.GET_METADATA_SUMMARY): [summary],
        })
        append_boot_attempt(flash_ctx(client, progress=events.append), AppendBootAttemptRequest())
        assert not events

    events = []
    client = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words()],
    })
    client.fail_on.add(int(Command.METADATA_APPEND_RECORD))
    assert not append_boot_attempt(
        flash_ctx(client, progress=events.append), AppendBootAttemptRequest()
    ).ok
    assert [(event.current_words, event.total_words) for event in events] == [(0, 64)]

    for summary in (
        metadata_words(boot_attempt_count=0),
        metadata_words(boot_attempt_count=1, app_confirmed=1),
    ):
        events = []
        client = FakeClient({
            int(Command.GET_SERVICE_STATUS): [service_words()],
            int(Command.GET_METADATA_SUMMARY): [summary],
        })
        append_app_confirmed(
            flash_ctx(client, progress=events.append), AppendAppConfirmedRequest()
        )
        assert not events

    events = []
    client = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words(boot_attempt_count=1)],
    })
    client.fail_on.add(int(Command.METADATA_APPEND_RECORD))
    result = append_app_confirmed(
        flash_ctx(client, progress=events.append), AppendAppConfirmedRequest()
    )
    assert not result.ok
    assert [(event.current_words, event.total_words) for event in events] == [(0, 64)]


def test_invalid_data_capacities_fail_before_begin() -> None:
    client = FakeClient()
    client.protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, 5, 0)
    result = load_ram_image(ctx(client), LoadRamImageRequest(prepared_ram()))
    assert not result.ok and command_ids(client) == []

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0), service_words()]})
    client.protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, 6, 0)
    assert ensure_service_attached(flash_ctx(client)).attach_performed
    assert command_ids(client).count(int(Command.RAM_LOAD_DATA)) == 32

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, 12, 0)
    result = program_flash_image(flash_ctx(client), ProgramFlashImageRequest(prepared_flash()))
    assert not result.ok and command_ids(client) == []


def test_all_data_payloads_fit_negotiated_limit() -> None:
    limit = 14

    client = FakeClient()
    client.protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, limit, 0)
    assert load_ram_image(ctx(client), LoadRamImageRequest(prepared_ram(tuple(range(20))))).ok
    assert all(len(payload) <= limit for command, payload in client.calls if command == int(Command.RAM_LOAD_DATA))

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(), service_words()]})
    client.protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, limit, 0)
    ensure_service_attached(flash_ctx(client, force=True))
    assert all(len(payload) <= limit for command, payload in client.calls if command == int(Command.RAM_LOAD_DATA))

    for operation, request, data_command in (
        (program_flash_image, ProgramFlashImageRequest(prepared_flash()), Command.PROGRAM_DATA),
        (verify_flash_image, VerifyFlashImageRequest(prepared_flash()), Command.VERIFY_DATA),
    ):
        client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
        client.protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, limit, 0)
        assert operation(flash_ctx(client), request).ok
        assert all(len(payload) <= limit for command, payload in client.calls if command == int(data_command))


def test_operation_completion_model_and_serialization() -> None:
    success = OperationResult(True, "op", "target", "done", {})
    failure = OperationResult(
        False,
        "op",
        "target",
        "failed",
        {},
        error=OperationErrorInfo("FAILED", "failed", "failed"),
    )
    assert success.completion is OperationCompletion.SUCCEEDED and success.ok
    assert failure.completion is OperationCompletion.FAILED and not failure.ok

    cancellation = OperationCancellationInfo("DATA", 1, 2, True, False, False, recovery_action="RESTART_RAM_LOAD")
    result = OperationResult(
        False,
        "op",
        "target",
        "DATA",
        {},
        completion=OperationCompletion.CANCELLED,
        cancellation=cancellation,
    )
    plain = operation_result_to_dict(result)
    assert plain["completion"] == "cancelled"
    assert plain["cancellation"]["recovery_action"] == "RESTART_RAM_LOAD"

    with pytest.raises(RuntimeError, match="error details"):
        OperationResult(False, "op", "target", "failed", {}, completion=OperationCompletion.FAILED)
    with pytest.raises(ValueError):
        OperationResult(True, "op", "target", "done", {}, completion=OperationCompletion.CANCELLED)
    with pytest.raises(ValueError):
        OperationCancellationInfo("", 0, 0, True, False, False)
    with pytest.raises(ValueError):
        OperationCancellationInfo("x", 1, 0, True, False, False)
    with pytest.raises(ValueError):
        OperationCancellationInfo("x", 0, 0, True, True, True)
    with pytest.raises(ValueError):
        OperationCancellationInfo("x", 0, 0, False, False, False, erase_before_retry_required=True)
    with pytest.raises(ValueError):
        OperationCancellationInfo("x", 0, 0, True, False, False, recovery_action="INVALID")


def test_pre_requested_cancellation_sends_no_protocol_commands() -> None:
    token = ScriptedCancellation(True)
    client = FakeClient()
    assert load_ram_image(ctx(client, cancellation=token), LoadRamImageRequest(prepared_ram())).completion is OperationCompletion.CANCELLED
    assert client.calls == []

    for operation, request, recovery_action in (
        (program_flash_image, ProgramFlashImageRequest(prepared_flash()), "RESTART_PROGRAM"),
        (verify_flash_image, VerifyFlashImageRequest(prepared_flash()), "RESTART_VERIFY"),
        (erase_sector_mask, EraseSectorMaskRequest(0x2), "NONE"),
        (append_image_valid, AppendImageValidRequest(prepared_flash()), "NONE"),
    ):
        client = FakeClient()
        result = operation(flash_ctx(client, cancellation=token), request)
        assert result.completion is OperationCompletion.CANCELLED
        assert result.cancellation and result.cancellation.recovery_action == recovery_action
        assert not result.cancellation.partial_flash_programmed
        assert not result.cancellation.erase_before_retry_required
        assert client.calls == []

    client = FakeClient()
    service = ensure_service_attached(flash_ctx(client, cancellation=token))
    assert isinstance(service, ServiceRuntimeCancellation)
    assert client.calls == []


@pytest.mark.parametrize(
    ("operation", "request_value", "recovery_action"),
    (
        (program_flash_image, ProgramFlashImageRequest(prepared_flash()), "RESTART_PROGRAM"),
        (verify_flash_image, VerifyFlashImageRequest(prepared_flash()), "RESTART_VERIFY"),
    ),
)
def test_flash_pre_cancellation_does_not_read_data_capacity(operation, request_value, recovery_action) -> None:
    token = ScriptedCancellation(True)
    client = NoFlashCapacityClient()
    result = operation(flash_ctx(client, cancellation=token), request_value)
    assert result.completion is OperationCompletion.CANCELLED
    assert result.cancellation and result.cancellation.recovery_action == recovery_action
    assert result.cancellation.service_attached is None
    assert client.calls == []


@pytest.mark.parametrize(
    ("operation", "request_value", "begin_command", "recovery_action"),
    (
        (program_flash_image, ProgramFlashImageRequest(prepared_flash()), Command.PROGRAM_BEGIN, "RESTART_PROGRAM"),
        (verify_flash_image, VerifyFlashImageRequest(prepared_flash()), Command.VERIFY_BEGIN, "RESTART_VERIFY"),
    ),
)
def test_flash_cancel_after_service_status_before_begin(
    operation, request_value, begin_command, recovery_action
) -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.callbacks[int(Command.GET_SERVICE_STATUS)] = [token.request]
    result = operation(flash_ctx(client, cancellation=token), request_value)
    assert result.completion is OperationCompletion.CANCELLED
    assert result.cancellation and result.cancellation.recovery_action == recovery_action
    assert result.cancellation.service_attached is True
    assert int(begin_command) not in command_ids(client)


@pytest.mark.parametrize(
    ("operation", "request_value", "data_command", "end_command", "end_payload"),
    (
        (
            load_ram_image,
            LoadRamImageRequest(prepared_ram(tuple(range(20)))),
            Command.RAM_LOAD_DATA,
            Command.RAM_LOAD_END,
            (*split_u32(3), *split_u32(20), *split_u32(0xCAFECAFE)),
        ),
        (
            program_flash_image,
            ProgramFlashImageRequest(prepared_flash_words(24)),
            Command.PROGRAM_DATA,
            Command.PROGRAM_END,
            (*split_u32(3), *split_u32(24), 0, 0),
        ),
        (
            verify_flash_image,
            VerifyFlashImageRequest(prepared_flash_words(24)),
            Command.VERIFY_DATA,
            Command.VERIFY_END,
            (*split_u32(3), *split_u32(24), 0, 0),
        ),
    ),
)
def test_partial_transfer_cleanup_uses_original_totals_and_accepts_count_mismatch(
    operation, request_value, data_command, end_command, end_payload
) -> None:
    token = ScriptedCancellation()
    responses = {} if operation is load_ram_image else {int(Command.GET_SERVICE_STATUS): [service_words()]}
    client = FakeClient(responses)
    client.callbacks[int(data_command)] = [token.request]
    client.failures[int(end_command)] = [ProtocolStatusError(int(end_command), int(Status.TOTAL_COUNT_MISMATCH))]
    operation_ctx = ctx(client, cancellation=token) if operation is load_ram_image else flash_ctx(client, cancellation=token)
    result = operation(operation_ctx, request_value)
    assert result.completion is OperationCompletion.CANCELLED
    assert command_ids(client).count(int(data_command)) == 1
    end_calls = [payload for command, payload in client.calls if command == int(end_command)]
    assert end_calls == [end_payload]


def test_program_recovery_fields_before_and_after_successful_data() -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.callbacks[int(Command.PROGRAM_BEGIN)] = [token.request]
    result = program_flash_image(
        flash_ctx(client, cancellation=token),
        ProgramFlashImageRequest(prepared_flash_words(24)),
    )
    assert result.completion is OperationCompletion.CANCELLED
    assert result.cancellation and not result.cancellation.partial_flash_programmed
    assert not result.cancellation.erase_before_retry_required
    assert result.cancellation.recovery_action == "RESTART_PROGRAM"

    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.callbacks[int(Command.PROGRAM_DATA)] = [token.request]
    result = program_flash_image(
        flash_ctx(client, cancellation=token),
        ProgramFlashImageRequest(prepared_flash_words(24)),
    )
    assert result.cancellation and result.cancellation.partial_flash_programmed
    assert result.cancellation.erase_before_retry_required
    assert result.cancellation.recovery_action == "ERASE_AND_RESTART_PROGRAM"


@pytest.mark.parametrize(
    ("failure", "exception_name"),
    (
        (ProtocolStatusError(int(Command.RAM_LOAD_END), int(Status.INVALID_STATE)), "ProtocolStatusError"),
        (ProtocolDecodeError("bad cleanup response"), "ProtocolDecodeError"),
    ),
)
def test_cancellation_cleanup_failure_requires_reconnect(failure, exception_name) -> None:
    token = ScriptedCancellation()
    client = FakeClient()
    client.callbacks[int(Command.RAM_LOAD_DATA)] = [token.request]
    client.failures[int(Command.RAM_LOAD_END)] = [failure]
    result = load_ram_image(
        ctx(client, cancellation=token),
        LoadRamImageRequest(prepared_ram(tuple(range(20)))),
    )
    assert result.completion is OperationCompletion.FAILED
    assert result.error and result.error.code == "CANCELLATION_CLEANUP_FAILED"
    assert result.error.details["exception_type"] == exception_name
    assert command_ids(client).count(int(Command.RAM_LOAD_END)) == 1
    assert result.cancellation and not result.cancellation.protocol_state_clean
    assert result.cancellation.outcome_uncertain and result.cancellation.connection_recovery_required
    assert result.cancellation.recovery_action == "RECONNECT_AND_RESTART_RAM_LOAD"


@pytest.mark.parametrize(
    ("operation", "request_value", "data_command", "expected_action"),
    (
        (load_ram_image, LoadRamImageRequest(prepared_ram()), Command.RAM_LOAD_DATA, "NONE"),
        (program_flash_image, ProgramFlashImageRequest(prepared_flash()), Command.PROGRAM_DATA, "NONE"),
        (verify_flash_image, VerifyFlashImageRequest(prepared_flash()), Command.VERIFY_DATA, "NONE"),
    ),
)
def test_cancel_after_final_data_completes_normally(operation, request_value, data_command, expected_action) -> None:
    token = ScriptedCancellation()
    responses = {} if operation is load_ram_image else {int(Command.GET_SERVICE_STATUS): [service_words()]}
    client = FakeClient(responses)
    client.callbacks[int(data_command)] = [token.request]
    operation_ctx = ctx(client, cancellation=token) if operation is load_ram_image else flash_ctx(client, cancellation=token)
    result = operation(operation_ctx, request_value)
    assert result.completion is OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST and result.ok
    assert result.cancellation and result.cancellation.current_words == result.cancellation.total_words
    assert result.cancellation.recovery_action == expected_action


def test_cancel_after_normal_end_completes_normally() -> None:
    token = ScriptedCancellation()
    client = FakeClient()
    client.callbacks[int(Command.RAM_LOAD_END)] = [token.request]
    result = load_ram_image(ctx(client, cancellation=token), LoadRamImageRequest(prepared_ram()))
    assert result.completion is OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST and result.ok


def test_service_load_begin_cancellation_cleans_up() -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0)]})
    client.callbacks[int(Command.RAM_LOAD_BEGIN)] = [token.request]
    result = erase_sector_mask(flash_ctx(client, cancellation=token), EraseSectorMaskRequest(0x2))
    assert result.completion is OperationCompletion.CANCELLED
    assert command_ids(client) == [
        int(Command.GET_SERVICE_STATUS),
        int(Command.RAM_LOAD_BEGIN),
        int(Command.RAM_LOAD_END),
    ]
    assert result.cancellation and result.cancellation.service_attached is False


def test_partial_service_load_cleans_up_and_skips_flash_action() -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0)]})
    client.callbacks[int(Command.RAM_LOAD_DATA)] = [None, token.request]
    client.failures[int(Command.RAM_LOAD_END)] = [
        ProtocolStatusError(int(Command.RAM_LOAD_END), int(Status.TOTAL_COUNT_MISMATCH)),
    ]
    result = erase_sector_mask(flash_ctx(client, cancellation=token), EraseSectorMaskRequest(0x2))
    assert result.completion is OperationCompletion.CANCELLED
    assert result.cancellation and result.cancellation.recovery_action == "RESTART_SERVICE_LOAD"
    assert command_ids(client).count(int(Command.RAM_LOAD_END)) == 1
    main_begin = [payload for command, payload in client.calls if command == int(Command.RAM_LOAD_BEGIN)][0]
    cleanup_end = [payload for command, payload in client.calls if command == int(Command.RAM_LOAD_END)][0]
    assert cleanup_end == (*split_u32(main_begin[1]), *split_u32(32), *split_u32(0xAABBCCDD))
    assert int(Command.RAM_CHECK_CRC) not in command_ids(client)
    assert int(Command.SERVICE_ATTACH) not in command_ids(client)
    assert int(Command.ERASE) not in command_ids(client)


def test_cancel_after_final_service_data_is_top_level_cancelled() -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0)]})
    client.callbacks[int(Command.RAM_LOAD_DATA)] = [None, None, None, token.request]
    result = erase_sector_mask(flash_ctx(client, cancellation=token), EraseSectorMaskRequest(0x2))
    assert result.completion is OperationCompletion.CANCELLED
    assert result.cancellation and result.cancellation.recovery_action == "RESTART_SERVICE_LOAD"
    assert int(Command.RAM_CHECK_CRC) not in command_ids(client)
    assert int(Command.ERASE) not in command_ids(client)


def test_cancel_after_service_attach_skips_requested_operation() -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0)]})
    client.callbacks[int(Command.SERVICE_ATTACH)] = [token.request]
    result = erase_sector_mask(flash_ctx(client, cancellation=token), EraseSectorMaskRequest(0x2))
    assert result.completion is OperationCompletion.CANCELLED
    assert result.cancellation and result.cancellation.service_attached is True
    assert int(Command.ERASE) not in command_ids(client)


def test_erase_and_metadata_transactions_are_atomic() -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.callbacks[int(Command.ERASE)] = [token.request]
    result = erase_flash_image_area(
        flash_ctx(client, cancellation=token),
        EraseFlashImageAreaRequest(prepared_flash(0x6)),
    )
    assert result.completion is OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST
    assert command_ids(client).count(int(Command.ERASE)) == 2

    token = ScriptedCancellation()
    client = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words(metadata_valid=0, state=0, valid_record_count=0)],
    })
    client.callbacks[int(Command.METADATA_APPEND_RECORD)] = [token.request]
    result = append_image_valid(
        flash_ctx(client, cancellation=token),
        AppendImageValidRequest(prepared_flash()),
    )
    assert result.completion is OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST
    assert command_ids(client).count(int(Command.METADATA_APPEND_RECORD)) == 1

    token = ScriptedCancellation()
    client = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words(metadata_valid=0, state=0, valid_record_count=0)],
    })
    client.callbacks[int(Command.GET_METADATA_SUMMARY)] = [token.request]
    result = append_image_valid(
        flash_ctx(client, cancellation=token),
        AppendImageValidRequest(prepared_flash()),
    )
    assert result.completion is OperationCompletion.CANCELLED
    assert int(Command.METADATA_APPEND_RECORD) not in command_ids(client)


def test_cancellable_progress_boundaries_are_marked() -> None:
    events: list[ProgressEvent] = []
    assert load_ram_image(ctx(progress=events.append), LoadRamImageRequest(prepared_ram())).ok
    assert events[-1].stage == "RAM_LOAD_DATA" and events[-1].cancellation_supported

    for operation, request, stage in (
        (program_flash_image, ProgramFlashImageRequest(prepared_flash()), "PROGRAM_DATA"),
        (verify_flash_image, VerifyFlashImageRequest(prepared_flash()), "VERIFY_DATA"),
    ):
        events.clear()
        client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
        assert operation(flash_ctx(client, progress=events.append), request).ok
        assert events[-1].stage == stage and events[-1].cancellation_supported

    assert not ProgressEvent("op", "target", "OTHER", "message").cancellation_supported


@pytest.mark.parametrize(
    ("operation", "request_value", "data_command", "end_command", "expected_action"),
    (
        (
            program_flash_image,
            ProgramFlashImageRequest(prepared_flash_words(24)),
            Command.PROGRAM_DATA,
            Command.PROGRAM_END,
            "RECONNECT_ERASE_AND_RESTART_PROGRAM",
        ),
        (
            verify_flash_image,
            VerifyFlashImageRequest(prepared_flash_words(24)),
            Command.VERIFY_DATA,
            Command.VERIFY_END,
            "RECONNECT_AND_RESTART_VERIFY",
        ),
    ),
)
def test_flash_cleanup_failure_reports_operation_specific_reconnect_action(
    operation, request_value, data_command, end_command, expected_action
) -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.callbacks[int(data_command)] = [token.request]
    client.failures[int(end_command)] = [ProtocolDecodeError("cleanup failed")]
    result = operation(flash_ctx(client, cancellation=token), request_value)
    assert result.completion is OperationCompletion.FAILED
    assert result.error and result.error.code == "CANCELLATION_CLEANUP_FAILED"
    assert result.cancellation and result.cancellation.recovery_action == expected_action
    assert command_ids(client).count(int(end_command)) == 1


def test_service_cleanup_failure_reports_reconnect_and_skips_flash() -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0)]})
    client.callbacks[int(Command.RAM_LOAD_DATA)] = [None, token.request]
    client.failures[int(Command.RAM_LOAD_END)] = [ProtocolDecodeError("cleanup failed")]
    result = erase_sector_mask(flash_ctx(client, cancellation=token), EraseSectorMaskRequest(0x2))
    assert result.completion is OperationCompletion.FAILED
    assert result.error and result.error.code == "CANCELLATION_CLEANUP_FAILED"
    assert result.cancellation and result.cancellation.recovery_action == "RECONNECT_AND_RESTART_SERVICE_LOAD"
    assert int(Command.ERASE) not in command_ids(client)


def test_ordinary_data_and_final_end_failures_take_precedence_over_cancellation() -> None:
    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.callbacks[int(Command.PROGRAM_DATA)] = [token.request]
    client.fail_on.add(int(Command.PROGRAM_DATA))
    result = program_flash_image(flash_ctx(client, cancellation=token), ProgramFlashImageRequest(prepared_flash()))
    assert result.completion is OperationCompletion.FAILED
    assert result.error and result.error.code == "DSP_STATUS_ERROR"
    assert int(Command.PROGRAM_END) not in command_ids(client)

    token = ScriptedCancellation()
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    client.callbacks[int(Command.VERIFY_DATA)] = [token.request]
    client.failures[int(Command.VERIFY_END)] = [
        ProtocolStatusError(int(Command.VERIFY_END), int(Status.TOTAL_COUNT_MISMATCH))
    ]
    result = verify_flash_image(flash_ctx(client, cancellation=token), VerifyFlashImageRequest(prepared_flash()))
    assert result.completion is OperationCompletion.FAILED
    assert result.error and result.error.code == "DSP_STATUS_ERROR"


def test_cancel_after_metadata_noop_returns_completed_after_request() -> None:
    token = ScriptedCancellation()
    client = FakeClient({
        int(Command.GET_SERVICE_STATUS): [service_words()],
        int(Command.GET_METADATA_SUMMARY): [metadata_words()],
    })
    client.callbacks[int(Command.GET_METADATA_SUMMARY)] = [token.request]
    result = append_image_valid(
        flash_ctx(client, cancellation=token),
        AppendImageValidRequest(prepared_flash()),
    )
    assert result.completion is OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST
    assert result.summary["reason"] == "IMAGE_VALID_ALREADY_EXISTS"
    assert int(Command.METADATA_APPEND_RECORD) not in command_ids(client)
