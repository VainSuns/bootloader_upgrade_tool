from datetime import datetime, timezone

import pytest

from bootloader_upgrade_tool.images import ImageIdentity
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo
from bootloader_upgrade_tool.gui.runtime_v2_events import (
    ActiveTargetChanged,
    ConnectionClosed,
    ConnectionOpened,
    DiagnosticReadFailed,
    DiagnosticReadSucceeded,
    MetadataReadFailed,
    MetadataReadSucceeded,
    MetadataWriteStarted,
    OperationStarted,
    RuntimeOperationType,
    SessionChanged,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration,
    DataFreshness,
    DiagnosticGroup,
    RuntimeReadError,
    RuntimeCpuId,
    RuntimeStateStore,
)
from bootloader_upgrade_tool.gui.runtime_v2_transition import DomainEventDispatcher


ERROR = RuntimeReadError("READ_FAILED", "read failed", "READ")


def connected():
    dispatcher = DomainEventDispatcher(RuntimeStateStore())
    result = dispatcher.dispatch(
        ConnectionOpened(
            ConnectionInfo(
                "connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu1"
            )
        )
    )
    return dispatcher, result.snapshot.connection_generation


def test_metadata_policy_a_lifecycle_and_write_invalidation() -> None:
    dispatcher, generation = connected()
    assert dispatcher.dispatch(MetadataReadFailed(RuntimeCpuId.CPU1, generation, ERROR)).snapshot.metadata_state.freshness is DataFreshness.EMPTY

    fresh = dispatcher.dispatch(
        MetadataReadSucceeded(RuntimeCpuId.CPU1, generation, "metadata-1")
    ).snapshot.metadata_state
    assert (fresh.value, fresh.freshness, fresh.read_error) == (
        "metadata-1", DataFreshness.FRESH, None
    )

    stale = dispatcher.dispatch(
        MetadataReadFailed(RuntimeCpuId.CPU1, generation, ERROR)
    ).snapshot.metadata_state
    assert (stale.value, stale.freshness, stale.read_error) == (
        "metadata-1", DataFreshness.STALE, ERROR
    )

    reread = dispatcher.dispatch(
        MetadataReadSucceeded(RuntimeCpuId.CPU1, generation, "metadata-2")
    ).snapshot.metadata_state
    assert (reread.value, reread.freshness, reread.read_error) == (
        "metadata-2", DataFreshness.FRESH, None
    )

    for event in (
        OperationStarted("erase", RuntimeOperationType.ERASE, RuntimeCpuId.CPU1, generation),
        OperationStarted(
            "program",
            RuntimeOperationType.PROGRAM,
            RuntimeCpuId.CPU1,
            generation,
            ImageIdentity(0x82400, 8, 0x1234, 0x82408),
        ),
        MetadataWriteStarted("metadata", RuntimeCpuId.CPU1, generation),
    ):
        state = dispatcher.dispatch(event).snapshot.metadata_state
        assert state.value == "metadata-2" and state.freshness is DataFreshness.STALE


def test_diagnostic_groups_are_independent_under_policy_a() -> None:
    dispatcher, generation = connected()
    snapshot = dispatcher.dispatch(
        DiagnosticReadSucceeded(
            RuntimeCpuId.CPU1, generation, DiagnosticGroup.DEVICE_INFO, "device"
        )
    ).snapshot
    snapshot = dispatcher.dispatch(
        DiagnosticReadSucceeded(
            RuntimeCpuId.CPU1, generation, DiagnosticGroup.PROTOCOL_INFO, "protocol"
        )
    ).snapshot
    snapshot = dispatcher.dispatch(
        DiagnosticReadFailed(
            RuntimeCpuId.CPU1, generation, DiagnosticGroup.DEVICE_INFO, ERROR
        )
    ).snapshot
    assert snapshot.diagnostics_state.device_info.value == "device"
    assert snapshot.diagnostics_state.device_info.freshness is DataFreshness.STALE
    assert snapshot.diagnostics_state.protocol_info.value == "protocol"
    assert snapshot.diagnostics_state.protocol_info.freshness is DataFreshness.FRESH

    snapshot = dispatcher.dispatch(
        DiagnosticReadFailed(
            RuntimeCpuId.CPU1, generation, DiagnosticGroup.LAST_ERROR, ERROR
        )
    ).snapshot
    assert snapshot.diagnostics_state.last_error.value is None
    assert snapshot.diagnostics_state.last_error.freshness is DataFreshness.EMPTY
    assert snapshot.diagnostics_state.protocol_info.read_error is None


@pytest.mark.parametrize("clear_event", ["disconnect", "target", "session"])
def test_connection_target_and_session_changes_clear_target_reads(clear_event) -> None:
    dispatcher, generation = connected()
    dispatcher.dispatch(MetadataReadSucceeded(RuntimeCpuId.CPU1, generation, "metadata"))
    dispatcher.dispatch(
        DiagnosticReadSucceeded(
            RuntimeCpuId.CPU1, generation, DiagnosticGroup.DEVICE_INFO, "device"
        )
    )
    if clear_event == "target":
        snapshot = dispatcher.dispatch(ActiveTargetChanged(RuntimeCpuId.CPU2)).snapshot
    else:
        snapshot = dispatcher.dispatch(ConnectionClosed("connection", generation)).snapshot
        if clear_event == "session":
            snapshot = dispatcher.dispatch(SessionChanged()).snapshot
    assert snapshot.metadata_state.freshness is DataFreshness.EMPTY
    assert all(
        snapshot.diagnostics_state.group_state(group).freshness is DataFreshness.EMPTY
        for group in DiagnosticGroup
    )


def test_late_old_generation_results_are_ignored() -> None:
    dispatcher, generation = connected()
    dispatcher.dispatch(ConnectionClosed("connection", generation))
    current = dispatcher.dispatch(
        ConnectionOpened(
            ConnectionInfo(
                "new", "SCI", "COM4", datetime.now(timezone.utc), "cpu1"
            )
        )
    ).snapshot
    assert current.connection_generation == ConnectionGeneration(generation.value + 1)
    metadata = dispatcher.dispatch(
        MetadataReadSucceeded(RuntimeCpuId.CPU1, generation, "old")
    ).snapshot.metadata_state
    diagnostics = dispatcher.dispatch(
        DiagnosticReadSucceeded(
            RuntimeCpuId.CPU1, generation, DiagnosticGroup.DEVICE_INFO, "old"
        )
    ).snapshot.diagnostics_state
    assert metadata.freshness is DataFreshness.EMPTY
    assert diagnostics.device_info.freshness is DataFreshness.EMPTY
