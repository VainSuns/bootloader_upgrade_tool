from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

import pytest

from bootloader_upgrade_tool.gui.runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)
from bootloader_upgrade_tool.gui.runtime_ports import CancellationToken
from bootloader_upgrade_tool.gui.workers import TaskWorker, WorkerFinishedMessage, WorkerResultMessage
from bootloader_upgrade_tool.gui.runtime_models import TaskExecutionResult, TaskFinalStatus
from bootloader_upgrade_tool.gui.runtime_ports import ConnectWorkerJob, DisconnectWorkerJob, ShutdownWorkerJob, TaskWorkerJob
from PySide6.QtCore import QCoreApplication, QEventLoop, QThread
from time import monotonic


class _Job:
    task_id = "id"
    def execute(self, cancellation, progress):
        return TaskExecutionResult("id", TaskFinalStatus.SUCCEEDED, "ok", "ok")


def test_plan_rejects_state_machine_breaking_shapes() -> None:
    step = TaskStepPlan("prepare", "Prepare", ProgressMode.INDETERMINATE)
    with pytest.raises(ValueError):
        TaskPlan("id", "Title", (), TaskConnectionRequirement.NONE, True, CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT)
    with pytest.raises(ValueError):
        TaskPlan("id", "Title", (step, step), TaskConnectionRequirement.NONE, True, CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT)


def test_cancellation_token_is_idempotent() -> None:
    token = CancellationToken()
    assert not token.is_cancel_requested()
    token.request_cancel()
    token.request_cancel()
    assert token.is_cancel_requested()


@pytest.mark.parametrize("bad", [{1: "x"}, {"x": b"bytes"}, {"x": {1}}, {"x": Lock()}, {"x": lambda: None}])
def test_details_reject_runtime_resources_and_non_string_keys(bad) -> None:
    from bootloader_upgrade_tool.gui.runtime_models import GuiTaskWarning
    with pytest.raises((TypeError, ValueError)):
        GuiTaskWarning("W", "warning", "test", bad)


def test_details_are_recursively_copied_and_frozen() -> None:
    from bootloader_upgrade_tool.gui.runtime_models import GuiTaskWarning
    source={"nested":{"items":[1,"x",None]}}
    warning=GuiTaskWarning("W","warning","test",source)
    source["nested"]["items"].append(2)
    assert warning.details["nested"]["items"] == (1,"x",None)
    with pytest.raises(TypeError): warning.details["new"] = 1


def test_all_worker_job_adapters_delegate() -> None:
    class Port:
        def __init__(self): self.calls=[]
        def _call(self,name,*args): self.calls.append((name,args)); return "result"
        def connect(self,*args): return self._call("connect",*args)
        def disconnect(self,*args): return self._call("disconnect",*args)
        def shutdown(self,*args): return self._call("shutdown",*args)
        def execute(self,*args): return self._call("execute",*args)
    port=Port(); token=CancellationToken(); progress=lambda _:None
    jobs=(ConnectWorkerJob("id",port,"r"),DisconnectWorkerJob("id",port,"r"),ShutdownWorkerJob("id",port,"r"),TaskWorkerJob("id",port,"r"))
    assert [job.execute(token,progress) for job in jobs] == ["result"]*4
    assert [name for name,_ in port.calls] == ["connect","disconnect","shutdown","execute"]


def _pump_until(predicate, timeout=2):
    app=QCoreApplication.instance() or QCoreApplication([]); deadline=monotonic()+timeout
    while not predicate() and monotonic()<deadline: app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents,10)
    assert predicate()


def test_worker_runs_in_real_qthread_and_exits_cleanly() -> None:
    gui_thread=QThread.currentThread(); seen=[]
    class Job(_Job):
        def execute(self,cancellation,progress): seen.append(QThread.currentThread()); return super().execute(cancellation,progress)
    thread=QThread(); worker=TaskWorker("id",1,Job(),CancellationToken(),True); results=[]; finished=[]
    worker.moveToThread(thread); thread.started.connect(worker.run); worker.resultReady.connect(results.append); worker.workFinished.connect(finished.append); worker.workFinished.connect(thread.quit); thread.start()
    _pump_until(lambda:not thread.isRunning())
    assert seen and seen[0] is not gui_thread and len(results)==len(finished)==1


@pytest.mark.parametrize("job", [type("Boom",(),{"task_id":"id","execute":lambda *args: (_ for _ in ()).throw(RuntimeError("boom"))})(), type("Bad",(),{"task_id":"id","execute":lambda *args: object()})()])
def test_worker_converts_exception_or_invalid_result_to_fatal(job) -> None:
    worker=TaskWorker("id",1,job,CancellationToken(),True); results=[]; finished=[]
    worker.resultReady.connect(results.append); worker.workFinished.connect(finished.append); worker.run()
    assert results[0].result.error.disposition.name == "RUNTIME_FATAL" and len(finished)==1


def test_worker_pre_cancel_skips_job() -> None:
    called=[]
    class Job(_Job):
        def execute(self,*args): called.append(True); return super().execute(*args)
    token=CancellationToken(); token.request_cancel(); results=[]
    worker=TaskWorker("id",1,Job(),token,True); worker.resultReady.connect(results.append); worker.run()
    assert not called and results[0].result.status is TaskFinalStatus.CANCELLED


def test_result_step_results_and_safe_payload_are_copied_and_frozen() -> None:
    payload={"items":[{"value":1}]}; steps=["one"]
    result=TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"ok","ok",step_results=steps,payload=payload)
    steps.append("two"); payload["items"][0]["value"]=2
    assert result.step_results == ("one",) and result.payload["items"][0]["value"] == 1
    with pytest.raises(TypeError): result.payload["x"] = 1


@pytest.mark.parametrize("payload", [Lock(), lambda:None, object()])
def test_result_payload_rejects_runtime_resources(payload) -> None:
    with pytest.raises(TypeError): TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"ok","ok",payload=payload)


def test_worker_emits_one_result_and_finished() -> None:
    worker = TaskWorker("id", 2, _Job(), CancellationToken(), True)
    results, finished = [], []
    worker.resultReady.connect(results.append)
    worker.workFinished.connect(finished.append)
    worker.run()
    assert isinstance(results[0], WorkerResultMessage)
    assert isinstance(finished[0], WorkerFinishedMessage)
