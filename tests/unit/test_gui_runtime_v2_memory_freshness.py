from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone

import pytest

from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo
from bootloader_upgrade_tool.gui.runtime_v2_events import (
    ActiveTargetChanged,
    ConnectionClosed,
    ConnectionOpened,
    MemoryCleared,
    MemoryReadFailed,
    MemoryReadSucceeded,
    SessionChanged,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration,
    DataFreshness,
    MemoryRuntimeState,
    RuntimeCpuId,
    RuntimeReadError,
    RuntimeStateStore,
)
from bootloader_upgrade_tool.gui.runtime_v2_transition import DomainEventDispatcher


READ_AT = datetime(2026, 7, 19, 4, 0, tzinfo=timezone.utc)
ERROR = RuntimeReadError("READ_FAILED", "read failed", "MEMORY_READ")


def _connection(cpu_id=RuntimeCpuId.CPU1, connection_id="connection"):
    return ConnectionInfo(
        connection_id, "SCI", "COM3", READ_AT, cpu_id.value
    )


def _connected(cpu_id=RuntimeCpuId.CPU1):
    dispatcher = DomainEventDispatcher(RuntimeStateStore())
    snapshot = dispatcher.dispatch(ConnectionOpened(_connection(cpu_id))).snapshot
    return dispatcher, snapshot.connection_generation


def _success(cpu_id, generation, base=0x1000, words=(1, 2), read_at=READ_AT):
    return MemoryReadSucceeded(cpu_id, generation, base, words, read_at)


def test_memory_events_are_frozen_strict_and_freeze_words() -> None:
    generation = ConnectionGeneration(1)
    source = [1, 2]
    event = _success(RuntimeCpuId.CPU1, generation, words=source)
    source.append(3)
    assert event.words == (1, 2)
    with pytest.raises(FrozenInstanceError):
        event.base_address = 0  # type: ignore[misc]
    assert [field.name for field in fields(MemoryReadSucceeded)] == [
        "cpu_id", "connection_generation", "base_address", "words", "read_at"
    ]
    for invalid in (
        lambda: _success("cpu1", generation),
        lambda: _success(RuntimeCpuId.CPU1, 1),
        lambda: _success(RuntimeCpuId.CPU1, generation, base=-1),
        lambda: _success(RuntimeCpuId.CPU1, generation, words=()),
        lambda: _success(RuntimeCpuId.CPU1, generation, words=(0x10000,)),
        lambda: _success(
            RuntimeCpuId.CPU1,
            generation,
            read_at=datetime(2026, 7, 19),
        ),
        lambda: _success(
            RuntimeCpuId.CPU1,
            generation,
            read_at=datetime(2026, 7, 19, tzinfo=timezone(timedelta(hours=1))),
        ),
        lambda: MemoryReadFailed(RuntimeCpuId.CPU1, generation, "bad"),
        lambda: MemoryCleared("cpu1"),
    ):
        with pytest.raises((TypeError, ValueError)):
            invalid()


@pytest.mark.parametrize("cpu_id", tuple(RuntimeCpuId))
def test_success_and_failure_are_per_cpu_and_current_connection_only(cpu_id) -> None:
    dispatcher, generation = _connected(cpu_id)
    other = RuntimeCpuId.CPU2 if cpu_id is RuntimeCpuId.CPU1 else RuntimeCpuId.CPU1
    before_other = dispatcher.dispatch(
        MemoryReadFailed(other, generation, ERROR)
    ).snapshot.memory_states[other]
    fresh = dispatcher.dispatch(_success(cpu_id, generation)).snapshot.memory_states
    assert fresh[cpu_id] == MemoryRuntimeState(
        cpu_id, DataFreshness.FRESH, 0x1000, (1, 2), READ_AT, generation
    )
    assert fresh[other] == before_other == MemoryRuntimeState(other)

    stale = dispatcher.dispatch(
        MemoryReadFailed(cpu_id, generation, ERROR)
    ).snapshot.memory_states[cpu_id]
    assert stale.freshness is DataFreshness.STALE
    assert (stale.base_address, stale.words, stale.read_at, stale.connection_generation) == (
        0x1000, (1, 2), READ_AT, generation
    )
    assert stale.read_error is ERROR

    reread = dispatcher.dispatch(
        _success(cpu_id, generation, 0x2000, (3,))
    ).snapshot.memory_states[cpu_id]
    assert reread.freshness is DataFreshness.FRESH
    assert (reread.base_address, reread.words, reread.read_error) == (0x2000, (3,), None)


def test_first_failure_is_empty_with_error_and_late_results_are_ignored() -> None:
    dispatcher, generation = _connected()
    failed = dispatcher.dispatch(
        MemoryReadFailed(RuntimeCpuId.CPU1, generation, ERROR)
    ).snapshot.memory_states[RuntimeCpuId.CPU1]
    assert failed == MemoryRuntimeState(RuntimeCpuId.CPU1, read_error=ERROR)

    for event in (
        _success(RuntimeCpuId.CPU2, generation),
        _success(RuntimeCpuId.CPU1, ConnectionGeneration(0)),
        MemoryReadFailed(RuntimeCpuId.CPU1, ConnectionGeneration(0), ERROR),
    ):
        state = dispatcher.dispatch(event).snapshot.memory_states[RuntimeCpuId.CPU1]
        assert state == failed


def test_disconnect_reconnect_and_target_changes_preserve_data_as_stale() -> None:
    dispatcher, generation = _connected()
    dispatcher.dispatch(_success(RuntimeCpuId.CPU1, generation))
    same = dispatcher.dispatch(
        ActiveTargetChanged(RuntimeCpuId.CPU1)
    ).snapshot.memory_states[RuntimeCpuId.CPU1]
    assert same.freshness is DataFreshness.FRESH

    stale = dispatcher.dispatch(
        ActiveTargetChanged(None)
    ).snapshot.memory_states[RuntimeCpuId.CPU1]
    assert stale.freshness is DataFreshness.STALE and stale.words == (1, 2)

    dispatcher.dispatch(_success(RuntimeCpuId.CPU1, generation, words=(3, 4)))
    closed = dispatcher.dispatch(
        ConnectionClosed("connection", generation)
    ).snapshot.memory_states[RuntimeCpuId.CPU1]
    assert closed.freshness is DataFreshness.STALE and closed.words == (3, 4)

    reopened = dispatcher.dispatch(
        ConnectionOpened(_connection(connection_id="new"))
    ).snapshot
    retained = reopened.memory_states[RuntimeCpuId.CPU1]
    assert retained.freshness is DataFreshness.STALE
    assert retained.connection_generation == generation
    assert reopened.connection_generation == generation.next()


def test_non_active_cpu_is_marked_stale_without_touching_other_runtime_domains() -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    cpu2_generation = dispatcher.dispatch(
        ConnectionOpened(_connection(RuntimeCpuId.CPU2))
    ).snapshot.connection_generation
    dispatcher.dispatch(_success(RuntimeCpuId.CPU2, cpu2_generation))
    before = store.snapshot()
    after = dispatcher.dispatch(ActiveTargetChanged(RuntimeCpuId.CPU1)).snapshot
    assert after.memory_states[RuntimeCpuId.CPU2].freshness is DataFreshness.STALE
    assert after.target_resources == before.target_resources
    assert after.metadata_state == before.metadata_state
    assert after.diagnostics_state == before.diagnostics_state
    assert after.connection == before.connection


def test_clear_is_local_disconnected_and_session_change_clears_both() -> None:
    dispatcher, generation = _connected()
    dispatcher.dispatch(_success(RuntimeCpuId.CPU1, generation))
    dispatcher.dispatch(ConnectionClosed("connection", generation))
    cleared = dispatcher.dispatch(MemoryCleared(RuntimeCpuId.CPU1)).snapshot
    assert cleared.memory_states[RuntimeCpuId.CPU1] == MemoryRuntimeState(RuntimeCpuId.CPU1)
    assert cleared.memory_states[RuntimeCpuId.CPU2] == MemoryRuntimeState(RuntimeCpuId.CPU2)

    dispatcher.dispatch(SessionChanged())
    assert dispatcher.dispatch(MemoryCleared(RuntimeCpuId.CPU2)).snapshot.memory_states == {
        cpu_id: MemoryRuntimeState(cpu_id) for cpu_id in RuntimeCpuId
    }
