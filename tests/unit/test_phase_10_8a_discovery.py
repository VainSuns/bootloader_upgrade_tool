from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.operations import discover_connected_target
from bootloader_upgrade_tool.operations.results import OperationErrorInfo, OperationResult
from bootloader_upgrade_tool.protocol.boot_protocol_client import ProtocolInfo
from bootloader_upgrade_tool.protocol.constants import Command, CpuId, DeviceId
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import (
    CPU1_PROFILE,
    CPU2_PROFILE,
    DISCOVERY_PROFILE,
)
from bootloader_upgrade_tool.transport.base import TransportError


def _info(device_id=DeviceId.F28377D, cpu_id=CpuId.CPU1):
    return DeviceInfo(int(device_id), int(cpu_id), 1, 0, 0, 1, 0, 256, 8, 2, 2)


class _Client:
    def __init__(self, info=None, error=None, protocol_words=(1, 1, 1, 10, 1, 1, 64, 0)):
        self.device_info = None
        self.protocol_info = None
        self.info = info
        self.error = error
        self.protocol_words = protocol_words
        self.commands = []

    @property
    def effective_max_payload_words(self):
        return min(self.device_info.max_payload_words, self.protocol_info.max_payload_words)

    @property
    def effective_max_data_words(self):
        return min(self.device_info.max_data_words, self.effective_max_payload_words - 5)

    @property
    def effective_max_write_data_words(self):
        value = self.effective_max_data_words
        return value - value % 8

    def transact(self, command, payload=(), *, timeout_ms=None):
        self.commands.append(command)
        if self.error:
            raise self.error
        if command == int(Command.GET_DEVICE_INFO):
            words = self.info.to_words() if hasattr(self.info, "to_words") else self.info
            if hasattr(self.info, "to_words"):
                self.device_info = self.info
            return words
        self.protocol_info = ProtocolInfo.from_words(self.protocol_words)
        return self.protocol_words


@pytest.mark.parametrize(
    ("info", "target", "key"),
    [(_info(cpu_id=CpuId.CPU1), CPU1_PROFILE, "cpu1"), (_info(cpu_id=CpuId.CPU2), CPU2_PROFILE, "cpu2")],
)
def test_discovery_resolves_supported_targets(info, target, key):
    client = _Client(info)
    session = SimpleNamespace(client=client)
    outcome = discover_connected_target(session)
    assert outcome.result.ok
    assert outcome.discovered_target is not None
    assert outcome.discovered_target.target_profile is target
    assert outcome.discovered_target.target_key == key
    assert client.commands == [int(Command.GET_DEVICE_INFO), int(Command.GET_PROTOCOL_INFO)]
    assert outcome.result.summary["device_max_payload_words"] == 256
    assert outcome.result.summary["protocol_max_payload_words"] == 64
    assert outcome.result.summary["effective_max_payload_words"] == 64
    assert outcome.result.summary["effective_max_data_words"] == 8
    assert outcome.result.summary["effective_max_write_data_words"] == 8


@pytest.mark.parametrize(
    ("info", "code"),
    [(_info(device_id=0x1234), "UNSUPPORTED_DEVICE"), (_info(cpu_id=0x99), "UNKNOWN_CPU_ID")],
)
def test_discovery_rejects_unsupported_identity(info, code):
    client = _Client(info)
    outcome = discover_connected_target(SimpleNamespace(client=client))
    assert not outcome.result.ok and outcome.result.error.code == code
    assert outcome.result.error.recoverable
    assert outcome.discovered_target is None
    if code == "UNKNOWN_CPU_ID":
        assert outcome.result.error.details["device_id"] == int(DeviceId.F28377D)
    assert client.commands == [int(Command.GET_DEVICE_INFO)]


def test_discovery_reports_malformed_device_info_as_protocol_error():
    outcome = discover_connected_target(SimpleNamespace(client=_Client((1, 2))))
    assert not outcome.result.ok
    assert outcome.result.error.code == "PROTOCOL_ERROR"
    assert outcome.result.error.stage == "GET_DEVICE_INFO"
    assert outcome.result.error.recoverable


def test_discovery_preserves_device_info_failure():
    client = _Client(error=TransportError("no response"))
    original = discover_connected_target(SimpleNamespace(client=client))
    assert not original.result.ok
    assert original.result.error.code == "PROTOCOL_ERROR"


def test_discovery_profile_supports_exactly_capability_commands():
    command_set = DISCOVERY_PROFILE.command_set
    assert command_set.get_device_info is not None
    assert command_set.get_protocol_info is not None
    assert sum(value is not None for value in command_set.__dict__.values()) == 2
    assert DISCOVERY_PROFILE.memory_map.flash is None


def test_discovery_protocol_failure_returns_no_target():
    client = _Client(_info(), protocol_words=(1, 1))
    outcome = discover_connected_target(SimpleNamespace(client=client))
    assert not outcome.result.ok
    assert outcome.discovered_target is None
    assert client.commands == [int(Command.GET_DEVICE_INFO), int(Command.GET_PROTOCOL_INFO)]
