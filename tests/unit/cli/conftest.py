from __future__ import annotations

from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.operations import DiscoveredTarget, OperationContext
from bootloader_upgrade_tool.protocol.boot_protocol_client import ProtocolInfo
from bootloader_upgrade_tool.protocol.constants import CpuId, DeviceId, Feature
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import CPU1_PROFILE


def make_device_info() -> DeviceInfo:
    return DeviceInfo(
        int(DeviceId.F28377D),
        int(CpuId.CPU1),
        1,
        0,
        0,
        1,
        int(Feature.MEMORY_READ),
        256,
        8,
        2,
        2,
        0x12345678,
        0xABCDEF01,
    )


class FakeClient:
    def __init__(self) -> None:
        self.device_info = make_device_info()
        self.protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, 128, 0)
        self.calls: list[tuple[int, tuple[int, ...], int | None]] = []
        self.responses: dict[int, tuple[int, ...]] = {}

    @property
    def effective_max_payload_words(self) -> int:
        return min(self.device_info.max_payload_words, self.protocol_info.max_payload_words)

    @property
    def effective_max_data_words(self) -> int:
        return min(self.device_info.max_data_words, self.effective_max_payload_words - 5)

    @property
    def effective_max_write_data_words(self) -> int:
        value = self.effective_max_data_words
        return value - value % 8

    def transact(
        self,
        command: int,
        payload: tuple[int, ...] = (),
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, ...]:
        self.calls.append((int(command), tuple(payload), timeout_ms))
        return self.responses.get(int(command), ())


class CommandRuntime:
    def __init__(self, client: FakeClient | None = None) -> None:
        self.client = client or FakeClient()
        self.session = SimpleNamespace(client=self.client)
        self.discovered_target = DiscoveredTarget(
            self.client.device_info,
            CPU1_PROFILE,
            "cpu1",
        )
        self.contexts: list[OperationContext] = []

    def operation_context(self, progress=None) -> OperationContext:  # type: ignore[no-untyped-def]
        context = OperationContext(self.session, CPU1_PROFILE, progress, None)
        self.contexts.append(context)
        return context


@pytest.fixture
def command_runtime() -> CommandRuntime:
    return CommandRuntime()
