from __future__ import annotations

from threading import Event, Lock, Thread

import pytest

from bootloader_upgrade_tool.gui.connection_command_executor import (
    ConnectionCommandExecutor,
    ConnectionExecutorClosedError,
    StaleConnectionGenerationError,
)
from bootloader_upgrade_tool.gui.connection_maintenance import MaintenanceExecutionStatus
from bootloader_upgrade_tool.gui.runtime_v2_models import ConnectionGeneration


def _thread(action):
    errors = []

    def run():
        try:
            action()
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=run)
    thread.start()
    return thread, errors


def test_foreground_returns_value_and_receives_bound_session():
    session = object()
    executor = ConnectionCommandExecutor(session, ConnectionGeneration(1))

    assert executor.execute_foreground(ConnectionGeneration(1), lambda value: (value, 7)) == (
        session,
        7,
    )


def test_two_foreground_actions_never_overlap():
    executor = ConnectionCommandExecutor(object(), ConnectionGeneration(1))
    first_entered = Event()
    release_first = Event()
    state_lock = Lock()
    active = 0
    maximum = 0

    def action(block=False):
        nonlocal active, maximum
        with state_lock:
            active += 1
            maximum = max(maximum, active)
        if block:
            first_entered.set()
            assert release_first.wait(2)
        with state_lock:
            active -= 1

    first, first_errors = _thread(
        lambda: executor.execute_foreground(ConnectionGeneration(1), lambda _: action(True))
    )
    assert first_entered.wait(2)
    second, second_errors = _thread(
        lambda: executor.execute_foreground(ConnectionGeneration(1), lambda _: action())
    )
    release_first.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive() and not second.is_alive()
    assert not first_errors and not second_errors and maximum == 1


def test_maintenance_executes_when_idle_and_returns_value():
    executor = ConnectionCommandExecutor(object(), ConnectionGeneration(1))

    result = executor.try_execute_maintenance(ConnectionGeneration(1), lambda _: 42)

    assert result.status is MaintenanceExecutionStatus.EXECUTED and result.value == 42


def test_foreground_or_maintenance_activity_makes_maintenance_skip_immediately():
    executor = ConnectionCommandExecutor(object(), ConnectionGeneration(1))
    entered = Event()
    release = Event()

    def hold(_):
        entered.set()
        assert release.wait(2)

    for start in (executor.execute_foreground, executor.try_execute_maintenance):
        worker, errors = _thread(lambda: start(ConnectionGeneration(1), hold))
        assert entered.wait(2)
        called = False

        def action(_):
            nonlocal called
            called = True

        result = executor.try_execute_maintenance(ConnectionGeneration(1), action)
        assert result.status is MaintenanceExecutionStatus.SKIPPED_BUSY and not called
        release.set()
        worker.join(2)
        assert not errors
        entered.clear()
        release.clear()


def test_waiting_foreground_blocks_new_maintenance_and_runs_next():
    executor = ConnectionCommandExecutor(object(), ConnectionGeneration(1))
    maintenance_entered = Event()
    release_maintenance = Event()
    foreground_entered = Event()

    maintenance, maintenance_errors = _thread(
        lambda: executor.try_execute_maintenance(
            ConnectionGeneration(1),
            lambda _: (maintenance_entered.set(), release_maintenance.wait(2)),
        )
    )
    assert maintenance_entered.wait(2)
    foreground, foreground_errors = _thread(
        lambda: executor.execute_foreground(
            ConnectionGeneration(1), lambda _: foreground_entered.set()
        )
    )
    with executor._condition:
        assert executor._condition.wait_for(lambda: executor._foreground_waiters == 1, 2)

    result = executor.try_execute_maintenance(
        ConnectionGeneration(1), lambda _: pytest.fail("maintenance inserted ahead of foreground")
    )
    assert result.status is MaintenanceExecutionStatus.SKIPPED_BUSY
    release_maintenance.set()
    maintenance.join(2)
    foreground.join(2)

    assert foreground_entered.is_set()
    assert not maintenance_errors and not foreground_errors


def test_stale_generation_never_calls_actions_and_rejects_plain_int():
    executor = ConnectionCommandExecutor(object(), ConnectionGeneration(2))
    called = False

    def action(_):
        nonlocal called
        called = True

    with pytest.raises(StaleConnectionGenerationError):
        executor.execute_foreground(ConnectionGeneration(1), action)
    result = executor.try_execute_maintenance(ConnectionGeneration(1), action)
    assert result.status is MaintenanceExecutionStatus.STALE_GENERATION and not called
    with pytest.raises(TypeError):
        executor.execute_foreground(2, action)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        executor.try_execute_maintenance(2, action)  # type: ignore[arg-type]


def test_invalidate_is_idempotent_and_rejects_new_actions():
    executor = ConnectionCommandExecutor(object(), ConnectionGeneration(1))
    executor.invalidate()
    executor.invalidate()

    with pytest.raises(ConnectionExecutorClosedError):
        executor.execute_foreground(ConnectionGeneration(1), lambda _: None)
    result = executor.try_execute_maintenance(ConnectionGeneration(1), lambda _: None)
    assert result.status is MaintenanceExecutionStatus.EXECUTOR_CLOSED
    assert not executor.is_valid


@pytest.mark.parametrize("method", ("foreground", "maintenance"))
def test_action_exception_is_propagated_and_releases_lease(method):
    executor = ConnectionCommandExecutor(object(), ConnectionGeneration(1))
    failure = ValueError("boom")

    def fail(_):
        raise failure

    with pytest.raises(ValueError) as raised:
        if method == "foreground":
            executor.execute_foreground(ConnectionGeneration(1), fail)
        else:
            executor.try_execute_maintenance(ConnectionGeneration(1), fail)
    assert raised.value is failure
    assert executor.execute_foreground(ConnectionGeneration(1), lambda _: "released") == "released"


def test_invalidate_does_not_interrupt_started_action():
    executor = ConnectionCommandExecutor(object(), ConnectionGeneration(1))
    entered = Event()
    release = Event()
    completed = Event()
    worker, errors = _thread(
        lambda: executor.execute_foreground(
            ConnectionGeneration(1),
            lambda _: (entered.set(), release.wait(2), completed.set()),
        )
    )
    assert entered.wait(2)
    executor.invalidate()
    release.set()
    worker.join(2)

    assert completed.is_set() and not errors
