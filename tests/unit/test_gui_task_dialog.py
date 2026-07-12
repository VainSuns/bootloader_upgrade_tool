from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QProgressBar, QWidget

from bootloader_upgrade_tool.gui.layout_metrics import (
    TASK_DIALOG_CARD_MAXIMUM_WIDTH,
    TASK_DIALOG_CARD_MINIMUM_WIDTH,
)
from bootloader_upgrade_tool.gui.runtime_models import (
    CompletionPolicy,
    ErrorDisposition,
    GuiRuntimeError,
    GuiTaskWarning,
    ProgressMode,
    TaskConnectionRequirement,
    TaskDialogAction,
    TaskDispositionState,
    TaskExecutionResult,
    TaskFinalStatus,
    TaskPhase,
    TaskPlan,
    TaskState,
    TaskStepPlan,
)
from bootloader_upgrade_tool.gui.widgets.task_dialog import TaskDialog

APP = QApplication.instance() or QApplication([])


def _state(cancellable: bool = True) -> TaskState:
    plan = TaskPlan(
        "id",
        "Connect SCI / RS232",
        (TaskStepPlan("s", "Opening SCI / RS232", ProgressMode.INDETERMINATE),),
        TaskConnectionRequirement.NONE,
        cancellable,
        CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT,
    )
    return TaskState(
        "id",
        plan,
        TaskPhase.RUNNING,
        current_step_title="Opening SCI / RS232",
        message="Opening SCI / RS232",
    )


def _shown_parent(width: int = 1000, height: int = 700) -> QWidget:
    parent = QWidget()
    parent.resize(width, height)
    parent.show()
    APP.processEvents()
    return parent


def test_dialog_is_frameless_window_modal_overlay_with_centered_card() -> None:
    parent = _shown_parent()
    dialog = TaskDialog(_state(), parent)
    dialog.open()
    APP.processEvents()

    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.windowModality() == Qt.WindowModality.WindowModal
    assert dialog.isModal()
    assert dialog.size() == parent.size()
    assert dialog.pos() == parent.mapToGlobal(QPoint(0, 0))
    assert TASK_DIALOG_CARD_MINIMUM_WIDTH <= dialog.card.width()
    assert dialog.card.width() <= TASK_DIALOG_CARD_MAXIMUM_WIDTH

    dialog_center = dialog.mapToGlobal(dialog.rect().center())
    card_center = dialog.card.mapToGlobal(dialog.card.rect().center())
    assert abs(dialog_center.x() - card_center.x()) <= 2
    assert abs(dialog_center.y() - card_center.y()) <= 2
    assert dialog.titleLabel.text() == "Connect SCI / RS232"
    assert dialog.closeButton.objectName() == "taskDialogCloseButton"

    dialog.accept()
    parent.close()


def test_header_indicator_is_centered_with_title_and_animates_only_while_busy() -> None:
    parent = _shown_parent()
    dialog = TaskDialog(_state(), parent)
    dialog.open()
    APP.processEvents()

    centers = (
        dialog.titleIcon.geometry().center().y(),
        dialog.titleLabel.geometry().center().y(),
        dialog.closeButton.geometry().center().y(),
    )
    assert max(centers) - min(centers) <= 1
    assert dialog._busy_indicator_timer.isActive()

    initial_key = dialog.titleIcon.pixmap().cacheKey()
    QTest.qWait(100)
    assert dialog.titleIcon.pixmap().cacheKey() != initial_key

    result = TaskExecutionResult(
        "id",
        TaskFinalStatus.SUCCEEDED,
        "Connected",
        "Connection established.",
    )
    finished = replace(
        _state(),
        phase=TaskPhase.FINISHED,
        disposition_state=TaskDispositionState.COMPLETE,
        close_allowed=True,
        result=result,
        finished_at=datetime.now(timezone.utc),
    )
    dialog.apply_state(finished)
    assert not dialog._busy_indicator_timer.isActive()
    assert dialog.card.property("state") == "success"

    dialog.accept()
    parent.close()


def test_active_dialog_close_control_requests_cancel_once_and_stays_open() -> None:
    parent = _shown_parent()
    dialog = TaskDialog(_state(), parent)
    seen: list[str] = []
    dialog.cancelRequested.connect(seen.append)
    dialog.open()
    APP.processEvents()

    dialog.closeButton.click()
    dialog.closeButton.click()

    assert seen == ["id"]
    assert dialog.isVisible()
    assert not dialog.closeButton.isEnabled()

    dialog.accept()
    parent.close()


def test_decision_close_does_not_cancel_and_identical_state_keeps_actions_disabled() -> None:
    state = replace(
        _state(),
        phase=TaskPhase.FINISHED,
        disposition_state=TaskDispositionState.AWAITING_DISCONNECT_DECISION,
        available_actions=(
            TaskDialogAction.DISCONNECT,
            TaskDialogAction.KEEP_CONNECTION,
        ),
    )
    parent = _shown_parent()
    dialog = TaskDialog(state, parent)
    cancelled: list[str] = []
    actions: list[tuple[str, object]] = []
    dialog.cancelRequested.connect(cancelled.append)
    dialog.actionRequested.connect(lambda *args: actions.append(args))
    dialog.open()
    APP.processEvents()

    buttons = dialog.actionBox.buttons()
    buttons[0].click()
    dialog.apply_state(state)
    dialog.reject()

    assert len(actions) == 1
    assert not cancelled
    assert all(not button.isEnabled() for button in dialog.actionBox.buttons())

    dialog.accept()
    parent.close()


def test_result_warning_and_details_use_warning_presentation() -> None:
    warning = GuiTaskWarning(
        "WARN",
        "Connection state requires review",
        "cleanup",
        {"reason": "busy"},
    )
    result = TaskExecutionResult(
        "id",
        TaskFinalStatus.SUCCEEDED,
        "Connected with warning",
        "The connection completed.",
        step_results=("step evidence",),
        warning=warning,
    )
    state = replace(
        _state(),
        phase=TaskPhase.FINISHED,
        disposition_state=TaskDispositionState.COMPLETE,
        close_allowed=True,
        result=result,
        finished_at=datetime.now(timezone.utc),
    )
    parent = _shown_parent()
    dialog = TaskDialog(state, parent)
    dialog.open()
    APP.processEvents()

    assert dialog.summaryLabel.text() == "Connected with warning"
    assert dialog.messageLabel.text() == "The connection completed."
    assert dialog.alertLabel.text() == "Connection state requires review"
    assert dialog.alertFrame.isVisible()
    assert dialog.alertFrame.property("state") == "warning"
    assert dialog.card.property("state") == "warning"
    assert "step evidence" in dialog.detailsText.toPlainText()
    assert "busy" in dialog.detailsText.toPlainText()

    dialog.detailsButton.setChecked(True)
    APP.processEvents()
    assert dialog.detailsText.isVisible()
    assert dialog.detailsButton.icon().isNull() is False

    dialog.accept()
    parent.close()


def test_failure_message_is_not_duplicated_in_alert_banner() -> None:
    error = GuiRuntimeError(
        "AUTOBAUD_TIMEOUT",
        "SCI autobaud handshake timed out",
        "autobaud",
        ErrorDisposition.SHOW_ONLY,
        task_id="id",
        details={"cleanup_pending": False},
    )
    result = TaskExecutionResult(
        "id",
        TaskFinalStatus.FAILED,
        "Connection failed",
        "SCI autobaud handshake timed out",
        error=error,
    )
    state = replace(
        _state(),
        phase=TaskPhase.FINISHED,
        disposition_state=TaskDispositionState.COMPLETE,
        close_allowed=True,
        result=result,
        finished_at=datetime.now(timezone.utc),
    )
    parent = _shown_parent()
    dialog = TaskDialog(state, parent)
    dialog.open()
    APP.processEvents()

    assert dialog.summaryLabel.text() == "Connection failed"
    assert dialog.messageLabel.text() == "SCI autobaud handshake timed out"
    assert not dialog.alertFrame.isVisible()
    assert dialog.card.property("state") == "error"
    assert "cleanup_pending" in dialog.detailsText.toPlainText()

    dialog.accept()
    parent.close()


def test_single_and_multi_progress_bar_visibility_and_modes() -> None:
    parent1 = _shown_parent()
    single = TaskDialog(_state(), parent1)
    single.open()
    APP.processEvents()
    assert not single.overallProgressBar.isVisible()
    assert not single.overallLabel.isVisible()
    assert single.stepLabel.isVisible() and single.stepProgressBar.isVisible()
    assert single.stepProgressBar.maximum() == 0
    assert single.stepLabel.text() == "Opening SCI / RS232"

    plan = replace(
        _state().plan,
        steps=(
            _state().plan.steps[0],
            TaskStepPlan("s2", "Step 2", ProgressMode.DETERMINATE),
        ),
    )
    state = replace(
        _state(),
        plan=plan,
        current_step_title="Opening SCI / RS232",
        step_progress_mode=ProgressMode.DETERMINATE,
        step_current=2,
        step_total=5,
    )
    parent2 = _shown_parent()
    multi = TaskDialog(state, parent2)
    multi.open()
    APP.processEvents()

    assert not multi.overallLabel.isVisible()
    assert not multi.overallProgressBar.isVisible()
    assert sum(bar.isVisible() for bar in multi.findChildren(QProgressBar)) == 1
    assert multi.stepLabel.text() == "Opening SCI / RS232"
    assert multi.stepProgressBar.maximum() == 5
    assert multi.stepProgressBar.value() == 2

    multi.apply_state(replace(state, current_step_title="Step 2", step_current=3))
    assert multi.stepLabel.text() == "Step 2"
    assert multi.stepProgressBar.value() == 3
    assert not multi.overallProgressBar.isVisible()

    single.accept()
    multi.accept()
    parent1.close()
    parent2.close()


def test_progress_title_falls_back_to_plan_title() -> None:
    parent = _shown_parent()
    dialog = TaskDialog(replace(_state(), current_step_title=""), parent)
    dialog.open()
    APP.processEvents()
    assert dialog.stepLabel.text() == "Connect SCI / RS232"
    assert not dialog.overallProgressBar.isVisible()
    dialog.accept()
    parent.close()


@pytest.mark.parametrize("status", [TaskFinalStatus.SUCCEEDED, TaskFinalStatus.FAILED])
def test_final_states_never_show_overall_progress(status) -> None:
    error = (
        GuiRuntimeError("FAILED", "Finished", "test", ErrorDisposition.SHOW_ONLY, "id")
        if status is TaskFinalStatus.FAILED
        else None
    )
    result = TaskExecutionResult("id", status, "Done", "Finished", error=error)
    state = replace(
        _state(),
        phase=TaskPhase.FINISHED,
        disposition_state=TaskDispositionState.COMPLETE,
        close_allowed=True,
        result=result,
    )
    parent = _shown_parent()
    dialog = TaskDialog(state, parent)
    dialog.open()
    APP.processEvents()
    assert not dialog.overallLabel.isVisible()
    assert not dialog.overallProgressBar.isVisible()
    assert dialog.stepProgressBar.isVisible()
    dialog.accept()
    parent.close()


def test_clean_success_auto_closes_but_warning_requires_manual_close() -> None:
    clean = TaskExecutionResult(
        "id",
        TaskFinalStatus.SUCCEEDED,
        "Done",
        "Connection established.",
    )
    state = replace(
        _state(),
        phase=TaskPhase.FINISHED,
        disposition_state=TaskDispositionState.COMPLETE,
        close_allowed=True,
        auto_close_delay_ms=20,
        result=clean,
    )
    parent = _shown_parent()
    dialog = TaskDialog(state, parent)
    dialog.open()
    QTest.qWait(40)
    assert not dialog.isVisible()

    warned = replace(
        clean,
        warning=GuiTaskWarning("W", "warning", "test"),
    )
    parent2 = _shown_parent()
    dialog2 = TaskDialog(replace(state, result=warned), parent2)
    dialog2.open()
    QTest.qWait(40)
    assert dialog2.isVisible()

    dialog2.accept()
    parent.close()
    parent2.close()


def test_task_id_mismatch_is_rejected() -> None:
    parent = QWidget()
    dialog = TaskDialog(_state(), parent)
    with pytest.raises(ValueError):
        dialog.apply_state(
            replace(
                _state(),
                task_id="other",
                plan=replace(_state().plan, task_id="other"),
            )
        )
