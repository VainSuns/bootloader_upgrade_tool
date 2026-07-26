from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from bootloader_upgrade_tool.operations import MemoryReadRequest, OperationContext, memory_read
from bootloader_upgrade_tool.protocol.constants import Command, Feature
from bootloader_upgrade_tool.protocol.models import split_u32
from bootloader_upgrade_tool.targets import CPU1_PROFILE


class FakeClient:
    def __init__(self, *, feature=True, max_payload=8):
        info = SimpleNamespace(feature_flags=int(Feature.MEMORY_READ) if feature else 0)
        self.device_info = info
        self.effective_max_payload_words = max_payload
        self.calls = []
        self.mutate = None

    def transact(self, command, payload=(), *, timeout_ms=None):
        self.calls.append((command, tuple(payload), timeout_ms))
        address = payload[0] | payload[1] << 16
        count = payload[2]
        response = (*split_u32(address), count, *(address + i & 0xFFFF for i in range(count)))
        return self.mutate(response) if self.mutate else response


class Session:
    def __init__(self, client):
        self.client = client


def context(client, target=CPU1_PROFILE):
    return OperationContext(Session(client), target)


def test_memory_read_splits_and_joins_using_word_addresses():
    client = FakeClient(max_payload=8)
    events = []
    ctx = context(client)
    ctx.progress = events.append
    result = memory_read(ctx, MemoryReadRequest(0x12340000, 12))
    assert result.ok
    assert result.summary == {"start_address": 0x12340000, "word_count": 12, "frame_count": 3}
    assert result.details["words"] == tuple((0x12340000 + i) & 0xFFFF for i in range(12))
    assert [call[1][2] for call in client.calls] == [5, 5, 2]
    assert [call[1][0] | call[1][1] << 16 for call in client.calls] == [
        0x12340000, 0x12340005, 0x1234000A
    ]
    assert all(call[0] == int(Command.MEMORY_READ) for call in client.calls)
    assert [event.current_words for event in events] == [5, 10, 12]


def test_memory_read_checks_capability_before_transact():
    client = FakeClient(feature=False)
    result = memory_read(context(client), MemoryReadRequest(0, 1))
    assert not result.ok
    assert result.error.code == "UNSUPPORTED_OPERATION"
    assert client.calls == []


def test_memory_read_rejects_response_address_and_count_mismatch():
    client = FakeClient()
    client.mutate = lambda response: (response[0] + 1, *response[1:])
    result = memory_read(context(client), MemoryReadRequest(0x100, 1))
    assert not result.ok and result.error.code == "RESPONSE_ADDRESS_MISMATCH"

    client = FakeClient()
    client.mutate = lambda response: (response[0], response[1], response[2] + 1, *response[3:])
    result = memory_read(context(client), MemoryReadRequest(0x100, 1))
    assert not result.ok and result.error.code == "RESPONSE_WORD_COUNT_MISMATCH"


def test_memory_map_is_injected_data_not_a_send_gate():
    client = FakeClient()
    no_map_target = replace(CPU1_PROFILE, name="Synthetic CPU2 profile", cpu_id=2, memory_map=replace(CPU1_PROFILE.memory_map, flash=None, ram=None, metadata=None))
    result = memory_read(context(client, no_map_target), MemoryReadRequest(0xDEADBEEF, 1))
    assert result.ok
    assert client.calls[0][1][:2] == split_u32(0xDEADBEEF)


def test_memory_read_request_boundaries():
    client = FakeClient()
    assert not memory_read(context(client), MemoryReadRequest(0, 0)).ok
    assert memory_read(context(client), MemoryReadRequest(0xFFFFFFFF, 1)).ok
    assert not memory_read(context(client), MemoryReadRequest(0xFFFFFFFF, 2)).ok
