from PySide6.QtWidgets import QApplication, QWidget, QPushButton
from PySide6.QtTest import QTest
from dataclasses import replace
from datetime import datetime, timezone
import pytest

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

def test_decision_close_does_not_cancel_and_identical_state_keeps_actions_disabled():
    state=replace(_state(),phase=TaskPhase.FINISHED,disposition_state=TaskDispositionState.AWAITING_DISCONNECT_DECISION,available_actions=(TaskDialogAction.DISCONNECT,TaskDialogAction.KEEP_CONNECTION))
    parent=QWidget(); dialog=TaskDialog(state,parent); cancelled=[]; actions=[]; dialog.cancelRequested.connect(cancelled.append); dialog.actionRequested.connect(lambda *x:actions.append(x)); dialog.open(); APP.processEvents()
    buttons=dialog.actionBox.buttons(); buttons[0].click(); dialog.apply_state(state); dialog.reject()
    assert len(actions)==1 and not cancelled and all(not b.isEnabled() for b in dialog.actionBox.buttons())

def test_result_warning_and_details_are_presented():
    warning=GuiTaskWarning("WARN","warning headline","cleanup",{"reason":"busy"})
    result=TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"summary text","result message",step_results=("step evidence",),warning=warning)
    state=replace(_state(),phase=TaskPhase.FINISHED,disposition_state=TaskDispositionState.COMPLETE,close_allowed=True,result=result,finished_at=datetime.now(timezone.utc))
    parent=QWidget(); dialog=TaskDialog(state,parent)
    text=" ".join(label.text() for label in dialog.findChildren(type(dialog.messageLabel)))
    assert "summary text" in text and "result message" in text and "warning headline" in text
    assert "step evidence" in dialog.detailsText.toPlainText() and "busy" in dialog.detailsText.toPlainText()

def test_single_and_multi_progress_bar_visibility_and_modes():
    parent1=QWidget(); single=TaskDialog(_state(),parent1); assert not single.overallProgressBar.isVisible() and single.stepProgressBar.maximum()==0
    plan=replace(_state().plan,steps=(_state().plan.steps[0],TaskStepPlan("s2","Step 2",ProgressMode.DETERMINATE)))
    state=replace(_state(),plan=plan,step_progress_mode=ProgressMode.DETERMINATE,step_current=2,step_total=5)
    parent2=QWidget(); multi=TaskDialog(state,parent2); multi.show(); APP.processEvents()
    assert multi.overallProgressBar.isVisible() and multi.stepProgressBar.maximum()==5 and multi.stepProgressBar.value()==2

def test_clean_success_auto_closes_but_warning_requires_manual_close():
    clean=TaskExecutionResult("id",TaskFinalStatus.SUCCEEDED,"done","done")
    state=replace(_state(),phase=TaskPhase.FINISHED,disposition_state=TaskDispositionState.COMPLETE,close_allowed=True,auto_close_delay_ms=20,result=clean)
    parent=QWidget(); dialog=TaskDialog(state,parent); dialog.open(); QTest.qWait(40); assert not dialog.isVisible()
    warned=replace(clean,warning=GuiTaskWarning("W","warning","test"))
    parent2=QWidget(); dialog2=TaskDialog(replace(state,result=warned),parent2); dialog2.open(); QTest.qWait(40); assert dialog2.isVisible()

def test_task_id_mismatch_is_rejected():
    parent=QWidget(); dialog=TaskDialog(_state(),parent)
    with pytest.raises(ValueError): dialog.apply_state(replace(_state(),task_id="other",plan=replace(_state().plan,task_id="other")))
