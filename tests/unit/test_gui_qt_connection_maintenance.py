from __future__ import annotations

import os
from collections.abc import Callable
from threading import Event, Thread, get_ident
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.connection_maintenance import (
    MaintenanceExecutionResult,
    MaintenanceExecutionStatus,
)
from bootloader_upgrade_tool.gui.qt_connection_maintenance import (
    DEFAULT_AUTO_PING_INTERVAL_MS,
    QtConnectionMaintenanceScheduler,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration,
    ConnectionHealthState,
)


APP = QApplication.instance() or QApplication([])
G1 = ConnectionGeneration(1)
G2 = ConnectionGeneration(2)
HEALTHY = MaintenanceExecutionResult(
    MaintenanceExecutionStatus.EXECUTED, ConnectionHealthState.HEALTHY
)
UNHEALTHY = MaintenanceExecutionResult(
    MaintenanceExecutionStatus.EXECUTED, ConnectionHealthState.UNHEALTHY
)


def _pump_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        APP.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
    assert predicate()


def _open(
    callback: Callable[[ConnectionGeneration], MaintenanceExecutionResult],
    *,
    interval_ms: int = 30,
) -> QtConnectionMaintenanceScheduler:
    scheduler = QtConnectionMaintenanceScheduler(interval_ms=interval_ms)
    scheduler.bind_ping_request(callback)
    scheduler.connection_opened(G1)
    _pump_until(scheduler._timer.isActive)
    return scheduler


def _finish(scheduler: QtConnectionMaintenanceScheduler) -> None:
    _pump_until(lambda: scheduler._inflight_generation is None)
    scheduler._shutdown()


def test_constructor_and_binding_contract() -> None:
    default = QtConnectionMaintenanceScheduler()
    assert default._timer.interval() == DEFAULT_AUTO_PING_INTERVAL_MS == 2000
    assert default._timer.isSingleShot()
    assert default._execution_host.thread_pool.maxThreadCount() == 1
    assert default._execution_host.thread_pool.parent() is None
    default._shutdown()

    assert QtConnectionMaintenanceScheduler(interval_ms=7)._timer.interval() == 7
    for invalid in (0, -1, True, 1.5, "2"):
        with pytest.raises(ValueError, match="positive integer"):
            QtConnectionMaintenanceScheduler(interval_ms=invalid)  # type: ignore[arg-type]

    scheduler = QtConnectionMaintenanceScheduler()
    with pytest.raises(TypeError, match="callable"):
        scheduler.bind_ping_request(None)  # type: ignore[arg-type]
    scheduler.bind_ping_request(lambda _generation: HEALTHY)
    with pytest.raises(RuntimeError, match="already bound"):
        scheduler.bind_ping_request(lambda _generation: HEALTHY)
    with pytest.raises(TypeError, match="ConnectionGeneration"):
        scheduler.connection_opened(1)  # type: ignore[arg-type]
    scheduler._shutdown()


def test_connection_lifecycle_and_generation_isolation() -> None:
    scheduler = _open(lambda _generation: HEALTHY, interval_ms=100)
    scheduler.connection_opened(G2)
    _pump_until(lambda: scheduler._active_generation == G2)
    scheduler.connection_closed(G1)
    APP.processEvents()
    assert scheduler._active_generation == G2 and scheduler._timer.isActive()

    scheduler.connection_closed(G2)
    _pump_until(lambda: scheduler._active_generation is None)
    assert not scheduler._timer.isActive()
    scheduler._shutdown()


def test_protocol_activity_and_foreground_hooks_restart_full_interval() -> None:
    scheduler = _open(lambda _generation: HEALTHY, interval_ms=100)
    _pump_until(lambda: scheduler._timer.remainingTime() < 70)
    scheduler.protocol_activity(G1)
    _pump_until(lambda: scheduler._timer.remainingTime() > 80)

    scheduler.protocol_activity(G2)
    APP.processEvents()
    assert scheduler._active_generation == G1
    scheduler.foreground_command_started(G1)
    _pump_until(lambda: scheduler._foreground_active)
    assert not scheduler._timer.isActive()
    scheduler.foreground_command_finished(G1)
    _pump_until(scheduler._timer.isActive)
    assert scheduler._timer.remainingTime() > 80
    scheduler._shutdown()


def test_ping_runs_off_gui_thread_and_retries_after_results() -> None:
    caller_threads: list[int] = []
    calls: list[ConnectionGeneration] = []
    results = iter((HEALTHY, UNHEALTHY, HEALTHY))

    def ping(generation: ConnectionGeneration) -> MaintenanceExecutionResult:
        caller_threads.append(get_ident())
        calls.append(generation)
        return next(results)

    gui_thread = get_ident()
    scheduler = _open(ping, interval_ms=20)
    _pump_until(lambda: len(calls) >= 3)
    assert set(calls) == {G1}
    assert all(thread_id != gui_thread for thread_id in caller_threads)
    _finish(scheduler)


def test_public_hook_from_python_thread_is_queued_to_scheduler_thread() -> None:
    scheduler = _open(lambda _generation: HEALTHY, interval_ms=100)
    scheduler.foreground_command_started(G1)
    _pump_until(lambda: scheduler._foreground_active)

    worker = Thread(target=lambda: scheduler.foreground_command_finished(G1))
    worker.start()
    worker.join()
    assert scheduler._foreground_active
    _pump_until(lambda: not scheduler._foreground_active)
    assert scheduler._timer.isActive()
    scheduler._shutdown()


def test_only_one_ping_is_in_flight_and_activity_waits_for_completion() -> None:
    entered = Event()
    release = Event()
    calls = 0

    def ping(_generation: ConnectionGeneration) -> MaintenanceExecutionResult:
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(1)
        return HEALTHY

    scheduler = _open(ping, interval_ms=100)
    scheduler._timer.stop()
    scheduler._on_timeout()
    assert entered.wait(1)
    scheduler._on_timeout()
    scheduler.protocol_activity(G1)
    APP.processEvents()
    assert calls == 1 and scheduler._inflight_generation == G1
    assert not scheduler._timer.isActive()
    release.set()
    _pump_until(lambda: scheduler._inflight_generation is None)
    assert scheduler._timer.isActive()
    scheduler._shutdown()


def test_ping_completion_during_foreground_waits_for_finish() -> None:
    entered = Event()
    release = Event()

    def ping(_generation: ConnectionGeneration) -> MaintenanceExecutionResult:
        entered.set()
        release.wait(1)
        return HEALTHY

    scheduler = _open(ping, interval_ms=100)
    scheduler._timer.stop()
    scheduler._on_timeout()
    assert entered.wait(1)
    scheduler.foreground_command_started(G1)
    _pump_until(lambda: scheduler._foreground_active)
    release.set()
    _pump_until(lambda: scheduler._inflight_generation is None)
    assert not scheduler._timer.isActive()
    scheduler.foreground_command_finished(G1)
    _pump_until(scheduler._timer.isActive)
    scheduler._shutdown()


@pytest.mark.parametrize(
    "result",
    (
        HEALTHY,
        UNHEALTHY,
        MaintenanceExecutionResult(MaintenanceExecutionStatus.SKIPPED_BUSY),
    ),
)
def test_nonterminal_results_restart_single_shot_interval(result) -> None:
    calls = []
    scheduler = _open(lambda generation: calls.append(generation) or result, interval_ms=80)
    scheduler._timer.stop()
    scheduler._on_timeout()
    _pump_until(lambda: scheduler._inflight_generation is None)
    assert calls == [G1]
    assert scheduler._timer.isActive() and scheduler._timer.remainingTime() > 50
    scheduler._shutdown()


@pytest.mark.parametrize(
    "status",
    (
        MaintenanceExecutionStatus.STALE_GENERATION,
        MaintenanceExecutionStatus.EXECUTOR_CLOSED,
    ),
)
def test_terminal_current_generation_result_stops_scheduling(status) -> None:
    scheduler = _open(
        lambda _generation: MaintenanceExecutionResult(status), interval_ms=100
    )
    scheduler._timer.stop()
    scheduler._on_timeout()
    _pump_until(lambda: scheduler._inflight_generation is None)
    assert scheduler._active_generation is None
    assert not scheduler._timer.isActive()
    scheduler._shutdown()


def test_late_old_generation_result_restarts_new_generation_only() -> None:
    entered = Event()
    release = Event()

    def ping(_generation: ConnectionGeneration) -> MaintenanceExecutionResult:
        entered.set()
        release.wait(1)
        return MaintenanceExecutionResult(MaintenanceExecutionStatus.STALE_GENERATION)

    scheduler = _open(ping, interval_ms=100)
    scheduler._timer.stop()
    scheduler._on_timeout()
    assert entered.wait(1)
    scheduler.connection_opened(G2)
    _pump_until(lambda: scheduler._active_generation == G2)
    assert not scheduler._timer.isActive()
    release.set()
    _pump_until(lambda: scheduler._inflight_generation is None)
    assert scheduler._active_generation == G2 and scheduler._timer.isActive()
    scheduler._shutdown()


def test_closed_generation_late_result_and_callback_exception_are_safe() -> None:
    entered = Event()
    release = Event()

    def ping(_generation: ConnectionGeneration) -> MaintenanceExecutionResult:
        entered.set()
        release.wait(1)
        raise RuntimeError("unexpected")

    scheduler = _open(ping, interval_ms=100)
    scheduler._timer.stop()
    scheduler._on_timeout()
    assert entered.wait(1)
    scheduler.connection_closed(G1)
    _pump_until(lambda: scheduler._active_generation is None)
    release.set()
    _pump_until(lambda: scheduler._inflight_generation is None)
    assert not scheduler._timer.isActive()

    retry = _open(
        lambda _generation: (_ for _ in ()).throw(RuntimeError("unexpected")),
        interval_ms=100,
    )
    retry._timer.stop()
    retry._on_timeout()
    _pump_until(lambda: retry._inflight_generation is None)
    assert retry._active_generation == G1 and retry._timer.isActive()
    scheduler._shutdown()
    retry._shutdown()


def test_unbound_timeout_and_shutdown_submit_no_ping() -> None:
    scheduler = QtConnectionMaintenanceScheduler(interval_ms=10)
    scheduler.connection_opened(G1)
    _pump_until(lambda: scheduler._active_generation == G1)
    _pump_until(lambda: not scheduler._timer.isActive())
    assert scheduler._inflight_generation is None

    calls = []
    active = _open(lambda generation: calls.append(generation) or HEALTHY, interval_ms=20)
    active._shutdown()
    active._on_timeout()
    APP.processEvents()
    assert not calls and active._active_generation is None
    scheduler._shutdown()


def test_parent_destruction_does_not_wait_for_inflight_ping() -> None:
    parent = QObject()
    scheduler = QtConnectionMaintenanceScheduler(interval_ms=100, parent=parent)
    entered = Event()
    release = Event()
    finished = Event()
    destroyed = Event()
    calls = 0

    def ping(_generation: ConnectionGeneration) -> MaintenanceExecutionResult:
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(1)
        finished.set()
        return HEALTHY

    scheduler.bind_ping_request(ping)
    scheduler.destroyed.connect(lambda: destroyed.set())
    scheduler.connection_opened(G1)
    _pump_until(scheduler._timer.isActive)
    scheduler._timer.stop()
    scheduler._on_timeout()
    assert entered.wait(1)
    host = scheduler._execution_host
    assert len(host.active_workers) == 1

    started = monotonic()
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    APP.processEvents()
    assert destroyed.is_set()
    assert monotonic() - started < 0.2
    assert not finished.is_set()

    release.set()
    assert finished.wait(1)
    _pump_until(lambda: not host.active_workers)
    APP.processEvents()
    assert calls == 1


def test_new_scheduler_survives_destroyed_scheduler_blocked_ping() -> None:
    parent = QObject()
    first = QtConnectionMaintenanceScheduler(interval_ms=100, parent=parent)
    first_entered = Event()
    first_release = Event()
    second_entered = Event()

    def first_ping(_generation: ConnectionGeneration) -> MaintenanceExecutionResult:
        first_entered.set()
        first_release.wait(1)
        return HEALTHY

    first.bind_ping_request(first_ping)
    first.connection_opened(G1)
    _pump_until(first._timer.isActive)
    first._timer.stop()
    first._on_timeout()
    assert first_entered.wait(1)
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    APP.processEvents()

    second = _open(
        lambda _generation: second_entered.set() or HEALTHY,
        interval_ms=100,
    )
    second._timer.stop()
    started = monotonic()
    second._on_timeout()
    APP.processEvents()
    assert monotonic() - started < 0.2
    assert second._active_generation == G1
    assert not second_entered.is_set()

    first_release.set()
    assert second_entered.wait(1)
    _pump_until(lambda: second._inflight_generation is None)
    assert second._timer.isActive()
    _finish(second)
