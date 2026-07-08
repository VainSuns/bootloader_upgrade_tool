from __future__ import annotations

from types import SimpleNamespace

from bootloader_upgrade_tool.core.client import ProtocolStatusError
from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.images.models import ImageIdentity, PreparedFlashImage, PreparedRamImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import (
    AppendAppConfirmedRequest,
    AppendBootAttemptRequest,
    AppendImageValidRequest,
    BootCpu2RunCpu1Request,
    CheckRamCrcRequest,
    EraseFlashImageAreaRequest,
    EraseSectorMaskRequest,
    FlashOperationContext,
    LoadRamImageRequest,
    OperationContext,
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
    operation_result_to_dict,
    program_flash_image,
    reset_target,
    run_flash_app,
    run_ram_image,
    verify_flash_image,
    get_metadata_summary,
)
import bootloader_upgrade_tool.operations.metadata_ops as metadata_ops
import bootloader_upgrade_tool.operations.status_ops as status_ops
from bootloader_upgrade_tool.operations._service_runtime import ensure_service_attached
from bootloader_upgrade_tool.protocol.constants import Command, MetadataRecordType, ServiceState
from bootloader_upgrade_tool.protocol.models import DeviceInfo, MetadataSummary, split_u32
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


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


def prepared_ram() -> PreparedRamImage:
    image = firmware(0x008000)
    return PreparedRamImage(image, image.entry_point, image.total_words, 0xCAFECAFE)


def prepared_service() -> PreparedServiceImage:
    image = firmware(0x010000, tuple(range(32)))
    return PreparedServiceImage(image, 0x010000, 0x010020, 0x010030, 32, 0xAABBCCDD, 0xF)


def device_info() -> DeviceInfo:
    return DeviceInfo(0x377D, 1, 1, 0, 0, 1, 0, 256, 8, 2, 2)


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
        state=0,
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
    abi_major: int = 1,
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
        1,
        *split_u32(capabilities),
        0,
        *split_u32(crc32),
        *split_u32(words),
    )


class FakeClient:
    def __init__(self, responses: dict[int, list[tuple[int, ...]]] | None = None) -> None:
        self.device_info = device_info()
        self.responses = responses or {}
        self.calls: list[tuple[int, tuple[int, ...]]] = []
        self.fail_on: set[int] = set()

    def transact(self, command: int, payload: tuple[int, ...] = (), *, timeout_ms: int | None = None) -> tuple[int, ...]:
        assert type(command) is int
        self.calls.append((command, tuple(payload)))
        if command in self.fail_on:
            raise ProtocolStatusError(command, 0x0202)
        queue = self.responses.get(command)
        return queue.pop(0) if queue else ()

    def __getattr__(self, name: str):
        raise AssertionError(f"operation used convenience method {name}")


def ctx(client: FakeClient | None = None, *, progress=None) -> OperationContext:
    return OperationContext(SimpleNamespace(client=client or FakeClient()), CPU1_PROFILE, progress)


def flash_ctx(client: FakeClient | None = None, *, progress=None, force: bool = False) -> FlashOperationContext:
    responses = {int(Command.GET_SERVICE_STATUS): [service_words()]}
    item = client or FakeClient(responses)
    return FlashOperationContext(
        SimpleNamespace(client=item),
        CPU1_PROFILE,
        progress,
        service=prepared_service(),
        force_service_attach=force,
    )


def command_ids(client: FakeClient) -> list[int]:
    return [command for command, _ in client.calls]


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
    client = FakeClient()
    assert run_ram_image(ctx(client), RunRamImageRequest(prepared_ram())).ok
    assert command_ids(client) == [int(Command.RUN_RAM)]
    client = FakeClient()
    assert reset_target(ctx(client), ResetTargetRequest()).ok
    assert command_ids(client) == [int(Command.RESET)]


def test_unsupported_cpu2_command_returns_operation_error() -> None:
    result = boot_cpu2_run_cpu1(
        OperationContext(SimpleNamespace(client=FakeClient()), CPU2_PROFILE),
        BootCpu2RunCpu1Request(),
    )
    assert not result.ok
    assert result.error and result.error.code == "UNSUPPORTED_OPERATION"


def test_service_reuse_force_reload_load_attach_and_checks() -> None:
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    reused = ensure_service_attached(flash_ctx(client))
    assert reused.reused and command_ids(client) == [int(Command.GET_SERVICE_STATUS)]

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(), service_words()]})
    reloaded = ensure_service_attached(flash_ctx(client, force=True))
    assert reloaded.attach_performed
    assert int(Command.SERVICE_ATTACH) in command_ids(client)

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(state=0), service_words()]})
    assert ensure_service_attached(flash_ctx(client)).attach_performed

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words(abi_major=2), service_words(abi_major=2)]})
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
    assert not result.ok and result.error and result.error.code == "FORBIDDEN_SECTOR"
    assert command_ids(client) == [int(Command.GET_SERVICE_STATUS)]

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    assert program_flash_image(flash_ctx(client), ProgramFlashImageRequest(prepared_flash())).ok
    assert command_ids(client) == [int(Command.GET_SERVICE_STATUS), int(Command.PROGRAM_BEGIN), int(Command.PROGRAM_DATA), int(Command.PROGRAM_END)]

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()]})
    assert verify_flash_image(flash_ctx(client), VerifyFlashImageRequest(prepared_flash())).ok
    assert command_ids(client) == [int(Command.GET_SERVICE_STATUS), int(Command.VERIFY_BEGIN), int(Command.VERIFY_DATA), int(Command.VERIFY_END)]


def test_metadata_business_states_are_ok() -> None:
    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words()]})
    result = append_image_valid(flash_ctx(client), AppendImageValidRequest(prepared_flash()))
    assert result.ok and result.summary["already_exists"] is True

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words(metadata_valid=0)]})
    result = append_boot_attempt(flash_ctx(client), AppendBootAttemptRequest(IDENTITY))
    assert result.ok and result.summary["reason"] == "IMAGE_VALID_REQUIRED"

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words(boot_attempt_count=1)]})
    result = append_boot_attempt(flash_ctx(client), AppendBootAttemptRequest(IDENTITY))
    assert result.ok and result.summary["reason"] == "BOOT_ATTEMPT_ALREADY_EXISTS"

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words(metadata_valid=0)]})
    result = append_app_confirmed(flash_ctx(client), AppendAppConfirmedRequest(IDENTITY))
    assert result.ok and result.summary["reason"] == "IMAGE_VALID_REQUIRED"

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words()]})
    result = append_app_confirmed(flash_ctx(client), AppendAppConfirmedRequest(IDENTITY))
    assert result.ok and result.summary["reason"] == "BOOT_ATTEMPT_REQUIRED"

    client = FakeClient({int(Command.GET_SERVICE_STATUS): [service_words()], int(Command.GET_METADATA_SUMMARY): [metadata_words(boot_attempt_count=1, app_confirmed=1)]})
    result = append_app_confirmed(flash_ctx(client), AppendAppConfirmedRequest(IDENTITY))
    assert result.ok and result.summary["reason"] == "APP_CONFIRMED_ALREADY_EXISTS"


def test_metadata_writes_only_requested_record_type() -> None:
    for operation, request, expected, summary_words in (
        (
            append_image_valid,
            AppendImageValidRequest(prepared_flash()),
            MetadataRecordType.IMAGE_VALID,
            metadata_words(entry_point=1),
        ),
        (
            append_boot_attempt,
            AppendBootAttemptRequest(IDENTITY),
            MetadataRecordType.BOOT_ATTEMPT,
            metadata_words(),
        ),
        (
            append_app_confirmed,
            AppendAppConfirmedRequest(IDENTITY),
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
