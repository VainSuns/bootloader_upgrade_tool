from __future__ import annotations

from threading import enumerate as enumerate_threads

from bootloader_upgrade_tool.gui.connection_maintenance import (
    ConnectionHealthState,
    MaintenanceExecutionResult,
    MaintenanceExecutionStatus,
    NoOpConnectionMaintenanceScheduler,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import ConnectionGeneration


def test_frozen_maintenance_types_define_the_foundation():
    result = MaintenanceExecutionResult(MaintenanceExecutionStatus.EXECUTED, "pong")

    assert result.status is MaintenanceExecutionStatus.EXECUTED
    assert result.value == "pong"
    assert ConnectionHealthState.UNKNOWN.value == "unknown"


def test_noop_scheduler_hooks_are_safe_and_create_no_threads_or_state():
    scheduler = NoOpConnectionMaintenanceScheduler()
    generation = ConnectionGeneration(1)
    before = tuple(enumerate_threads())

    assert scheduler.connection_opened(generation) is None
    assert scheduler.foreground_command_started(generation) is None
    assert scheduler.foreground_command_finished(generation) is None
    assert scheduler.protocol_activity(generation) is None
    assert scheduler.connection_closed(generation) is None

    assert tuple(enumerate_threads()) == before
    assert not vars(scheduler)
