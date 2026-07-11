from datetime import datetime, timezone

from bootloader_upgrade_tool.gui.controller import GuiController
from bootloader_upgrade_tool.gui.runtime_models import *
from gui_runtime_fakes import FakePort, FakeRequest
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
    payload = ConnectionInfo("c", "SCI", "COM1", datetime.now(timezone.utc)) if kind == "connect" else None
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
