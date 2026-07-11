from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal, Slot

from .runtime_models import ErrorDisposition, GuiRuntimeError, TaskExecutionResult, TaskFinalStatus, TaskProgressUpdate
from .runtime_ports import CancellationToken, WorkerJob

@dataclass(frozen=True, slots=True)
class WorkerProgressMessage:
    task_id: str; execution_generation: int; update: TaskProgressUpdate
@dataclass(frozen=True, slots=True)
class WorkerResultMessage:
    task_id: str; execution_generation: int; result: TaskExecutionResult
@dataclass(frozen=True, slots=True)
class WorkerFinishedMessage:
    task_id: str; execution_generation: int

class TaskWorker(QObject):
    progressReported = Signal(object)
    resultReady = Signal(object)
    workFinished = Signal(object)

    def __init__(self, task_id: str, execution_generation: int, job: WorkerJob, cancellation: CancellationToken, cancellable: bool = True):
        super().__init__(); self.task_id=task_id; self.generation=execution_generation; self.job=job; self.cancellation=cancellation; self.cancellable=cancellable

    def _fatal(self, exc: BaseException) -> TaskExecutionResult:
        error=GuiRuntimeError("WORKER_RUNTIME_FATAL", "Worker execution failed", "worker", ErrorDisposition.RUNTIME_FATAL, self.task_id, False, details={"exception_type": type(exc).__name__}, cause_summary=str(exc))
        return TaskExecutionResult(self.task_id, TaskFinalStatus.FAILED, "Runtime failure", str(exc), error=error)

    @Slot()
    def run(self) -> None:
        try:
            if self.cancellable and self.cancellation.is_cancel_requested():
                result=TaskExecutionResult(self.task_id, TaskFinalStatus.CANCELLED, "Cancelled", "Cancelled before start", cancel_requested=True)
            else:
                result=self.job.execute(self.cancellation, self._progress)
                if not isinstance(result, TaskExecutionResult) or result.task_id != self.task_id:
                    raise TypeError("WorkerJob returned an invalid result")
            self.resultReady.emit(WorkerResultMessage(self.task_id, self.generation, result))
        except BaseException as exc:
            self.resultReady.emit(WorkerResultMessage(self.task_id, self.generation, self._fatal(exc)))
        finally:
            self.workFinished.emit(WorkerFinishedMessage(self.task_id, self.generation))

    def _progress(self, update: TaskProgressUpdate) -> None:
        self.progressReported.emit(WorkerProgressMessage(self.task_id, self.generation, update))
