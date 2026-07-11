from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable, Protocol

from .runtime_models import TaskExecutionResult, TaskPlan, TaskProgressUpdate

ProgressCallback = Callable[[TaskProgressUpdate], None]

class GuiTaskRequest(Protocol):
    def create_plan(self, task_id: str) -> TaskPlan: ...
class CancellationToken:
    def __init__(self): self._event = Event()
    def request_cancel(self) -> None: self._event.set()
    def is_cancel_requested(self) -> bool: return self._event.is_set()
class WorkerJob(Protocol):
    task_id: str
    def execute(self, cancellation: CancellationToken, progress: ProgressCallback) -> TaskExecutionResult: ...
class RuntimePort(Protocol):
    def connect(self, task_id, request, cancellation, progress) -> TaskExecutionResult: ...
    def disconnect(self, task_id, request, cancellation, progress) -> TaskExecutionResult: ...
    def shutdown(self, task_id, request, cancellation, progress) -> TaskExecutionResult: ...
class TaskPort(Protocol):
    def execute(self, task_id, request, cancellation, progress) -> TaskExecutionResult: ...

@dataclass(frozen=True, slots=True)
class ConnectWorkerJob:
    task_id: str; port: RuntimePort; request: object
    def execute(self, cancellation, progress): return self.port.connect(self.task_id, self.request, cancellation, progress)
@dataclass(frozen=True, slots=True)
class DisconnectWorkerJob:
    task_id: str; port: RuntimePort; request: object
    def execute(self, cancellation, progress): return self.port.disconnect(self.task_id, self.request, cancellation, progress)
@dataclass(frozen=True, slots=True)
class ShutdownWorkerJob:
    task_id: str; port: RuntimePort; request: object
    def execute(self, cancellation, progress): return self.port.shutdown(self.task_id, self.request, cancellation, progress)
@dataclass(frozen=True, slots=True)
class TaskWorkerJob:
    task_id: str; port: TaskPort; request: object
    def execute(self, cancellation, progress): return self.port.execute(self.task_id, self.request, cancellation, progress)
