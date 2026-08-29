from __future__ import annotations

from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.core.client import ProtocolDecodeError, ProtocolStatusError
from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.images.models import PreparedServiceImage
from bootloader_upgrade_tool.operations import (
    ErrorDomain,
    FlashOperationContext,
    OperationCancellationInfo,
    OperationCompletion,
    OperationContext,
    attach_flash_service,
    get_service_status,
)
import bootloader_upgrade_tool.operations as operations
import bootloader_upgrade_tool.operations.service_ops as service_ops
from bootloader_upgrade_tool.operations._service_runtime import (
    ServiceRuntimeCancellation,
    ServiceRuntimeSummary,
)
from bootloader_upgrade_tool.protocol.constants import Command, ServiceState, Status
from bootloader_upgrade_tool.protocol.models import split_u32
from bootloader_upgrade_tool.targets import CPU1_PROFILE


def service_words(
    *,
    state: int = int(ServiceState.ATTACHED),
    abi_major: int = 2,
    abi_minor: int = 0,
    capabilities: int = 0xF,
    last_attach_status: int = 0,
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
        last_attach_status,
        *split_u32(crc32),
        *split_u32(words),
    )


class FakeClient:
    def __init__(
        self,
        response: tuple[int, ...] = (),
        failure: Exception | None = None,
    ) -> None:
        self.response = response
        self.failure = failure
        self.calls: list[tuple[int, tuple[int, ...]]] = []

    def transact(
        self,
        command: int,
        payload: tuple[int, ...] = (),
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, ...]:
        self.calls.append((command, tuple(payload)))
        if self.failure is not None:
            raise self.failure
        return self.response


class NoProtocolClient:
    def transact(self, *args: object, **kwargs: object) -> tuple[int, ...]:
        raise AssertionError("attach wrapper must not add protocol transactions")


def prepared_service() -> PreparedServiceImage:
    image = FirmwareImage(
        source_out_file="service.out",
        generated_hex_file="service.txt",
        entry_point=0x010000,
        blocks=(FirmwareBlock(0x010000, (1,)),),
        file_checksum="sha",
        format_info={},
    )
    return PreparedServiceImage(image, 0x010000, 1, 0xAABBCCDD, 0xF)


def operation_context(client: object) -> OperationContext:
    return OperationContext(SimpleNamespace(client=client), CPU1_PROFILE)


def flash_context(client: object | None = None) -> FlashOperationContext:
    return FlashOperationContext(
        SimpleNamespace(client=client or NoProtocolClient()),
        CPU1_PROFILE,
        service=prepared_service(),
    )


def runtime_summary(*, reused: bool, attach_performed: bool) -> ServiceRuntimeSummary:
    return ServiceRuntimeSummary(
        reused=reused,
        attach_performed=attach_performed,
        service_state=int(ServiceState.ATTACHED),
        abi_major=2,
        abi_minor=0,
        capabilities=0xF,
        loaded_image_crc32=0xAABBCCDD,
    )


def cancellation_info() -> OperationCancellationInfo:
    return OperationCancellationInfo(
        "RAM_LOAD_END",
        1,
        32,
        True,
        False,
        False,
        service_attached=False,
        recovery_action="RESTART_SERVICE_LOAD",
    )


def test_get_service_status_only_reads_and_decodes_service_status(monkeypatch) -> None:
    client = FakeClient(service_words(last_attach_status=7))
    monkeypatch.setattr(
        service_ops,
        "ensure_service_attached",
        lambda _ctx: pytest.fail("get_service_status must not attach the service"),
    )

    result = get_service_status(operation_context(client))

    assert result.ok
    assert result.operation == "get_service_status"
    assert result.stage == "GET_SERVICE_STATUS"
    assert result.summary == {
        "service_state": int(ServiceState.ATTACHED),
        "abi_major": 2,
        "abi_minor": 0,
        "reserved0": 0,
        "reserved1": 0,
        "capabilities": 0xF,
        "last_attach_status": 7,
        "loaded_image_crc32": 0xAABBCCDD,
        "loaded_image_words": 32,
    }
    assert client.calls == [(int(Command.GET_SERVICE_STATUS), ())]


def test_get_service_status_uses_standard_failure_result() -> None:
    client = FakeClient(
        failure=ProtocolStatusError(int(Command.GET_SERVICE_STATUS), int(Status.INVALID_STATE))
    )

    result = get_service_status(operation_context(client))

    assert result.completion is OperationCompletion.FAILED
    assert result.error is not None
    assert result.error.code == "DSP_STATUS_ERROR"
    assert result.error.domain is ErrorDomain.OPERATION


@pytest.mark.parametrize(
    ("summary", "action"),
    (
        (runtime_summary(reused=True, attach_performed=False), "REUSED"),
        (runtime_summary(reused=False, attach_performed=True), "LOADED_AND_ATTACHED"),
    ),
)
def test_attach_flash_service_delegates_and_reports_action(
    monkeypatch,
    summary: ServiceRuntimeSummary,
    action: str,
) -> None:
    calls: list[FlashOperationContext] = []

    def fake_ensure(ctx: FlashOperationContext) -> ServiceRuntimeSummary:
        calls.append(ctx)
        return summary

    monkeypatch.setattr(service_ops, "ensure_service_attached", fake_ensure)
    ctx = flash_context()

    result = attach_flash_service(ctx)

    assert result.ok
    assert result.summary == {"service_action": action}
    assert result.service == {
        "reused": summary.reused,
        "attach_performed": summary.attach_performed,
        "service_state": int(ServiceState.ATTACHED),
        "abi_major": 2,
        "abi_minor": 0,
        "capabilities": 0xF,
        "loaded_image_crc32": 0xAABBCCDD,
    }
    assert calls == [ctx]


def test_attach_flash_service_maps_cancellation(monkeypatch) -> None:
    cancellation = cancellation_info()
    monkeypatch.setattr(
        service_ops,
        "ensure_service_attached",
        lambda _ctx: ServiceRuntimeCancellation(cancellation),
    )

    result = attach_flash_service(flash_context())

    assert result.completion is OperationCompletion.CANCELLED
    assert result.error is None
    assert result.cancellation is cancellation
    assert result.cancellation.stage == "RAM_LOAD_END"
    assert result.cancellation.recovery_action == "RESTART_SERVICE_LOAD"
    assert result.cancellation.service_attached is False


def test_attach_flash_service_preserves_cleanup_failure_contract(monkeypatch) -> None:
    cancellation = cancellation_info()
    monkeypatch.setattr(
        service_ops,
        "ensure_service_attached",
        lambda _ctx: ServiceRuntimeCancellation(
            cancellation,
            cleanup_error=ProtocolDecodeError("cleanup failed"),
        ),
    )

    result = attach_flash_service(flash_context())

    assert result.completion is OperationCompletion.FAILED
    assert result.error is not None
    assert result.error.code == "CANCELLATION_CLEANUP_FAILED"
    assert result.cancellation is not None
    assert result.cancellation.stage == cancellation.stage
    assert result.cancellation.recovery_action == cancellation.recovery_action
    assert not result.cancellation.protocol_state_clean
    assert result.cancellation.outcome_uncertain
    assert result.cancellation.connection_recovery_required


def test_service_operations_are_public_exports() -> None:
    from bootloader_upgrade_tool.operations import attach_flash_service as exported_attach
    from bootloader_upgrade_tool.operations import get_service_status as exported_status

    assert exported_attach is attach_flash_service
    assert exported_status is get_service_status
    assert "attach_flash_service" in operations.__all__
    assert "get_service_status" in operations.__all__
