"""Qt scheduler for idle connection maintenance PING requests."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
    Slot,
)

from .connection_maintenance import (
    MaintenanceExecutionResult,
    MaintenanceExecutionStatus,
)
from .runtime_v2_models import ConnectionGeneration, ConnectionHealthState


DEFAULT_AUTO_PING_INTERVAL_MS = 2000


class _PingExecutionSignals(QObject):
    completed = Signal(object, object, object, object)


class _PingRunnable(QRunnable):
    def __init__(
        self,
        token: object,
        generation: ConnectionGeneration,
        request_ping: Callable[
            [ConnectionGeneration],
            MaintenanceExecutionResult[ConnectionHealthState],
        ],
        completed: Callable[
            [
                _PingRunnable,
                object,
                ConnectionGeneration,
                MaintenanceExecutionResult[ConnectionHealthState] | None,
                Exception | None,
            ],
            None,
        ],
    ) -> None:
        super().__init__()
        self._token = token
        self._generation = generation
        self._request_ping = request_ping
        self._completed = completed

    @Slot()
    def run(self) -> None:
        try:
            result = self._request_ping(self._generation)
        except Exception as exc:
            self._completed(self, self._token, self._generation, None, exc)
        else:
            self._completed(self, self._token, self._generation, result, None)


class _PingExecutionHost:
    """Own maintenance workers independently of any window lifetime."""

    def __init__(self) -> None:
        self.signals = _PingExecutionSignals()
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(1)
        self.active_workers: set[_PingRunnable] = set()

    def submit(
        self,
        token: object,
        generation: ConnectionGeneration,
        request_ping: Callable[
            [ConnectionGeneration],
            MaintenanceExecutionResult[ConnectionHealthState],
        ],
    ) -> None:
        worker = _PingRunnable(token, generation, request_ping, self._completed)
        self.active_workers.add(worker)
        self.thread_pool.start(worker)

    def _completed(
        self,
        worker: _PingRunnable,
        token: object,
        generation: ConnectionGeneration,
        result: MaintenanceExecutionResult[ConnectionHealthState] | None,
        error: Exception | None,
    ) -> None:
        self.active_workers.discard(worker)
        self.signals.completed.emit(token, generation, result, error)


_EXECUTION_HOST: _PingExecutionHost | None = None


def _execution_host() -> _PingExecutionHost:
    global _EXECUTION_HOST
    if _EXECUTION_HOST is None:
        _EXECUTION_HOST = _PingExecutionHost()
    return _EXECUTION_HOST


class QtConnectionMaintenanceScheduler(QObject):
    """Schedule one background maintenance PING after each idle interval."""

    _connection_opened = Signal(object)
    _foreground_command_started = Signal(object)
    _foreground_command_finished = Signal(object)
    _protocol_activity = Signal(object)
    _connection_closed = Signal(object)
    _auto_ping_enabled_requested = Signal(bool)

    def __init__(
        self,
        *,
        interval_ms: int = DEFAULT_AUTO_PING_INTERVAL_MS,
        parent: QObject | None = None,
    ) -> None:
        if type(interval_ms) is not int or interval_ms <= 0:
            raise ValueError("interval_ms must be a positive integer")
        super().__init__(parent)
        self._interval_ms = interval_ms
        self._active_generation: ConnectionGeneration | None = None
        self._foreground_active = False
        self._inflight_generation: ConnectionGeneration | None = None
        self._execution_token = object()
        self._execution_host = _execution_host()
        self._request_ping: Callable[
            [ConnectionGeneration],
            MaintenanceExecutionResult[ConnectionHealthState],
        ] | None = None
        self._shutting_down = False
        self._auto_ping_enabled = True

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_timeout)
        self._execution_host.signals.completed.connect(
            self._on_ping_completed, Qt.ConnectionType.QueuedConnection
        )

        queued = Qt.ConnectionType.QueuedConnection
        self._connection_opened.connect(self._on_connection_opened, queued)
        self._foreground_command_started.connect(
            self._on_foreground_command_started, queued
        )
        self._foreground_command_finished.connect(
            self._on_foreground_command_finished, queued
        )
        self._protocol_activity.connect(self._on_protocol_activity, queued)
        self._connection_closed.connect(self._on_connection_closed, queued)
        self._auto_ping_enabled_requested.connect(
            self._on_auto_ping_enabled_requested, queued
        )

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)

    def bind_ping_request(
        self,
        request_ping: Callable[
            [ConnectionGeneration],
            MaintenanceExecutionResult[ConnectionHealthState],
        ],
    ) -> None:
        if not callable(request_ping):
            raise TypeError("request_ping must be callable")
        if self._request_ping is not None:
            raise RuntimeError("PING request callback is already bound")
        self._request_ping = request_ping

    def set_auto_ping_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        self._auto_ping_enabled_requested.emit(enabled)

    def connection_opened(self, generation: ConnectionGeneration) -> None:
        self._require_generation(generation)
        self._connection_opened.emit(generation)

    def foreground_command_started(self, generation: ConnectionGeneration) -> None:
        self._require_generation(generation)
        self._foreground_command_started.emit(generation)

    def foreground_command_finished(self, generation: ConnectionGeneration) -> None:
        self._require_generation(generation)
        self._foreground_command_finished.emit(generation)

    def protocol_activity(self, generation: ConnectionGeneration) -> None:
        self._require_generation(generation)
        self._protocol_activity.emit(generation)

    def connection_closed(self, generation: ConnectionGeneration) -> None:
        self._require_generation(generation)
        self._connection_closed.emit(generation)

    @staticmethod
    def _require_generation(generation: ConnectionGeneration) -> None:
        if not isinstance(generation, ConnectionGeneration):
            raise TypeError("generation must be ConnectionGeneration")

    @Slot(object)
    def _on_connection_opened(self, generation: ConnectionGeneration) -> None:
        if self._shutting_down:
            return
        self._timer.stop()
        self._active_generation = generation
        self._foreground_active = False
        self._restart_timer_if_idle()

    @Slot(object)
    def _on_foreground_command_started(
        self, generation: ConnectionGeneration
    ) -> None:
        if generation != self._active_generation:
            return
        self._foreground_active = True
        self._timer.stop()

    @Slot(object)
    def _on_foreground_command_finished(
        self, generation: ConnectionGeneration
    ) -> None:
        if generation != self._active_generation:
            return
        self._foreground_active = False
        self._restart_timer_if_idle()

    @Slot(object)
    def _on_protocol_activity(self, generation: ConnectionGeneration) -> None:
        if generation != self._active_generation:
            return
        self._timer.stop()
        self._restart_timer_if_idle()

    @Slot(object)
    def _on_connection_closed(self, generation: ConnectionGeneration) -> None:
        if generation != self._active_generation:
            return
        self._timer.stop()
        self._active_generation = None
        self._foreground_active = False

    @Slot(bool)
    def _on_auto_ping_enabled_requested(self, enabled: bool) -> None:
        if self._shutting_down:
            self._auto_ping_enabled = False
            return
        self._auto_ping_enabled = enabled
        if not enabled:
            self._timer.stop()
            return
        self._restart_timer_if_idle()

    @Slot()
    def _on_timeout(self) -> None:
        generation = self._active_generation
        request_ping = self._request_ping
        if (
            generation is None
            or self._shutting_down
            or not self._auto_ping_enabled
            or self._foreground_active
            or self._inflight_generation is not None
            or request_ping is None
        ):
            return
        self._inflight_generation = generation
        self._execution_host.submit(self._execution_token, generation, request_ping)

    @Slot(object, object, object, object)
    def _on_ping_completed(
        self,
        token: object,
        generation: ConnectionGeneration,
        result: MaintenanceExecutionResult[ConnectionHealthState] | None,
        error: Exception | None,
    ) -> None:
        if token is not self._execution_token:
            return
        if self._inflight_generation == generation:
            self._inflight_generation = None
        if self._shutting_down or generation != self._active_generation:
            self._restart_timer_if_idle()
            return
        if error is not None:
            self._restart_timer_if_idle()
            return
        if result is not None and result.status in {
            MaintenanceExecutionStatus.STALE_GENERATION,
            MaintenanceExecutionStatus.EXECUTOR_CLOSED,
        }:
            self._timer.stop()
            self._active_generation = None
            self._foreground_active = False
            return
        self._restart_timer_if_idle()

    def _restart_timer_if_idle(self) -> None:
        if (
            not self._shutting_down
            and self._auto_ping_enabled
            and self._active_generation is not None
            and not self._foreground_active
            and self._inflight_generation is None
        ):
            self._timer.start(self._interval_ms)

    @Slot()
    def _shutdown(self) -> None:
        self._shutting_down = True
        self._auto_ping_enabled = False
        self._timer.stop()
        self._active_generation = None
        self._foreground_active = False


__all__ = [
    "DEFAULT_AUTO_PING_INTERVAL_MS",
    "QtConnectionMaintenanceScheduler",
]
