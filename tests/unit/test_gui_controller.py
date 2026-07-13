from datetime import datetime, timezone
import pytest
from threading import Event, Thread
from bootloader_upgrade_tool.gui.workers import WorkerProgressMessage, WorkerResultMessage

from bootloader_upgrade_tool.gui.connection_models import SerialConnectRequest
from bootloader_upgrade_tool.gui.controller import GuiController
from bootloader_upgrade_tool.gui.runtime_models import *
from gui_runtime_fakes import FakePort, FakeRequest, ScriptedPort
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication
from time import monotonic

_APP = QApplication.instance() or QApplication([])
_CONTROLLERS=[]

def _wait(predicate):
    deadline=monotonic()+2
    while not predicate() and monotonic()<deadline: _APP.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
    assert predicate()

def _result(task_id, kind):
    payload = ConnectionInfo("c", "SCI", "COM1", datetime.now(timezone.utc), "cpu1") if kind == "connect" else None
    return TaskExecutionResult(task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload)

def test_controller_admits_only_one_task():
    port=FakePort(_result); controller=GuiController(port, port); _CONTROLLERS.append(controller)
    admission=controller.request_task(FakeRequest())
    assert admission.accepted
    assert not controller.request_task(FakeRequest()).accepted
    _wait(lambda: controller.snapshot.active_task_id is None)

def test_connect_success_enters_connected():
    port=FakePort(_result); controller=GuiController(port, port); _CONTROLLERS.append(controller)
    assert controller.request_connect(FakeRequest("Connect")).accepted
    _wait(lambda: controller.snapshot.state is RuntimeState.CONNECTED)

def _failure(task_id, disposition=ErrorDisposition.SHOW_ONLY, code="FAIL", cleanup_pending=False):
    error=GuiRuntimeError(code,"failed","test",disposition,task_id,disposition is not ErrorDisposition.RUNTIME_FATAL,disposition is ErrorDisposition.ASK_DISCONNECT,details={"cleanup_pending":cleanup_pending})
    return TaskExecutionResult(task_id,TaskFinalStatus.FAILED,"failed","failed",error=error)

def test_invalid_progress_fatal_is_latched_and_converges():
    class BadPort(FakePort):
        def _run(self,name,task_id,request,cancellation,progress):
            progress(TaskProgressUpdate(task_id,"wrong",TaskStepState.STARTED,"x","bad"))
            return _result(task_id,name)
    port=BadPort(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); finished=[]; controller.taskFinished.connect(finished.append)
    controller.request_task(FakeRequest()); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.ERROR and controller.snapshot.last_error.code=="INVALID_TASK_PROGRESS"
    assert finished[-1].status is TaskFinalStatus.FAILED
    assert not controller.request_task(FakeRequest()).accepted

def test_ask_disconnect_uses_release_plan_and_preserves_primary_error():
    uncertain=lambda tid,_:_failure(tid,ErrorDisposition.ASK_DISCONNECT,"TIMEOUT")
    cleanup=lambda tid,_:_failure(tid,ErrorDisposition.SHOW_ONLY,"CLEANUP")
    port=ScriptedPort([_result,uncertain,cleanup]); controller=GuiController(port,port); _CONTROLLERS.append(controller)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED)
    admission=controller.request_task(FakeRequest("Connected",TaskConnectionRequirement.CONNECTED)); _wait(lambda:controller.snapshot.disconnect_decision_pending)
    assert not controller.request_cancel(admission.task_id).accepted
    controller.respond_task_action(admission.task_id,TaskDialogAction.DISCONNECT); _wait(lambda:controller.snapshot.active_task_id is None)
    assert port.step_ids[-1] == ("release",) and controller.snapshot.state is RuntimeState.DISCONNECTED

def test_final_task_state_precedes_runtime_and_finished():
    port=FakePort(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); events=[]
    controller.taskStateChanged.connect(lambda s: events.append(("task",s.phase)))
    controller.runtimeStateChanged.connect(lambda s: events.append(("runtime",s.state)))
    controller.taskFinished.connect(lambda _: events.append(("finished",controller.snapshot.active_task_id)))
    controller.request_task(FakeRequest()); _wait(lambda:controller.snapshot.active_task_id is None)
    tail=[e[0] for e in events[-3:]]; assert tail == ["task","runtime","finished"] and events[-1][1] is None

@pytest.mark.parametrize("illegal", [
    lambda tid,_: TaskExecutionResult(tid,TaskFinalStatus.SUCCEEDED,"ok","ok",payload=ConnectionInfo("c","SCI","COM1",datetime.now(timezone.utc),"cpu1"),completion_action=TaskCompletionAction.RELEASE_CONNECTION),
    lambda tid,_: _failure(tid,ErrorDisposition.ASK_DISCONNECT),
    lambda tid,_: _failure(tid,ErrorDisposition.FORCE_DISCONNECTED),
    lambda tid,_: TaskExecutionResult(tid,TaskFinalStatus.SUCCEEDED,"ok","ok"),
])
def test_connect_illegal_results_latch_error(illegal):
    port=ScriptedPort([illegal]); controller=GuiController(port,port); _CONTROLLERS.append(controller)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.ERROR

def test_release_cleanup_failure_keeps_success_and_adds_warning():
    release=lambda tid,_: TaskExecutionResult(tid,TaskFinalStatus.SUCCEEDED,"ran","primary",completion_action=TaskCompletionAction.RELEASE_CONNECTION)
    port=ScriptedPort([_result,release,lambda tid,_:_failure(tid)]); controller=GuiController(port,port); _CONTROLLERS.append(controller); final=[]; controller.taskFinished.connect(final.append)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED)
    controller.request_task(FakeRequest("Run",TaskConnectionRequirement.CONNECTED)); _wait(lambda:controller.snapshot.active_task_id is None)
    assert final[-1].status is TaskFinalStatus.SUCCEEDED and final[-1].summary=="ran" and final[-1].warning.code=="CONNECTION_RELEASE_FAILED"

def test_shutdown_retry_can_repeat_and_force_exit_emits_once():
    port=ScriptedPort([_result,lambda tid,_:_failure(tid),lambda tid,_:_failure(tid),lambda tid,_:_failure(tid)]); controller=GuiController(port,port); _CONTROLLERS.append(controller); forced=[]; controller.forceExitReady.connect(forced.append)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED)
    close=controller.request_application_close(); _wait(lambda:controller._active and controller._active.state.phase is TaskPhase.FINISHED)
    for _ in range(2):
        assert controller.respond_task_action(close.task_id,TaskDialogAction.RETRY_CLEANUP).accepted
        _wait(lambda:controller._active and controller._active.state.phase is TaskPhase.FINISHED)
    controller.respond_task_action(close.task_id,TaskDialogAction.FORCE_EXIT); controller.respond_task_action(close.task_id,TaskDialogAction.FORCE_EXIT)
    assert len(forced)==1 and controller.snapshot.shutdown_requested

@pytest.mark.parametrize("status",[TaskFinalStatus.FAILED,TaskFinalStatus.CANCELLED])
def test_connect_normal_failure_or_cancel_returns_disconnected(status):
    def outcome(tid,_):
        return _failure(tid) if status is TaskFinalStatus.FAILED else TaskExecutionResult(tid,status,"cancelled","cancelled",cancel_requested=True)
    port=ScriptedPort([outcome]); controller=GuiController(port,port); _CONTROLLERS.append(controller)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.DISCONNECTED and controller.snapshot.last_error is None

def test_ask_disconnect_keep_connection_preserves_suspect_connection():
    port=ScriptedPort([_result,lambda tid,_:_failure(tid,ErrorDisposition.ASK_DISCONNECT,"TIMEOUT")]); controller=GuiController(port,port); _CONTROLLERS.append(controller)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED)
    admission=controller.request_task(FakeRequest("Task",TaskConnectionRequirement.CONNECTED)); _wait(lambda:controller.snapshot.disconnect_decision_pending)
    controller.respond_task_action(admission.task_id,TaskDialogAction.KEEP_CONNECTION)
    assert controller.snapshot.state is RuntimeState.CONNECTED and controller.snapshot.connection_suspect and controller.snapshot.active_task_id is None

def test_user_disconnect_failure_retains_global_error():
    port=ScriptedPort([_result,lambda tid,_:_failure(tid)]); controller=GuiController(port,port); _CONTROLLERS.append(controller)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED)
    controller.request_disconnect(FakeRequest("Disconnect",TaskConnectionRequirement.CONNECTED,False)); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.DISCONNECTED and controller.snapshot.last_error.code=="FAIL" and controller.snapshot.cleanup_pending

def test_connected_force_disconnected_clears_connection_and_sets_error():
    port=ScriptedPort([_result,lambda tid,_:_failure(tid,ErrorDisposition.FORCE_DISCONNECTED,"LOST")]); controller=GuiController(port,port); _CONTROLLERS.append(controller)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED)
    controller.request_task(FakeRequest("Task",TaskConnectionRequirement.CONNECTED)); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.DISCONNECTED and controller.snapshot.connection_info is None and controller.snapshot.last_error.code=="LOST"

def test_shutdown_success_emits_ready_after_task_finished():
    port=ScriptedPort([_result,_result]); controller=GuiController(port,port); _CONTROLLERS.append(controller); events=[]; controller.taskFinished.connect(lambda _:events.append("finished")); controller.shutdownReady.connect(lambda:events.append("ready"))
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED)
    controller.request_application_close(); _wait(lambda:"ready" in events)
    assert events[-2:]==["finished","ready"] and controller.snapshot.state is RuntimeState.DISCONNECTED

def test_weighted_progress_is_strict_and_determinate():
    class Request:
        def create_plan(self,tid): return TaskPlan(tid,"Weighted",(TaskStepPlan("a","A",ProgressMode.DETERMINATE,1),TaskStepPlan("b","B",ProgressMode.DETERMINATE,3)),TaskConnectionRequirement.NONE,True,CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT)
    class Port(FakePort):
        def _run(self,name,tid,request,cancel,progress):
            progress(TaskProgressUpdate(tid,"a",TaskStepState.STARTED,"x","a",0,4,ProgressMode.DETERMINATE)); progress(TaskProgressUpdate(tid,"a",TaskStepState.PROGRESS,"x","a",2,4,ProgressMode.DETERMINATE)); progress(TaskProgressUpdate(tid,"a",TaskStepState.COMPLETED,"x","a",4,4,ProgressMode.DETERMINATE)); progress(TaskProgressUpdate(tid,"b",TaskStepState.STARTED,"x","b",0,1,ProgressMode.DETERMINATE)); progress(TaskProgressUpdate(tid,"b",TaskStepState.COMPLETED,"x","b",1,1,ProgressMode.DETERMINATE)); return _result(tid,name)
    port=Port(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); overall=[]; controller.taskStateChanged.connect(lambda s:overall.append(s.overall_current))
    controller.request_task(Request()); _wait(lambda:controller.snapshot.active_task_id is None)
    assert 125 in overall and 250 in overall and 1000 in overall

class _BlockingPort(FakePort):
    def __init__(self): super().__init__(_result); self.entered=Event(); self.release=Event(); self.cancellation=None
    def _run(self,name,tid,request,cancel,progress):
        self.cancellation=cancel; plan=request.create_plan(tid); step=plan.steps[0]; progress(TaskProgressUpdate(tid,step.step_id,TaskStepState.STARTED,name,"started",progress_mode=step.initial_progress_mode)); progress(TaskProgressUpdate(tid,step.step_id,TaskStepState.COMPLETED,name,"done",progress_mode=step.initial_progress_mode)); self.entered.set(); self.release.wait(2); return _result(tid,name)

def test_current_generation_duplicate_result_latches_fatal_and_old_generation_is_ignored():
    port=_BlockingPort(); controller=GuiController(port,port); _CONTROLLERS.append(controller); admission=controller.request_task(FakeRequest()); assert port.entered.wait(1)
    old=WorkerProgressMessage(admission.task_id,-1,TaskProgressUpdate(admission.task_id,"work",TaskStepState.STARTED,"x","old")); controller._on_progress(old); assert controller.snapshot.state is RuntimeState.BUSY
    result=_result(admission.task_id,"execute"); message=WorkerResultMessage(admission.task_id,0,result); controller._on_result(message); controller._on_result(message); port.release.set(); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.ERROR and controller.snapshot.last_error.code=="DUPLICATE_WORKER_RESULT"

def test_wrong_thread_request_is_rejected_and_queued_as_fatal():
    port=FakePort(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); returned=[]
    thread=Thread(target=lambda:returned.append(controller.request_task(FakeRequest()))); thread.start(); thread.join(); _wait(lambda:controller.snapshot.state is RuntimeState.ERROR)
    assert not returned[0].accepted and returned[0].error.code=="WRONG_CONTROLLER_THREAD" and not port.calls

def test_cancellation_is_cooperative_and_repeated_request_is_idempotent():
    port=_BlockingPort(); controller=GuiController(port,port); _CONTROLLERS.append(controller); admission=controller.request_task(FakeRequest()); assert port.entered.wait(1)
    first=controller.request_cancel(admission.task_id); second=controller.request_cancel(admission.task_id)
    assert first.accepted and second.accepted and second.already_requested and port.cancellation.is_cancel_requested() and controller._active.state.phase is TaskPhase.CANCELLING
    port.release.set(); _wait(lambda:controller.snapshot.active_task_id is None)


def test_real_connect_plan_cancellation_reaches_worker_and_finishes_disconnected():
    request = SerialConnectRequest("COM3", 115200, 1000, 1000, 5000)
    assert request.create_plan("plan").cancellable

    class Port(FakePort):
        def __init__(self):
            super().__init__(_result); self.entered=Event(); self.release=Event(); self.cancellation=None
        def _run(self,name,tid,request,cancellation,progress):
            self.cancellation=cancellation
            progress(TaskProgressUpdate(tid,"connect_sci",TaskStepState.STARTED,"CONNECT_SCI","opening"))
            self.entered.set(); self.release.wait(2)
            assert cancellation.is_cancel_requested()
            return TaskExecutionResult(tid,TaskFinalStatus.CANCELLED,"Connection cancelled","cancelled",cancel_requested=True)

    port=Port(); controller=GuiController(port,port); _CONTROLLERS.append(controller)
    admission=controller.request_connect(request); assert admission.accepted and port.entered.wait(1)
    first=controller.request_cancel(admission.task_id); second=controller.request_cancel(admission.task_id)
    assert first.accepted and second.accepted and second.already_requested
    assert port.cancellation.is_cancel_requested()
    port.release.set(); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.DISCONNECTED
    assert controller.snapshot.connection_info is None and controller.snapshot.active_target_key is None
    assert controller.snapshot.last_error is None

def test_prestart_plan_failure_returns_fatal_without_task_started():
    class BadRequest:
        def create_plan(self,task_id): raise RuntimeError("bad plan")
    port=FakePort(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); started=[]; controller.taskStarted.connect(started.append)
    admission=controller.request_task(BadRequest())
    assert not admission.accepted and admission.error.disposition is ErrorDisposition.RUNTIME_FATAL and not started and controller.snapshot.state is RuntimeState.ERROR

def test_fatal_final_snapshot_is_published_between_state_and_result():
    class BadPort(FakePort):
        def _run(self,name,tid,request,cancel,progress): progress(TaskProgressUpdate(tid,"bad",TaskStepState.STARTED,"x","bad")); return _result(tid,name)
    controller=GuiController(BadPort(_result),BadPort(_result)); _CONTROLLERS.append(controller); events=[]
    controller.taskStateChanged.connect(lambda s:events.append(("task",s.task_id)))
    controller.runtimeStateChanged.connect(lambda s:events.append(("runtime",s.active_task_id)))
    controller.taskFinished.connect(lambda r:events.append(("finished",r.task_id)))
    controller.request_task(FakeRequest()); _wait(lambda:controller.snapshot.active_task_id is None)
    assert events[-3:][0][0]=="task" and events[-3:][1]==("runtime",None) and events[-3:][2][0]=="finished"

class _BadPlanRequest:
    def create_plan(self,task_id): return object()

def test_connect_non_plan_is_prestart_fatal_without_task_started():
    port=FakePort(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); started=[]; controller.taskStarted.connect(started.append)
    admission=controller.request_connect(_BadPlanRequest())
    assert not admission.accepted and admission.error and not started and controller.snapshot.active_task_id is None

def test_disconnect_non_plan_is_prestart_fatal_without_task_started():
    port=FakePort(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED); started=[]; controller.taskStarted.connect(started.append)
    admission=controller.request_disconnect(_BadPlanRequest())
    assert not admission.accepted and admission.error and not started and controller.snapshot.active_task_id is None

def test_shutdown_start_failure_returns_error_not_started(monkeypatch):
    port=FakePort(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED)
    monkeypatch.setattr(controller,"_prepare_generation",lambda:(_ for _ in ()).throw(RuntimeError("startup")))
    close=controller.request_application_close()
    assert close.decision is ApplicationCloseDecision.ERROR and close.error and close.task_id is None and not controller.snapshot.shutdown_requested

def test_internal_generation_preparation_failure_converges(monkeypatch):
    port=ScriptedPort([_result,lambda tid,_:_failure(tid,ErrorDisposition.ASK_DISCONNECT)]); controller=GuiController(port,port); _CONTROLLERS.append(controller); controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED)
    admission=controller.request_task(FakeRequest("Task",TaskConnectionRequirement.CONNECTED)); _wait(lambda:controller.snapshot.disconnect_decision_pending)
    monkeypatch.setattr(controller,"_prepare_generation",lambda:(_ for _ in ()).throw(RuntimeError("startup"))); controller.respond_task_action(admission.task_id,TaskDialogAction.DISCONNECT)
    assert controller.snapshot.state is RuntimeState.ERROR and controller.snapshot.active_task_id is None

def test_internal_disconnect_cancelled_is_fatal():
    cancelled=lambda tid,_:TaskExecutionResult(tid,TaskFinalStatus.CANCELLED,"cancelled","cancelled",cancel_requested=True)
    release=lambda tid,_:TaskExecutionResult(tid,TaskFinalStatus.SUCCEEDED,"ok","ok",completion_action=TaskCompletionAction.RELEASE_CONNECTION)
    port=ScriptedPort([_result,release,cancelled]); controller=GuiController(port,port); _CONTROLLERS.append(controller); controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED); controller.request_task(FakeRequest("Run",TaskConnectionRequirement.CONNECTED)); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.ERROR

def test_shutdown_cancelled_is_fatal():
    cancelled=lambda tid,_:TaskExecutionResult(tid,TaskFinalStatus.CANCELLED,"cancelled","cancelled",cancel_requested=True)
    port=ScriptedPort([_result,cancelled]); controller=GuiController(port,port); _CONTROLLERS.append(controller); controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED); controller.request_application_close(); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.ERROR

def test_worker_fatal_result_evidence_is_preserved():
    def fatal(tid,_):
        error=GuiRuntimeError("PORT_BUG","port bug","worker",ErrorDisposition.RUNTIME_FATAL,tid,False,details={"detail":"kept"},cause_summary="cause")
        return TaskExecutionResult(tid,TaskFinalStatus.FAILED,"worker summary","worker message",step_results=("evidence",),payload={"safe":1},error=error)
    port=ScriptedPort([fatal]); controller=GuiController(port,port); _CONTROLLERS.append(controller); results=[]; controller.taskFinished.connect(results.append); controller.request_task(FakeRequest()); _wait(lambda:controller.snapshot.active_task_id is None)
    result=results[-1]; assert result.summary=="worker summary" and result.message=="worker message" and result.step_results==("evidence",) and result.payload["safe"]==1 and result.error.cause_summary=="cause"


def test_progress_allows_indeterminate_to_determinate_transition():
    class Port(FakePort):
        def _run(self,name,tid,request,cancel,progress):
            progress(TaskProgressUpdate(tid,"work",TaskStepState.STARTED,"x","start",progress_mode=ProgressMode.INDETERMINATE))
            progress(TaskProgressUpdate(tid,"work",TaskStepState.PROGRESS,"x","known",1,4,ProgressMode.DETERMINATE))
            progress(TaskProgressUpdate(tid,"work",TaskStepState.COMPLETED,"x","done",4,4,ProgressMode.DETERMINATE))
            return _result(tid,name)
    port=Port(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); controller.request_task(FakeRequest()); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.DISCONNECTED


@pytest.mark.parametrize("updates",[
    [(TaskStepState.STARTED,ProgressMode.INDETERMINATE,0,None)],
    [(TaskStepState.STARTED,ProgressMode.DETERMINATE,0,0)],
    [(TaskStepState.STARTED,ProgressMode.DETERMINATE,2,1)],
    [(TaskStepState.STARTED,ProgressMode.DETERMINATE,1,4),(TaskStepState.PROGRESS,ProgressMode.DETERMINATE,0,4)],
    [(TaskStepState.STARTED,ProgressMode.DETERMINATE,1,4),(TaskStepState.PROGRESS,ProgressMode.DETERMINATE,2,5)],
    [(TaskStepState.STARTED,ProgressMode.DETERMINATE,1,4),(TaskStepState.PROGRESS,ProgressMode.INDETERMINATE,None,None)],
])
def test_invalid_progress_modes_and_numbers_latch_fatal_without_normal_progress(updates):
    class Port(FakePort):
        def _run(self,name,tid,request,cancel,progress):
            for state,mode,current,total in updates:progress(TaskProgressUpdate(tid,"work",state,"x","bad",current,total,mode))
            return _result(tid,name)
    port=Port(_result); controller=GuiController(port,port); _CONTROLLERS.append(controller); progressed=[]; controller.taskProgressed.connect(progressed.append); controller.request_task(FakeRequest()); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.ERROR and len(progressed)==len(updates)-1


@pytest.mark.parametrize("bad_result",[object(),TaskExecutionResult("other",TaskFinalStatus.SUCCEEDED,"ok","ok")])
def test_invalid_worker_result_type_or_task_id_latches_fatal(bad_result):
    port=_BlockingPort(); controller=GuiController(port,port); _CONTROLLERS.append(controller); admission=controller.request_task(FakeRequest()); assert port.entered.wait(1)
    controller._on_result(WorkerResultMessage(admission.task_id,0,bad_result)); port.release.set(); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.ERROR and controller.snapshot.last_error.code=="INVALID_WORKER_RESULT"


def test_internal_disconnect_publishes_running_once():
    uncertain=lambda tid,_:_failure(tid,ErrorDisposition.ASK_DISCONNECT)
    port=ScriptedPort([_result,uncertain,_result]); controller=GuiController(port,port); _CONTROLLERS.append(controller); states=[]; controller.taskStateChanged.connect(states.append)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED); admission=controller.request_task(FakeRequest("Task",TaskConnectionRequirement.CONNECTED)); _wait(lambda:controller.snapshot.disconnect_decision_pending); controller.respond_task_action(admission.task_id,TaskDialogAction.DISCONNECT); _wait(lambda:controller.snapshot.active_task_id is None)
    release_running=[state for state in states if state.plan.steps[0].step_id=="release" and state.phase is TaskPhase.RUNNING and state.current_step_index is None]
    assert len(release_running)==1


def test_shutdown_retry_publishes_running_once():
    port=ScriptedPort([_result,lambda tid,_:_failure(tid),lambda tid,_:_failure(tid)]); controller=GuiController(port,port); _CONTROLLERS.append(controller); states=[]; controller.taskStateChanged.connect(states.append)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.state is RuntimeState.CONNECTED); close=controller.request_application_close(); _wait(lambda:controller._active and controller._active.state.phase is TaskPhase.FINISHED); states.clear()
    controller.respond_task_action(close.task_id,TaskDialogAction.RETRY_CLEANUP); _wait(lambda:controller._active and controller._active.state.phase is TaskPhase.FINISHED)
    running=[state for state in states if state.plan.steps[0].step_id=="shutdown" and state.phase is TaskPhase.RUNNING and state.current_step_index is None]
    assert len(running)==1


def test_connection_info_requires_explicit_target():
    with pytest.raises(TypeError):
        ConnectionInfo("c", "SCI", "COM1", datetime.now(timezone.utc))


@pytest.mark.parametrize("pending", [False, True])
def test_connect_failure_publishes_cleanup_pending(pending):
    port=ScriptedPort([lambda tid,_:_failure(tid, cleanup_pending=pending)]); controller=GuiController(port,port); _CONTROLLERS.append(controller)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.DISCONNECTED and controller.snapshot.cleanup_pending is pending


def test_close_disconnected_with_pending_cleanup_runs_shutdown_and_clears_pending():
    port=ScriptedPort([lambda tid,_:_failure(tid, cleanup_pending=True), _result]); controller=GuiController(port,port); _CONTROLLERS.append(controller)
    controller.request_connect(FakeRequest("Connect")); _wait(lambda:controller.snapshot.active_task_id is None)
    close=controller.request_application_close()
    assert close.decision is ApplicationCloseDecision.SHUTDOWN_STARTED
    _wait(lambda:controller.snapshot.active_task_id is None)
    assert controller.snapshot.state is RuntimeState.DISCONNECTED and not controller.snapshot.cleanup_pending
