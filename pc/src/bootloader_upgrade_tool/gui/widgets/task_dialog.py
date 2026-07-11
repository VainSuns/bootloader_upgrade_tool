from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..runtime_models import ProgressMode, TaskDialogAction, TaskPhase, TaskState

_ACTION_LABELS={
    TaskDialogAction.DISCONNECT:"Disconnect", TaskDialogAction.KEEP_CONNECTION:"Keep Connection",
    TaskDialogAction.RETRY_CLEANUP:"Retry Cleanup", TaskDialogAction.FORCE_EXIT:"Force Exit",
}

class TaskDialog(QDialog):
    cancelRequested=Signal(str); actionRequested=Signal(str,object)

    def __init__(self,initial_state:TaskState,parent:QWidget):
        if parent is None: raise ValueError("TaskDialog requires a parent")
        super().__init__(parent); self._task_id=initial_state.task_id; self._state=initial_state; self._cancel_emitted=False; self._action_clicked=False
        self.setWindowModality(Qt.WindowModality.WindowModal); self.setModal(True); self.setWindowTitle(initial_state.plan.title)
        layout=QVBoxLayout(self); self.messageLabel=QLabel(self); layout.addWidget(self.messageLabel)
        self.overallLabel=QLabel("Overall",self); self.overallProgressBar=QProgressBar(self); layout.addWidget(self.overallLabel); layout.addWidget(self.overallProgressBar)
        self.stepLabel=QLabel("Current Step",self); self.stepProgressBar=QProgressBar(self); layout.addWidget(self.stepLabel); layout.addWidget(self.stepProgressBar)
        self.actionBox=QDialogButtonBox(self); layout.addWidget(self.actionBox)
        self._timer=QTimer(self); self._timer.setSingleShot(True); self._timer.timeout.connect(self.accept)
        self.apply_state(initial_state)

    def apply_state(self,state:TaskState)->None:
        if state.task_id!=self._task_id: raise ValueError("Task ID mismatch")
        changed=state!=self._state; self._state=state; self._action_clicked=False
        self.messageLabel.setText(state.message)
        multi=len(state.plan.steps)>1; self.overallLabel.setVisible(multi); self.overallProgressBar.setVisible(multi)
        if multi: self._set_progress(self.overallProgressBar,state.overall_current,state.overall_total,ProgressMode.DETERMINATE)
        self._set_progress(self.stepProgressBar,state.step_current,state.step_total,state.step_progress_mode)
        while button:=self.actionBox.buttons()[0] if self.actionBox.buttons() else None: self.actionBox.removeButton(button); button.deleteLater()
        for action in state.available_actions:
            button=QPushButton(_ACTION_LABELS[action],self); button.setProperty("taskAction",action.name); button.clicked.connect(partial(self._action,action)); self.actionBox.addButton(button,QDialogButtonBox.ButtonRole.ActionRole)
        if state.plan.cancellable and state.phase in (TaskPhase.PENDING,TaskPhase.RUNNING,TaskPhase.CANCELLING) and not state.cancel_requested:
            button=QPushButton("Cancel",self); button.setProperty("taskAction","CANCEL"); button.clicked.connect(self._request_cancel); self.actionBox.addButton(button,QDialogButtonBox.ButtonRole.RejectRole)
        elif state.close_allowed:
            button=self.actionBox.addButton(QDialogButtonBox.StandardButton.Close); button.clicked.connect(self.accept)
        self._timer.stop()
        if state.close_allowed and state.auto_close_delay_ms is not None: self._timer.start(state.auto_close_delay_ms)

    @staticmethod
    def _set_progress(bar,current,total,mode):
        if mode is ProgressMode.INDETERMINATE: bar.setRange(0,0)
        else: bar.setRange(0,max(total,1)); bar.setValue(current)

    def _request_cancel(self):
        if not self._cancel_emitted and self._state.plan.cancellable and not self._state.cancel_requested:
            self._cancel_emitted=True; self.cancelRequested.emit(self._task_id)
            for button in self.actionBox.buttons(): button.setEnabled(False)

    def _action(self,action):
        if self._action_clicked:return
        self._action_clicked=True
        for button in self.actionBox.buttons(): button.setEnabled(False)
        self.actionRequested.emit(self._task_id,action)

    def reject(self)->None:
        if self._state.close_allowed: super().reject()
        else:self._request_cancel()
    def closeEvent(self,event:QCloseEvent)->None:
        if self._state.close_allowed: super().closeEvent(event)
        else: self._request_cancel(); event.ignore()
