from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.gui.advanced_flash_operation_models import (
    ProgramAdvancedFlashRequest,
)
from bootloader_upgrade_tool.gui.advanced_metadata_models import (
    WriteAdvancedBootAttemptRequest,
)
from bootloader_upgrade_tool.gui.advanced_ram_models import (
    LoadAdvancedRamImageRequest,
    RunAdvancedRamImageRequest,
)
from bootloader_upgrade_tool.gui.connection_maintenance import (
    ConnectionHealthState,
    MaintenanceExecutionStatus,
)
from bootloader_upgrade_tool.gui.connection_models import SerialDisconnectRequest
from bootloader_upgrade_tool.gui.runtime_models import TaskFinalStatus
from bootloader_upgrade_tool.gui.runtime_v2_events import (
    ConnectionHealthChanged,
    ProtocolActivityRecorded,
)
from bootloader_upgrade_tool.gui.status_models import DeviceInfoRequest
from bootloader_upgrade_tool.operations import OperationResult
from tests.unit import test_gui_batch14_status as status_support
from tests.unit import test_gui_runtime_backend as backend_support
from tests.unit import test_gui_runtime_backend_flash_operations as flash_support
from tests.unit import test_gui_runtime_backend_metadata_operations as metadata_support
from tests.unit import test_gui_runtime_backend_ram as ram_support


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class FakeScheduler:
    def __init__(self, fail_on=()):
        self.events = []
        self.fail_on = set(fail_on)
        self.request_ping = None

    def _record(self, hook, generation):
        self.events.append((hook, generation))
        if hook in self.fail_on:
            raise RuntimeError(f"{hook} failed")

    def connection_opened(self, generation):
        self._record("opened", generation)

    def foreground_command_started(self, generation):
        self._record("started", generation)

    def protocol_activity(self, generation):
        self._record("activity", generation)

    def foreground_command_finished(self, generation):
        self._record("finished", generation)

    def connection_closed(self, generation):
        self._record("closed", generation)


def _assert_foreground(events, generation):
    assert events == [
        ("started", generation),
        ("activity", generation),
        ("finished", generation),
    ]


def test_status_ram_flash_and_metadata_each_emit_one_foreground_hook_group(tmp_path):
    scheduler = FakeScheduler()
    common = {"maintenance_scheduler": scheduler, "maintenance_clock": lambda: NOW}

    status_backend = status_support._backend(
        **common,
        device_info_operation=lambda _ctx: status_support._ok(
            "get_device_info", status_support._device_info()
        ),
    )
    result = status_backend.execute(
        "status", DeviceInfoRequest("connection"), None, None
    )
    assert result.status is TaskFinalStatus.SUCCEEDED
    _assert_foreground(scheduler.events, status_backend.connection_generation)

    scheduler.events.clear()
    ram_backend, path, _ = ram_support.connected_backend(
        tmp_path,
        **common,
        load_ram_operation=lambda ctx, _request: OperationResult(
            True, "load_ram", ctx.target.name, "RAM_LOAD", {}
        ),
    )
    result = ram_backend.execute(
        "ram",
        ram_support.ram_request(ram_backend, path, LoadAdvancedRamImageRequest),
        None,
        None,
    )
    assert result.status is TaskFinalStatus.SUCCEEDED
    _assert_foreground(scheduler.events, ram_backend.connection_generation)

    scheduler.events.clear()
    flash_backend, *_ = flash_support.populated_backend(
        tmp_path,
        [],
        **common,
        program_flash_operation=lambda ctx, _request: OperationResult(
            True, "program", ctx.target.name, "PROGRAM", {}
        ),
    )
    result = flash_backend.execute(
        "flash",
        flash_support.flash_request(flash_backend, ProgramAdvancedFlashRequest),
        None,
        None,
    )
    assert result.status is TaskFinalStatus.SUCCEEDED
    _assert_foreground(scheduler.events, flash_backend.connection_generation)

    scheduler.events.clear()
    metadata_backend, *_ = metadata_support._backend(tmp_path, [], **common)
    result = metadata_backend.execute(
        "metadata",
        metadata_support.metadata_request(
            metadata_backend, WriteAdvancedBootAttemptRequest
        ),
        None,
        None,
    )
    assert result.status is TaskFinalStatus.SUCCEEDED
    _assert_foreground(scheduler.events, metadata_backend.connection_generation)


def test_typed_foreground_failure_is_activity_but_exception_is_not():
    scheduler = FakeScheduler()
    backend = status_support._backend(
        maintenance_scheduler=scheduler,
        maintenance_clock=lambda: NOW,
        device_info_operation=lambda _ctx: status_support._failed(
            "get_device_info", "READ_FAILED"
        ),
    )
    result = backend.execute("status", DeviceInfoRequest("connection"), None, None)
    assert result.status is TaskFinalStatus.FAILED
    _assert_foreground(scheduler.events, backend.connection_generation)

    scheduler.events.clear()
    backend._device_info_operation = lambda _ctx: (_ for _ in ()).throw(ValueError("boom"))
    with pytest.raises(ValueError, match="boom"):
        backend.execute("status", DeviceInfoRequest("connection"), None, None)
    assert scheduler.events == [
        ("started", backend.connection_generation),
        ("finished", backend.connection_generation),
    ]


@pytest.mark.parametrize("hook", ("started", "activity", "finished"))
def test_foreground_scheduler_hook_failures_do_not_change_result(hook):
    scheduler = FakeScheduler({hook})
    backend = status_support._backend(
        maintenance_scheduler=scheduler,
        maintenance_clock=lambda: NOW,
        device_info_operation=lambda _ctx: status_support._ok(
            "get_device_info", status_support._device_info()
        ),
    )
    result = backend.execute("status", DeviceInfoRequest("connection"), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    _assert_foreground(scheduler.events, backend.connection_generation)


def test_connection_scheduler_hook_failures_do_not_break_connect_or_cleanup():
    opened = FakeScheduler({"opened"})
    backend, _, _ = backend_support._backend(maintenance_scheduler=opened)
    result, _ = backend_support._connect(backend)
    assert result.status is TaskFinalStatus.SUCCEEDED

    closed = FakeScheduler({"closed"})
    backend, _, _ = backend_support._backend(maintenance_scheduler=closed)
    backend_support._connect(backend)
    executor = backend.connection_command_executor
    result = backend.disconnect("disconnect", SerialDisconnectRequest(), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert backend.connection_command_executor is None and not executor.is_valid

    backend, _, _ = backend_support._backend(maintenance_scheduler=closed)
    backend_support._connect(backend)
    executor = backend.connection_command_executor
    result = backend.shutdown("shutdown", type("Request", (), {"step_id": "shutdown"})(), None, None)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert backend.connection_command_executor is None and not executor.is_valid


def _connected_ping_backend(scheduler, ping, **kwargs):
    backend, _, sessions = backend_support._backend(
        maintenance_scheduler=scheduler,
        maintenance_clock=lambda: NOW,
        **kwargs,
    )
    backend_support._connect(backend)
    sessions[0].client.ping = ping
    sessions[0].dirty = False
    scheduler.events.clear()
    scheduler.request_ping = backend.try_execute_maintenance_ping
    return backend, sessions[0]


def test_maintenance_ping_success_updates_activity_and_health_without_task_path(monkeypatch):
    scheduler = FakeScheduler()
    calls = []
    backend, session = _connected_ping_backend(scheduler, lambda: (1, 2))
    executor = backend.connection_command_executor
    session.client.ping = lambda: calls.append(executor._active) or (1, 2)
    transitions = []
    backend.subscribe_runtime_v2(transitions.append)
    monkeypatch.setattr(
        backend, "_publish", lambda *_args, **_kwargs: pytest.fail("Ping published progress")
    )

    result = scheduler.request_ping(backend.connection_generation)

    assert result.status is MaintenanceExecutionStatus.EXECUTED
    assert result.value is ConnectionHealthState.HEALTHY
    assert calls == [True]
    connection = backend.runtime_v2_snapshot.connection
    assert connection.last_protocol_activity == NOW
    assert connection.health_state is ConnectionHealthState.HEALTHY
    assert connection.health_checked_at == NOW and connection.health_error is None
    assert scheduler.events == [("activity", backend.connection_generation)]
    assert [type(item.source_event) for item in transitions] == [
        ProtocolActivityRecorded,
        ConnectionHealthChanged,
    ]
    assert session.dirty is False


def test_maintenance_ping_failure_only_records_unhealthy(monkeypatch):
    scheduler = FakeScheduler()

    def fail():
        raise TimeoutError()

    backend, session = _connected_ping_backend(scheduler, fail)
    before = backend.runtime_v2_snapshot.connection.last_protocol_activity
    monkeypatch.setattr(
        backend, "_publish", lambda *_args, **_kwargs: pytest.fail("Ping published progress")
    )

    result = scheduler.request_ping(backend.connection_generation)

    assert result.status is MaintenanceExecutionStatus.EXECUTED
    assert result.value is ConnectionHealthState.UNHEALTHY
    connection = backend.runtime_v2_snapshot.connection
    assert connection.last_protocol_activity == before
    assert connection.health_state is ConnectionHealthState.UNHEALTHY
    assert connection.health_checked_at == NOW
    assert connection.health_error.stage == "PING"
    assert connection.health_error.code == "TimeoutError"
    assert connection.health_error.message == "TimeoutError"
    assert scheduler.events == [] and session.dirty is False


def test_maintenance_ping_skips_deterministically_while_foreground_is_busy():
    scheduler = FakeScheduler()
    pings = []
    backend, _ = _connected_ping_backend(scheduler, lambda: pings.append(True))
    generation = backend.connection_generation
    captured = backend._status_connection(backend.connection_info.connection_id)
    entered = Event()
    release = Event()

    def foreground(_session):
        entered.set()
        assert release.wait(2)

    worker = Thread(
        target=backend._execute_connected_foreground,
        args=(captured, foreground),
    )
    worker.start()
    assert entered.wait(2)
    before = backend.runtime_v2_snapshot.connection

    result = scheduler.request_ping(generation)

    assert result.status is MaintenanceExecutionStatus.SKIPPED_BUSY
    assert not pings
    assert backend.runtime_v2_snapshot.connection == before
    release.set()
    worker.join(2)
    assert not worker.is_alive()


def test_maintenance_ping_rejects_closed_and_old_generations_without_new_session_ping():
    scheduler = FakeScheduler()
    old_pings = []
    backend, _ = _connected_ping_backend(scheduler, lambda: old_pings.append(True))
    old_generation = backend.connection_generation
    backend.disconnect("disconnect", SerialDisconnectRequest(), None, None)
    assert scheduler.request_ping(old_generation).status is MaintenanceExecutionStatus.EXECUTOR_CLOSED

    backend_support._connect(backend, "reconnect")
    new_pings = []
    backend.active_session.client.ping = lambda: new_pings.append(True)
    assert scheduler.request_ping(old_generation).status is MaintenanceExecutionStatus.STALE_GENERATION
    assert not old_pings and not new_pings


def test_ram_release_connection_cleanup_invalidates_old_maintenance_callback(tmp_path):
    scheduler = FakeScheduler()
    backend, path, _ = ram_support.connected_backend(
        tmp_path,
        maintenance_scheduler=scheduler,
        maintenance_clock=lambda: NOW,
        run_ram_operation=lambda ctx, _request: OperationResult(
            True, "run_ram", ctx.target.name, "RUN_RAM", {}
        ),
    )
    generation = backend.connection_generation
    scheduler.request_ping = backend.try_execute_maintenance_ping

    result = backend.execute(
        "run",
        ram_support.ram_request(backend, path, RunAdvancedRamImageRequest),
        None,
        None,
    )
    assert result.completion_action.name == "RELEASE_CONNECTION"

    backend._session = SimpleNamespace(disconnect=lambda: None)
    cleanup = backend.disconnect("disconnect", SerialDisconnectRequest(), None, None)
    assert cleanup.status is TaskFinalStatus.SUCCEEDED
    assert scheduler.request_ping(generation).status is MaintenanceExecutionStatus.EXECUTOR_CLOSED


def test_cleanup_failure_keeps_original_maintenance_executor_until_retry():
    scheduler = FakeScheduler()
    pings = []
    backend, session = _connected_ping_backend(
        scheduler,
        lambda: pings.append(True),
        session_close_error=OSError("session busy"),
        transport_close_error=OSError("port busy"),
    )
    generation = backend.connection_generation

    failed = backend.disconnect("disconnect", SerialDisconnectRequest(), None, None)
    assert failed.status is TaskFinalStatus.FAILED
    assert scheduler.request_ping(generation).value is ConnectionHealthState.HEALTHY
    assert pings == [True]

    session.close_error = None
    session.config.transport.close_error = None
    retried = backend.shutdown(
        "shutdown", type("Request", (), {"step_id": "shutdown"})(), None, None
    )
    assert retried.status is TaskFinalStatus.SUCCEEDED
    assert scheduler.request_ping(generation).status is MaintenanceExecutionStatus.EXECUTOR_CLOSED
