from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .runtime_models import *
from .runtime_ports import *
from .workers import *

class _Kind(Enum): CONNECT=auto(); TASK=auto(); DISCONNECT=auto(); SHUTDOWN=auto(); INTERNAL_DISCONNECT=auto()

@dataclass
class _Active:
    task_id: str; request: object; primary_plan: TaskPlan; plan: TaskPlan; kind: _Kind; origin: RuntimeState
    state: TaskState; generation: int = 0; cancellation: CancellationToken | None = None
    worker: TaskWorker | None = None; thread: QThread | None = None; result: TaskExecutionResult | None = None
    result_received: bool = False; thread_finished: bool = False; primary_result: TaskExecutionResult | None = None
    step_index: int = -1; step_started: bool = False; step_complete: bool = False; step_current: int = 0; step_total: int | None = None
    actions: set[TaskDialogAction] | None = None

class GuiController(QObject):
    runtimeStateChanged=Signal(object); taskStarted=Signal(object); taskProgressed=Signal(object); taskStateChanged=Signal(object); taskFinished=Signal(object)
    requestRejected=Signal(object); runtimeErrorRaised=Signal(object); shutdownReady=Signal(); forceExitReady=Signal(object)
    _threadViolationDetected=Signal(object)
    _threadExited=Signal(int)

    def __init__(self, runtime_port: RuntimePort, task_port: TaskPort, parent: QObject | None = None):
        super().__init__(parent); self.runtime_port=runtime_port; self.task_port=task_port; self._snapshot=RuntimeSnapshot(); self._active: _Active | None=None
        self._threadViolationDetected.connect(self._enter_fatal); self._threadExited.connect(self._on_thread_finished)

    @property
    def snapshot(self): return self._snapshot

    def _thread_ok(self, task_id=None):
        if QThread.currentThread() is self.thread(): return None
        error=GuiRuntimeError("WRONG_CONTROLLER_THREAD", "Controller called from the wrong thread", "controller", ErrorDisposition.RUNTIME_FATAL, task_id, False)
        self._threadViolationDetected.emit(error); return error

    def _reject(self, code, message, task_id=None):
        rejection=RequestRejection(code,message,task_id); self.requestRejected.emit(rejection); return RequestAdmission(False,rejection=rejection)

    def request_connect(self, request):
        if error:=self._thread_ok(): return RequestAdmission(False,error=error)
        if self._active: return self._reject(RequestRejectionCode.TASK_ALREADY_ACTIVE,"A task is already active")
        if self._snapshot.state is not RuntimeState.DISCONNECTED: return self._reject(RequestRejectionCode.INVALID_RUNTIME_STATE,"Connect requires disconnected state")
        return self._start(request,_Kind.CONNECT,RuntimeState.CONNECTING)

    def request_task(self, request):
        if error:=self._thread_ok(): return RequestAdmission(False,error=error)
        if self._active: return self._reject(RequestRejectionCode.TASK_ALREADY_ACTIVE,"A task is already active")
        task_id=uuid4().hex; plan=request.create_plan(task_id)
        if plan.task_id != task_id: return self._fatal_admission("INVALID_TASK_PLAN",task_id)
        if plan.connection_requirement is TaskConnectionRequirement.CONNECTED and self._snapshot.state is not RuntimeState.CONNECTED: return self._reject(RequestRejectionCode.INVALID_RUNTIME_STATE,"Task requires a connection")
        if self._snapshot.state not in (RuntimeState.DISCONNECTED,RuntimeState.CONNECTED): return self._reject(RequestRejectionCode.INVALID_RUNTIME_STATE,"Runtime is not idle")
        return self._start(request,_Kind.TASK,RuntimeState.BUSY,task_id,plan)

    def request_disconnect(self, request):
        if error:=self._thread_ok(): return RequestAdmission(False,error=error)
        if self._active: return self._reject(RequestRejectionCode.TASK_ALREADY_ACTIVE,"A task is already active")
        if self._snapshot.state is not RuntimeState.CONNECTED: return self._reject(RequestRejectionCode.INVALID_RUNTIME_STATE,"Disconnect requires connected state")
        return self._start(request,_Kind.DISCONNECT,RuntimeState.DISCONNECTING)

    def _start(self,request,kind,runtime_state,task_id=None,plan=None):
        task_id=task_id or uuid4().hex
        try: plan=plan or request.create_plan(task_id)
        except Exception: return self._fatal_admission("INVALID_TASK_PLAN",task_id)
        if plan.task_id != task_id: return self._fatal_admission("INVALID_TASK_PLAN",task_id)
        state=TaskState(task_id,plan,TaskPhase.PENDING)
        self._active=_Active(task_id,request,plan,plan,kind,self._snapshot.state,state,actions=set())
        self._set_snapshot(state=runtime_state,active_task_id=task_id,disconnect_decision_pending=False)
        self.taskStarted.emit(state); self._run_generation(); return RequestAdmission(True,task_id=task_id)

    def _run_generation(self):
        a=self._active; assert a
        a.cancellation=CancellationToken(); a.result=None; a.result_received=False; a.thread_finished=False; a.step_index=-1; a.step_started=False; a.step_complete=False; a.step_total=None
        if a.kind is _Kind.CONNECT: job=ConnectWorkerJob(a.task_id,self.runtime_port,a.request)
        elif a.kind in (_Kind.DISCONNECT,_Kind.INTERNAL_DISCONNECT): job=DisconnectWorkerJob(a.task_id,self.runtime_port,a.request)
        elif a.kind is _Kind.SHUTDOWN: job=ShutdownWorkerJob(a.task_id,self.runtime_port,a.request)
        else: job=TaskWorkerJob(a.task_id,self.task_port,a.request)
        thread=QThread(self); worker=TaskWorker(a.task_id,a.generation,job,a.cancellation,a.plan.cancellable)
        a.thread=thread; a.worker=worker; worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.progressReported.connect(self._on_progress); worker.resultReady.connect(self._on_result)
        worker.workFinished.connect(thread.quit); worker.workFinished.connect(worker.deleteLater); thread.finished.connect(lambda g=a.generation:self._threadExited.emit(g)); thread.finished.connect(thread.deleteLater)
        a.state=replace(a.state,phase=TaskPhase.RUNNING,started_at=a.state.started_at or self._now()); self.taskStateChanged.emit(a.state); thread.start()

    def request_cancel(self,task_id):
        if error:=self._thread_ok(task_id): return CancelRequestResult(False,task_id,error=error)
        a=self._active
        if not a or a.task_id != task_id: return CancelRequestResult(False,task_id,rejection=RequestRejection(RequestRejectionCode.UNKNOWN_TASK,"Unknown task",task_id))
        if not a.plan.cancellable: return CancelRequestResult(False,task_id,rejection=RequestRejection(RequestRejectionCode.TASK_NOT_CANCELLABLE,"Task is not cancellable",task_id))
        if a.state.cancel_requested: return CancelRequestResult(True,task_id,True)
        a.cancellation.request_cancel(); a.state=replace(a.state,phase=TaskPhase.CANCELLING,cancel_requested=True); self.taskStateChanged.emit(a.state); return CancelRequestResult(True,task_id)

    @Slot(object)
    def _on_progress(self,message):
        a=self._active
        if not isinstance(message,WorkerProgressMessage): return self._fatal("INVALID_WORKER_MESSAGE_TYPE")
        if not a or message.task_id != a.task_id: return self._fatal("UNKNOWN_WORKER_TASK")
        if message.execution_generation < a.generation: return
        if message.execution_generation != a.generation or a.result_received: return self._fatal("PROGRESS_AFTER_RESULT")
        try: self._apply_progress(message.update)
        except (ValueError,TypeError): self._fatal("INVALID_TASK_PROGRESS")

    def _apply_progress(self,u):
        a=self._active; assert a
        if not isinstance(u,TaskProgressUpdate) or u.task_id != a.task_id: raise ValueError
        steps=a.plan.steps
        if u.step_state is TaskStepState.STARTED:
            next_i=a.step_index+1
            if a.step_started and not a.step_complete or next_i>=len(steps) or steps[next_i].step_id!=u.step_id: raise ValueError
            a.step_index=next_i; a.step_started=True; a.step_complete=False; a.step_current=0; a.step_total=None
        elif u.step_state is TaskStepState.PROGRESS:
            if not a.step_started or a.step_complete or steps[a.step_index].step_id!=u.step_id: raise ValueError
            if u.progress_mode is ProgressMode.DETERMINATE:
                if u.current is None or u.total is None or u.total<=0 or not 0<=u.current<=u.total or u.current<a.step_current or a.step_total not in (None,u.total): raise ValueError
                a.step_current=u.current; a.step_total=u.total
            elif a.step_total is not None: raise ValueError
        else:
            if not a.step_started or a.step_complete or steps[a.step_index].step_id!=u.step_id: raise ValueError
            a.step_complete=True
        completed=sum(s.weight for s in steps[:a.step_index]) + (steps[a.step_index].weight if a.step_complete else 0)
        if not a.step_complete and a.step_total: completed += steps[a.step_index].weight*a.step_current/a.step_total
        overall=int(1000*completed/sum(s.weight for s in steps))
        a.state=replace(a.state,current_step_index=a.step_index,current_step_id=u.step_id,current_step_title=steps[a.step_index].title,message=u.message,overall_current=overall,step_current=u.current or 0,step_total=u.total or 0,step_progress_mode=u.progress_mode)
        self.taskProgressed.emit(u); self.taskStateChanged.emit(a.state)

    @Slot(object)
    def _on_result(self,message):
        a=self._active
        if not isinstance(message,WorkerResultMessage): return self._fatal("INVALID_WORKER_MESSAGE_TYPE")
        if not a or message.task_id != a.task_id: return self._fatal("UNKNOWN_WORKER_TASK")
        if message.execution_generation < a.generation: return
        if message.execution_generation != a.generation or a.result_received: return self._fatal("DUPLICATE_WORKER_RESULT")
        a.result=message.result; a.result_received=True; self._maybe_finish()

    @Slot(int)
    def _on_thread_finished(self,generation):
        a=self._active
        if not a or generation < a.generation: return
        if generation != a.generation: return self._fatal("INVALID_WORKER_GENERATION")
        a.thread_finished=True; a.thread=None; a.worker=None
        if not a.result_received: return self._fatal("WORKER_EXITED_WITHOUT_RESULT")
        self._maybe_finish()

    def _maybe_finish(self):
        a=self._active
        if not a or not (a.result_received and a.thread_finished): return
        result=a.result; assert result
        if result.status in (TaskFinalStatus.SUCCEEDED,TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST) and not all(i<a.step_index or (i==a.step_index and a.step_complete) for i in range(len(a.plan.steps))):
            return self._fatal("INCOMPLETE_SUCCESS_PROGRESS")
        if result.error and result.error.disposition is ErrorDisposition.RUNTIME_FATAL: return self._enter_fatal(result.error)
        if a.kind is _Kind.CONNECT: self._finish_connect(result)
        elif a.kind in (_Kind.DISCONNECT,_Kind.INTERNAL_DISCONNECT): self._finish_disconnect(result)
        elif a.kind is _Kind.SHUTDOWN: self._finish_shutdown(result)
        else: self._finish_task(result)

    def _finish_connect(self,result):
        if result.status is TaskFinalStatus.SUCCEEDED and isinstance(result.payload,ConnectionInfo): self._complete(result,RuntimeState.CONNECTED,connection_info=result.payload,connection_suspect=False,last_error=None)
        elif result.status is TaskFinalStatus.SUCCEEDED: self._fatal("CONNECT_MISSING_CONNECTION_INFO")
        else: self._complete(result,RuntimeState.DISCONNECTED,connection_info=None,connection_suspect=False)
    def _finish_disconnect(self,result): self._complete(self._active.primary_result or result,RuntimeState.DISCONNECTED,connection_info=None,connection_suspect=False,last_error=result.error)
    def _finish_task(self,result):
        a=self._active; assert a; a.primary_result=result
        if a.plan.connection_requirement is TaskConnectionRequirement.NONE:
            if result.completion_action is not TaskCompletionAction.NONE or result.error and result.error.disposition in (ErrorDisposition.ASK_DISCONNECT,ErrorDisposition.FORCE_DISCONNECTED): return self._fatal("INVALID_LOCAL_TASK_DISPOSITION")
            return self._complete(result,a.origin)
        if result.error and result.error.disposition is ErrorDisposition.ASK_DISCONNECT:
            actions=(TaskDialogAction.DISCONNECT,TaskDialogAction.KEEP_CONNECTION); a.state=replace(a.state,phase=TaskPhase.FINISHED,disposition_state=TaskDispositionState.AWAITING_DISCONNECT_DECISION,available_actions=actions,result=result,error=result.error)
            self._set_snapshot(state=RuntimeState.BUSY,connection_suspect=True,disconnect_decision_pending=True); self.taskStateChanged.emit(a.state); return
        if result.completion_action is TaskCompletionAction.RELEASE_CONNECTION: return self._begin_internal_disconnect()
        if result.error and result.error.disposition is ErrorDisposition.FORCE_DISCONNECTED: return self._complete(result,RuntimeState.DISCONNECTED,connection_info=None,connection_suspect=False)
        self._complete(result,RuntimeState.CONNECTED)

    def respond_task_action(self,task_id,action):
        if error:=self._thread_ok(task_id): return TaskActionResult(False,task_id,action,error=error)
        a=self._active
        if not a or a.task_id!=task_id: return TaskActionResult(False,task_id,action,rejection=RequestRejection(RequestRejectionCode.UNKNOWN_TASK,"Unknown task",task_id))
        if action in a.actions: return TaskActionResult(True,task_id,action,True)
        if action not in a.state.available_actions: return TaskActionResult(False,task_id,action,rejection=RequestRejection(RequestRejectionCode.ACTION_NOT_AVAILABLE,"Action unavailable",task_id))
        a.actions.add(action)
        if action is TaskDialogAction.KEEP_CONNECTION: self._complete(a.primary_result,RuntimeState.CONNECTED,connection_suspect=True,disconnect_decision_pending=False)
        elif action is TaskDialogAction.DISCONNECT: self._begin_internal_disconnect()
        elif action is TaskDialogAction.RETRY_CLEANUP: a.generation+=1; a.kind=_Kind.SHUTDOWN; self._run_generation()
        else: self.forceExitReady.emit(a.primary_result.error if a.primary_result else None)
        return TaskActionResult(True,task_id,action)

    def _begin_internal_disconnect(self):
        a=self._active; assert a; a.generation+=1; a.kind=_Kind.INTERNAL_DISCONNECT
        a.plan=TaskPlan(a.task_id,"Release Connection",(TaskStepPlan("release","Release Connection",ProgressMode.INDETERMINATE),),TaskConnectionRequirement.CONNECTED,False,CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT)
        a.state=TaskState(a.task_id,a.plan,TaskPhase.RUNNING,TaskDispositionState.DISCONNECTING,started_at=a.state.started_at)
        self._set_snapshot(state=RuntimeState.DISCONNECTING,disconnect_decision_pending=False); self.taskStateChanged.emit(a.state); self._run_generation()

    def request_application_close(self):
        if error:=self._thread_ok(): return ApplicationCloseResult(ApplicationCloseDecision.ERROR,error=error)
        if self._active: return ApplicationCloseResult(ApplicationCloseDecision.REJECTED,self._active.task_id,RequestRejection(RequestRejectionCode.CLOSE_NOT_ALLOWED,"Task active",self._active.task_id))
        if self._snapshot.state is RuntimeState.DISCONNECTED: return ApplicationCloseResult(ApplicationCloseDecision.ALLOW_IMMEDIATE)
        if self._snapshot.state is not RuntimeState.CONNECTED: return ApplicationCloseResult(ApplicationCloseDecision.REJECTED,rejection=RequestRejection(RequestRejectionCode.CLOSE_NOT_ALLOWED,"Runtime busy"))
        class _ShutdownRequest:
            def create_plan(_,task_id): return TaskPlan(task_id,"Shutdown",(TaskStepPlan("shutdown","Shutdown",ProgressMode.INDETERMINATE),),TaskConnectionRequirement.CONNECTED,False,CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT)
        admission=self._start(_ShutdownRequest(),_Kind.SHUTDOWN,RuntimeState.DISCONNECTING)
        self._set_snapshot(shutdown_requested=True); return ApplicationCloseResult(ApplicationCloseDecision.SHUTDOWN_STARTED,admission.task_id)

    def _finish_shutdown(self,result):
        if result.status is TaskFinalStatus.SUCCEEDED:
            self._complete(result,RuntimeState.DISCONNECTED,connection_info=None,connection_suspect=False,shutdown_requested=False,last_error=None); self.shutdownReady.emit()
        else:
            a=self._active; a.primary_result=result; a.state=replace(a.state,phase=TaskPhase.FINISHED,available_actions=(TaskDialogAction.RETRY_CLEANUP,TaskDialogAction.FORCE_EXIT),result=result,error=result.error)
            self._set_snapshot(state=RuntimeState.DISCONNECTING,connection_info=None,shutdown_requested=True,last_error=result.error); self.taskStateChanged.emit(a.state)

    def _complete(self,result,state,**snapshot_changes):
        a=self._active; assert a
        auto=800 if result.status is TaskFinalStatus.SUCCEEDED and not result.warning and a.primary_plan.completion_policy is CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS else None
        final=replace(a.state,phase=TaskPhase.FINISHED,disposition_state=TaskDispositionState.COMPLETE,available_actions=(),close_allowed=True,auto_close_delay_ms=auto,finished_at=self._now(),result=result,error=result.error)
        self._active=None; self._set_snapshot(state=state,active_task_id=None,disconnect_decision_pending=False,**snapshot_changes); self.taskStateChanged.emit(final); self.taskFinished.emit(result)

    def _set_snapshot(self,**changes):
        new=replace(self._snapshot,**changes)
        if new!=self._snapshot: self._snapshot=new; self.runtimeStateChanged.emit(new)
    def _fatal_admission(self,code,task_id):
        error=self._make_fatal(code,task_id); self._enter_fatal(error); return RequestAdmission(False,error=error)
    def _fatal(self,code): self._enter_fatal(self._make_fatal(code,self._active.task_id if self._active else None))
    def _make_fatal(self,code,task_id=None): return GuiRuntimeError(code,"GUI runtime contract violation","controller",ErrorDisposition.RUNTIME_FATAL,task_id,False)
    @Slot(object)
    def _enter_fatal(self,error):
        self._set_snapshot(state=RuntimeState.ERROR,last_error=error,active_task_id=self._active.task_id if self._active else None); self.runtimeErrorRaised.emit(error)
    @staticmethod
    def _now():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)
