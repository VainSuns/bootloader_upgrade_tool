from PySide6.QtWidgets import QApplication, QWidget

from bootloader_upgrade_tool.gui.runtime_models import *
from bootloader_upgrade_tool.gui.widgets.task_dialog import TaskDialog

APP=QApplication.instance() or QApplication([])

def _state(cancellable=True):
    plan=TaskPlan("id","Task",(TaskStepPlan("s","Step",ProgressMode.INDETERMINATE),),TaskConnectionRequirement.NONE,cancellable,CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT)
    return TaskState("id",plan,TaskPhase.RUNNING)

def test_active_dialog_requests_cancel_once_and_stays_open():
    parent=QWidget(); dialog=TaskDialog(_state(),parent); seen=[]; dialog.cancelRequested.connect(seen.append); dialog.open(); APP.processEvents()
    dialog.reject(); dialog.reject()
    assert seen==["id"] and dialog.isVisible()
