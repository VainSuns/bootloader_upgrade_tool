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
from bootloader_upgrade_tool.operations.results import OperationErrorInfo, OperationResult, ProgressEvent, operation_result_to_dict
from dataclasses import dataclass
from bootloader_upgrade_tool.firmware.models import AddressRange, FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.images.models import ImageIdentity, PreparedFlashImage, PreparedRamImage, PreparedServiceImage


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


def test_successful_operation_result_is_preserved_and_recursively_frozen() -> None:
    summary={"counts":{"words":4}}; details={"chunks":[{"size":2}]}; service={"loaded":True}; warning={"code":"slow"}
    operation=OperationResult(True,"program","CPU1","program",summary,details,service,warning)
    result=TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"ok","ok",step_results=(operation,))
    summary["counts"]["words"]=9; details["chunks"][0]["size"]=8; service["loaded"]=False; warning["code"]="changed"
    stored=result.step_results[0]
    assert isinstance(stored,OperationResult)
    assert stored.summary["counts"]["words"]==4 and stored.details["chunks"][0]["size"]==2
    assert stored.service["loaded"] is True and stored.warning["code"]=="slow"
    with pytest.raises(TypeError): stored.summary["new"]=1


def test_failed_operation_result_and_error_info_remain_typed_and_frozen() -> None:
    error_details={"status":{"code":7}}
    operation=OperationResult(False,"verify","CPU1","verify",{},error=OperationErrorInfo("VERIFY_FAILED","failed","verify",details=error_details))
    result=TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"captured","captured",step_results=[operation])
    error_details["status"]["code"]=8
    stored=result.step_results[0]
    assert isinstance(stored,OperationResult) and isinstance(stored.error,OperationErrorInfo)
    assert stored.error.details["status"]["code"]==7
    with pytest.raises(TypeError): stored.error.details["new"]=1


def _prepared_images():
    format_info={"format":"sci8","metadata":{"labels":["original"]}}
    image=FirmwareImage(source_out_file="app.out",generated_hex_file="app.txt",entry_point=0x1000,blocks=[FirmwareBlock(0x1000,[1,2,3])],file_checksum="abc",format_info=format_info)
    identity=ImageIdentity(0x1000,3,0x12345678,0x1003)
    return format_info, (
        PreparedFlashImage(image,identity,1),
        PreparedRamImage(image,0x1000,3,0x12345678),
        PreparedServiceImage(image,0x2000,0x2010,0x2020,3,0x12345678,1),
    )


@pytest.mark.parametrize("index,expected_type",[(0,PreparedFlashImage),(1,PreparedRamImage),(2,PreparedServiceImage)])
def test_prepared_image_payload_types_and_derived_firmware_fields_are_preserved(index,expected_type) -> None:
    source,images=_prepared_images(); original=images[index]; result=TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"ok","ok",payload=original); stored=result.payload
    source["metadata"]["labels"].append("changed")
    assert type(stored) is expected_type and type(stored.image) is FirmwareImage
    assert type(stored.image.blocks[0]) is FirmwareBlock and type(stored.image.address_ranges[0]) is AddressRange
    assert stored.image.total_words==3 and stored.image.address_ranges==(AddressRange(0x1000,0x1003),)
    assert stored.image.format_info["metadata"]["labels"]==("original",)
    with pytest.raises(TypeError): stored.image.format_info["new"]=1


def test_prepared_flash_identity_type_is_preserved() -> None:
    _,images=_prepared_images(); stored=TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"ok","ok",payload=images[0]).payload
    assert type(stored.identity) is ImageIdentity


@pytest.mark.parametrize("unsafe",[Lock(),lambda:None,object()])
def test_frozen_dataclass_with_runtime_resource_is_rejected(unsafe) -> None:
    @dataclass(frozen=True)
    class Unsafe:
        value: object
    with pytest.raises(TypeError): TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"ok","ok",payload=Unsafe(unsafe))


@pytest.mark.parametrize("kind",["mapping","list"])
def test_cyclic_payload_is_rejected_as_type_error(kind) -> None:
    payload={}
    if kind=="mapping": payload["self"]=payload
    else:
        items=[]; items.append(items); payload["items"]=items
    with pytest.raises(TypeError,match="cyclic"): TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"ok","ok",payload=payload)


def test_progress_event_raw_event_remains_typed_and_is_recursively_frozen() -> None:
    from bootloader_upgrade_tool.gui.runtime_models import TaskProgressUpdate, TaskStepState
    details={"chunks":[{"words":2}]}; event=ProgressEvent("program","CPU1","write","writing",2,4,2,details)
    update=TaskProgressUpdate("id","write",TaskStepState.PROGRESS,"write","writing",2,4,ProgressMode.DETERMINATE,event)
    details["chunks"][0]["words"]=9
    assert isinstance(update.raw_event,ProgressEvent) and update.raw_event.details["chunks"][0]["words"]==2
    with pytest.raises(TypeError): update.raw_event.details["new"]=1


def test_progress_raw_event_rejects_cycles_and_runtime_resources() -> None:
    from bootloader_upgrade_tool.gui.runtime_models import TaskProgressUpdate, TaskStepState
    cycle={}; cycle["self"]=cycle
    for raw in (cycle,Lock()):
        with pytest.raises(TypeError): TaskProgressUpdate("id","s",TaskStepState.STARTED,"s","s",raw_event=raw)


def test_cancelled_result_cannot_release_connection() -> None:
    from bootloader_upgrade_tool.gui.runtime_models import TaskCompletionAction
    with pytest.raises(ValueError): TaskExecutionResult("id",TaskFinalStatus.CANCELLED,"cancel","cancel",completion_action=TaskCompletionAction.RELEASE_CONNECTION,cancel_requested=True)


def test_normalized_operation_result_remains_serializable() -> None:
    operation=OperationResult(True,"program","CPU1","done",{"counts":{"words":2}},details={"items":[1,2]})
    stored=TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"ok","ok",step_results=(operation,)).step_results[0]
    assert operation_result_to_dict(stored)=={"ok":True,"operation":"program","target":"CPU1","stage":"done","summary":{"counts":{"words":2}},"details":{"items":[1,2]},"service":None,"warning":None,"error":None}


def test_callable_frozen_dataclass_and_dataclass_class_are_rejected() -> None:
    @dataclass(frozen=True)
    class CallablePayload:
        value:int=1
        def __call__(self):return self.value
    @dataclass(frozen=True)
    class PayloadClass:
        value:int=1
    for payload in (CallablePayload(),PayloadClass):
        with pytest.raises(TypeError): TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"ok","ok",payload=payload)


def test_cyclic_gui_details_raise_type_error() -> None:
    from bootloader_upgrade_tool.gui.runtime_models import GuiTaskWarning
    details={}; details["self"]=details
    with pytest.raises(TypeError,match="cyclic"): GuiTaskWarning("W","warning","test",details)


def test_worker_emits_one_result_and_finished() -> None:
    worker = TaskWorker("id", 2, _Job(), CancellationToken(), True)
    results, finished = [], []
    worker.resultReady.connect(results.append)
    worker.workFinished.connect(finished.append)
    worker.run()
    assert isinstance(results[0], WorkerResultMessage)
    assert isinstance(finished[0], WorkerFinishedMessage)
