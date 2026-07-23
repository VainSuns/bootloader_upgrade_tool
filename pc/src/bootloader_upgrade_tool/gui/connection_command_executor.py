"""Operation-level serialization for one connected UpgradeSession."""

from __future__ import annotations

from collections.abc import Callable
from threading import Condition
from typing import TypeVar

from ..session import UpgradeSession
from .connection_maintenance import MaintenanceExecutionResult, MaintenanceExecutionStatus
from .runtime_v2_models import ConnectionGeneration


T = TypeVar("T")


class StaleConnectionGenerationError(RuntimeError):
    pass


class ConnectionExecutorClosedError(RuntimeError):
    pass


class ConnectionCommandExecutor:
    """Owns the foreground-priority command lease for one connection generation."""

    def __init__(self, session: UpgradeSession, generation: ConnectionGeneration) -> None:
        if type(generation) is not ConnectionGeneration:
            raise TypeError("generation must be ConnectionGeneration")
        self._session = session
        self._generation = generation
        self._condition = Condition()
        self._active = False
        self._foreground_waiters = 0
        self._valid = True

    @property
    def generation(self) -> ConnectionGeneration:
        return self._generation

    @property
    def is_valid(self) -> bool:
        with self._condition:
            return self._valid

    def execute_foreground(
        self,
        generation: ConnectionGeneration,
        action: Callable[[UpgradeSession], T],
    ) -> T:
        self._require_generation(generation)
        with self._condition:
            self._raise_if_unavailable(generation)
            self._foreground_waiters += 1
            self._condition.notify_all()
            try:
                while self._active:
                    self._condition.wait()
                    self._raise_if_unavailable(generation)
                self._active = True
            finally:
                self._foreground_waiters -= 1
        try:
            return action(self._session)
        finally:
            with self._condition:
                self._active = False
                self._condition.notify_all()

    def try_execute_maintenance(
        self,
        generation: ConnectionGeneration,
        action: Callable[[UpgradeSession], T],
    ) -> MaintenanceExecutionResult[T]:
        self._require_generation(generation)
        with self._condition:
            if not self._valid:
                return MaintenanceExecutionResult(MaintenanceExecutionStatus.EXECUTOR_CLOSED)
            if generation != self._generation:
                return MaintenanceExecutionResult(MaintenanceExecutionStatus.STALE_GENERATION)
            if self._active or self._foreground_waiters:
                return MaintenanceExecutionResult(MaintenanceExecutionStatus.SKIPPED_BUSY)
            self._active = True
        try:
            return MaintenanceExecutionResult(
                MaintenanceExecutionStatus.EXECUTED,
                action(self._session),
            )
        finally:
            with self._condition:
                self._active = False
                self._condition.notify_all()

    def invalidate(self) -> None:
        with self._condition:
            self._valid = False
            self._condition.notify_all()

    @staticmethod
    def _require_generation(generation: ConnectionGeneration) -> None:
        if type(generation) is not ConnectionGeneration:
            raise TypeError("generation must be ConnectionGeneration")

    def _raise_if_unavailable(self, generation: ConnectionGeneration) -> None:
        if not self._valid:
            raise ConnectionExecutorClosedError("connection command executor is closed")
        if generation != self._generation:
            raise StaleConnectionGenerationError("connection generation is stale")


__all__ = [
    "ConnectionCommandExecutor",
    "ConnectionExecutorClosedError",
    "StaleConnectionGenerationError",
]
