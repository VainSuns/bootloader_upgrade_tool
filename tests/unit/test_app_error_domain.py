from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.core.client import (
    ProtocolClientError,
    ProtocolDecodeError,
    ProtocolStatusError,
)
from bootloader_upgrade_tool.gui.operation_task_adapter import operation_result_to_task_result
from bootloader_upgrade_tool.gui.runtime_models import ErrorDisposition, TaskFinalStatus
from bootloader_upgrade_tool.operations import (
    ErrorDomain,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
    classify_exception_domain,
)
from bootloader_upgrade_tool.operations.results import OperationFailure, failure_result
from bootloader_upgrade_tool.protocol.boot_protocol_client import (
    BootProtocolClient,
    ProtocolPayloadLimitError,
)
from bootloader_upgrade_tool.protocol.constants import Command, PacketType, Status
from bootloader_upgrade_tool.protocol.frame import Frame, FrameError
from bootloader_upgrade_tool.targets import UnsupportedOperationError
from bootloader_upgrade_tool.transport.base import TransportError


@pytest.mark.parametrize(
    ("exception", "domain"),
    (
        (OperationFailure("FAILED", "failed", stage="CHECK"), ErrorDomain.OPERATION),
        (UnsupportedOperationError("unsupported"), ErrorDomain.OPERATION),
        (
            ProtocolPayloadLimitError(int(Command.PING), 18, 17, 24, 17),
            ErrorDomain.OPERATION,
        ),
        (ProtocolDecodeError("bad frame"), ErrorDomain.COMMUNICATION),
        (TransportError("closed"), ErrorDomain.COMMUNICATION),
    ),
)
def test_exception_classifier_maps_known_exception_families(exception, domain) -> None:
    assert classify_exception_domain(exception) is domain


@pytest.mark.parametrize(
    "status",
    (
        Status.BAD_PAYLOAD_CRC,
        Status.UNSUPPORTED_PROTOCOL,
        Status.BAD_PACKET_TYPE,
        Status.BAD_FLAGS,
    ),
)
def test_only_wire_integrity_statuses_are_communication(status) -> None:
    assert classify_exception_domain(ProtocolStatusError(int(Command.PING), int(status))) is ErrorDomain.COMMUNICATION


@pytest.mark.parametrize(
    "status",
    (Status.BAD_PAYLOAD_LENGTH, Status.UNKNOWN_COMMAND, Status.INVALID_STATE, 0x7FFF),
)
def test_dsp_business_and_unknown_statuses_are_operation(status) -> None:
    assert classify_exception_domain(ProtocolStatusError(int(Command.PING), int(status))) is ErrorDomain.OPERATION


def test_unknown_programming_exception_is_not_converted() -> None:
    context = SimpleNamespace(target=SimpleNamespace(name="CPU1"))
    with pytest.raises(RuntimeError, match="bug"):
        failure_result(context, "operation", "STAGE", RuntimeError("bug"))


def test_payload_limit_failure_is_operation_domain_with_limit_details() -> None:
    context = SimpleNamespace(target=SimpleNamespace(name="CPU1"))
    result = failure_result(
        context,
        "operation",
        "PROGRAM_DATA",
        ProtocolPayloadLimitError(int(Command.PROGRAM_DATA), 18, 17, 24, 17),
    )

    assert result.completion is OperationCompletion.FAILED
    assert result.error is not None
    assert result.error.code == "PAYLOAD_LIMIT_EXCEEDED"
    assert result.error.domain is ErrorDomain.OPERATION
    assert result.error.details == {
        "command": int(Command.PROGRAM_DATA),
        "actual_payload_words": 18,
        "effective_max_payload_words": 17,
        "device_max_payload_words": 24,
        "protocol_max_payload_words": 17,
    }


def test_gui_summary_uses_domain_without_changing_disposition_rules() -> None:
    result = OperationResult(
        False,
        "get_device_info",
        "CPU1",
        "GET_DEVICE_INFO",
        {},
        error=OperationErrorInfo(
            "DSP_STATUS_ERROR",
            "business status",
            "GET_DEVICE_INFO",
            True,
            {},
            ErrorDomain.COMMUNICATION,
        ),
    )

    mapped = operation_result_to_task_result("task", result)

    assert mapped.status is TaskFinalStatus.FAILED
    assert mapped.summary == "Communication failed"
    assert mapped.error.domain is ErrorDomain.COMMUNICATION
    assert mapped.error.disposition is ErrorDisposition.SHOW_ONLY


class _Transport:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write_all(self, data: bytes) -> None:
        self.writes.append(data)


class _Reader:
    def __init__(self, result) -> None:
        self.result = result

    def read_frame(self, **_kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_protocol_frame_and_sequence_errors_are_decode_errors() -> None:
    transport = _Transport()
    client = BootProtocolClient(transport, _Reader(FrameError("invalid frame")))
    with pytest.raises(ProtocolDecodeError, match="invalid frame"):
        client.transact(Command.PING)

    transport = _Transport()
    client = BootProtocolClient(
        transport,
        _Reader(Frame(PacketType.RESPONSE, int(Command.PING), 2)),
    )
    with pytest.raises(ProtocolDecodeError, match="does not match"):
        client.transact(Command.PING)


def test_payload_limit_exception_has_client_error_base_not_decode_base() -> None:
    assert issubclass(ProtocolPayloadLimitError, ProtocolClientError)
    assert not issubclass(ProtocolPayloadLimitError, ProtocolDecodeError)
