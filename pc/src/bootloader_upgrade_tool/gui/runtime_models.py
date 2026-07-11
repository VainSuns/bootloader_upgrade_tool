from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum, auto
from types import MappingProxyType
from typing import Any
from collections.abc import Mapping


class _Names(Enum):
    def __str__(self) -> str:
        return self.name


class RuntimeState(_Names): DISCONNECTED=auto(); CONNECTING=auto(); CONNECTED=auto(); BUSY=auto(); DISCONNECTING=auto(); ERROR=auto()
class TaskPhase(_Names): PENDING=auto(); RUNNING=auto(); CANCELLING=auto(); FINISHED=auto()
class TaskDispositionState(_Names): NONE=auto(); AWAITING_DISCONNECT_DECISION=auto(); DISCONNECTING=auto(); COMPLETE=auto()
class TaskFinalStatus(_Names): SUCCEEDED=auto(); FAILED=auto(); CANCELLED=auto(); COMPLETED_AFTER_CANCEL_REQUEST=auto()
class TaskStepState(_Names): STARTED=auto(); PROGRESS=auto(); COMPLETED=auto()
class ProgressMode(_Names): INDETERMINATE=auto(); DETERMINATE=auto()
class CompletionPolicy(_Names): AUTO_CLOSE_ON_CLEAN_SUCCESS=auto(); REQUIRE_ACKNOWLEDGEMENT=auto()
class TaskConnectionRequirement(_Names): NONE=auto(); CONNECTED=auto()
class TaskCompletionAction(_Names): NONE=auto(); RELEASE_CONNECTION=auto()
class TaskDialogAction(_Names): DISCONNECT=auto(); KEEP_CONNECTION=auto(); RETRY_CLEANUP=auto(); FORCE_EXIT=auto()
class ErrorDisposition(_Names): SHOW_ONLY=auto(); ASK_DISCONNECT=auto(); FORCE_DISCONNECTED=auto(); RUNTIME_FATAL=auto()
class RequestRejectionCode(_Names): INVALID_RUNTIME_STATE=auto(); TASK_ALREADY_ACTIVE=auto(); DECISION_PENDING=auto(); SHUTDOWN_IN_PROGRESS=auto(); UNKNOWN_TASK=auto(); TASK_NOT_CANCELLABLE=auto(); ACTION_NOT_AVAILABLE=auto(); ACTION_ALREADY_APPLIED=auto(); CLOSE_NOT_ALLOWED=auto()
class ApplicationCloseDecision(_Names): ALLOW_IMMEDIATE=auto(); SHUTDOWN_STARTED=auto(); REJECTED=auto(); ERROR=auto()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value): raise TypeError("details keys must be strings")
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("runtime resources are not immutable GUI data")

def _enum(value: object, expected: type[Enum], name: str) -> None:
    if not isinstance(value, expected): raise TypeError(f"{name} must be {expected.__name__}")

def _normalize_typed(value: Any) -> Any:
    if value is None or isinstance(value,(str,int,float,bool,datetime,Enum)):return value
    if isinstance(value,Mapping):
        if any(not isinstance(key,str) for key in value):raise TypeError("mapping keys must be strings")
        return MappingProxyType({key:_normalize_typed(item) for key,item in value.items()})
    if isinstance(value,(list,tuple)):return tuple(_normalize_typed(item) for item in value)
    if is_dataclass(value) and getattr(type(value),"__dataclass_params__").frozen:
        return replace(value,**{item.name:_normalize_typed(getattr(value,item.name)) for item in fields(value) if item.init})
    raise TypeError("unsupported mutable runtime payload")


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    connection_id: str
    transport_label: str
    endpoint_label: str
    connected_at: datetime
    details: Mapping[str, object] = field(default_factory=dict)
    def __post_init__(self):
        if self.connected_at.tzinfo is None or self.connected_at.utcoffset().total_seconds() != 0: raise ValueError("connected_at must be UTC")
        object.__setattr__(self, "details", _freeze(self.details))


@dataclass(frozen=True, slots=True)
class GuiRuntimeError:
    code: str
    message: str
    stage: str
    disposition: ErrorDisposition
    task_id: str | None = None
    recoverable: bool = True
    outcome_uncertain: bool = False
    details: Mapping[str, object] = field(default_factory=dict)
    cause_summary: str | None = None
    def __post_init__(self):
        _enum(self.disposition,ErrorDisposition,"disposition")
        if self.disposition is ErrorDisposition.ASK_DISCONNECT and not self.outcome_uncertain: raise ValueError("ASK_DISCONNECT requires uncertain outcome")
        if self.disposition is ErrorDisposition.RUNTIME_FATAL and self.recoverable: raise ValueError("RUNTIME_FATAL is not recoverable")
        object.__setattr__(self, "details", _freeze(self.details))


@dataclass(frozen=True, slots=True)
class GuiTaskWarning:
    code: str; message: str; stage: str
    details: Mapping[str, object] = field(default_factory=dict)
    def __post_init__(self): object.__setattr__(self, "details", _freeze(self.details))


@dataclass(frozen=True, slots=True)
class TaskStepPlan:
    step_id: str; title: str; initial_progress_mode: ProgressMode; weight: int = 1
    def __post_init__(self):
        _enum(self.initial_progress_mode,ProgressMode,"initial_progress_mode")
        if not self.step_id or not self.title or self.weight <= 0: raise ValueError("invalid task step")


@dataclass(frozen=True, slots=True)
class TaskPlan:
    task_id: str; title: str; steps: tuple[TaskStepPlan, ...]
    connection_requirement: TaskConnectionRequirement
    cancellable: bool
    completion_policy: CompletionPolicy
    def __post_init__(self):
        object.__setattr__(self,"steps",tuple(self.steps))
        _enum(self.connection_requirement,TaskConnectionRequirement,"connection_requirement"); _enum(self.completion_policy,CompletionPolicy,"completion_policy")
        if not isinstance(self.cancellable,bool): raise TypeError("cancellable must be bool")
        if not self.task_id or not self.title or not self.steps: raise ValueError("invalid task plan")
        ids=[s.step_id for s in self.steps]
        if len(ids) != len(set(ids)): raise ValueError("step ids must be unique")


@dataclass(frozen=True, slots=True)
class TaskProgressUpdate:
    task_id: str; step_id: str; step_state: TaskStepState; stage: str; message: str
    current: int | None = None; total: int | None = None
    progress_mode: ProgressMode = ProgressMode.INDETERMINATE
    raw_event: object | None = None
    details: Mapping[str, object] = field(default_factory=dict)
    def __post_init__(self):
        _enum(self.step_state,TaskStepState,"step_state"); _enum(self.progress_mode,ProgressMode,"progress_mode")
        object.__setattr__(self, "details", _freeze(self.details))


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    task_id: str; status: TaskFinalStatus; summary: str; message: str
    step_results: tuple[object, ...] = (); payload: object | None = None
    warning: GuiTaskWarning | None = None; error: GuiRuntimeError | None = None
    completion_action: TaskCompletionAction = TaskCompletionAction.NONE
    cancel_requested: bool = False; started_at: datetime | None = None
    finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    def __post_init__(self):
        object.__setattr__(self,"step_results",tuple(_normalize_typed(item) for item in self.step_results))
        object.__setattr__(self,"payload",_normalize_typed(self.payload))
        _enum(self.status,TaskFinalStatus,"status"); _enum(self.completion_action,TaskCompletionAction,"completion_action")
        if self.status is TaskFinalStatus.FAILED and self.error is None: raise ValueError("FAILED requires error")
        if self.status is not TaskFinalStatus.FAILED and self.error is not None: raise ValueError("only FAILED carries error")
        if self.status in (TaskFinalStatus.CANCELLED, TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST) and not self.cancel_requested: raise ValueError("cancel status requires request")
        if self.error and self.error.task_id not in (None, self.task_id): raise ValueError("task id mismatch")
        if self.status is TaskFinalStatus.FAILED and self.warning: raise ValueError("failure cannot carry warning")
        if self.status is TaskFinalStatus.FAILED and self.completion_action is TaskCompletionAction.RELEASE_CONNECTION: raise ValueError("failed result cannot release connection")
        if self.finished_at.tzinfo is None or self.finished_at.utcoffset().total_seconds()!=0: raise ValueError("finished_at must be UTC")
        if self.started_at and (self.started_at.tzinfo is None or self.started_at.utcoffset().total_seconds()!=0): raise ValueError("started_at must be UTC")
        if self.started_at and self.finished_at < self.started_at: raise ValueError("invalid timestamps")


@dataclass(frozen=True, slots=True)
class TaskState:
    task_id: str; plan: TaskPlan; phase: TaskPhase; disposition_state: TaskDispositionState = TaskDispositionState.NONE
    current_step_index: int | None = None; current_step_id: str | None = None; current_step_title: str = ""; message: str = ""
    overall_current: int = 0; overall_total: int = 1000; step_current: int = 0; step_total: int = 0
    step_progress_mode: ProgressMode = ProgressMode.INDETERMINATE; cancel_requested: bool = False
    available_actions: tuple[TaskDialogAction, ...] = (); close_allowed: bool = False; auto_close_delay_ms: int | None = None
    started_at: datetime | None = None; finished_at: datetime | None = None
    result: TaskExecutionResult | None = None; error: GuiRuntimeError | None = None
    def __post_init__(self):
        _enum(self.phase,TaskPhase,"phase"); _enum(self.disposition_state,TaskDispositionState,"disposition_state"); _enum(self.step_progress_mode,ProgressMode,"step_progress_mode")
        if any(not isinstance(a,TaskDialogAction) for a in self.available_actions): raise TypeError("invalid dialog action")
        if self.plan.task_id != self.task_id: raise ValueError("task id mismatch")
        if self.result and self.result.task_id != self.task_id: raise ValueError("task id mismatch")
        if self.error and self.error.task_id not in (None, self.task_id): raise ValueError("task id mismatch")


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    state: RuntimeState = RuntimeState.DISCONNECTED; active_task_id: str | None = None
    connection_info: ConnectionInfo | None = None; active_target_key: str = "cpu1"
    connection_suspect: bool = False; disconnect_decision_pending: bool = False
    shutdown_requested: bool = False; last_error: GuiRuntimeError | None = None
    def __post_init__(self):
        _enum(self.state,RuntimeState,"state")
        if self.state is RuntimeState.DISCONNECTED and (self.connection_info or self.connection_suspect or self.disconnect_decision_pending): raise ValueError("invalid disconnected snapshot")
        if self.state is RuntimeState.CONNECTED and self.connection_info is None: raise ValueError("connected requires connection info")
        if self.state is RuntimeState.ERROR and (not self.last_error or self.last_error.disposition is not ErrorDisposition.RUNTIME_FATAL): raise ValueError("error state requires fatal error")
        if self.disconnect_decision_pending and (self.state is not RuntimeState.BUSY or not self.connection_suspect or not self.active_task_id): raise ValueError("invalid disconnect decision")


@dataclass(frozen=True, slots=True)
class RequestRejection:
    code: RequestRejectionCode; message: str; task_id: str | None = None
@dataclass(frozen=True, slots=True)
class RequestAdmission:
    accepted: bool; task_id: str | None = None; rejection: RequestRejection | None = None; error: GuiRuntimeError | None = None
    def __post_init__(self):
        if self.accepted != (self.task_id is not None and self.rejection is None and self.error is None): raise ValueError("invalid admission")
@dataclass(frozen=True, slots=True)
class CancelRequestResult:
    accepted: bool; task_id: str; already_requested: bool = False; rejection: RequestRejection | None = None; error: GuiRuntimeError | None = None
    def __post_init__(self):
        if self.rejection and self.error: raise ValueError("rejection and error are exclusive")
@dataclass(frozen=True, slots=True)
class TaskActionResult:
    accepted: bool; task_id: str; action: TaskDialogAction; already_applied: bool = False; rejection: RequestRejection | None = None; error: GuiRuntimeError | None = None
    def __post_init__(self):
        if self.rejection and self.error: raise ValueError("rejection and error are exclusive")
@dataclass(frozen=True, slots=True)
class ApplicationCloseResult:
    decision: ApplicationCloseDecision; task_id: str | None = None; rejection: RequestRejection | None = None; error: GuiRuntimeError | None = None
    def __post_init__(self):
        if self.rejection and self.error: raise ValueError("rejection and error are exclusive")
