"""Window-modal task presentation used by the Phase 11 GUI runtime.

The task dialog is rendered as a frameless overlay constrained to the main
window client area.  It keeps the controller-facing signals and state handling
unchanged while presenting progress, warnings, errors, details, and actions in
an application-owned visual shell.
"""

from __future__ import annotations

from functools import partial
from pprint import pformat

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QPainter, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import (
    TASK_DIALOG_CARD_CONTENT_MARGINS,
    TASK_DIALOG_CARD_MAXIMUM_WIDTH,
    TASK_DIALOG_CARD_MINIMUM_WIDTH,
    TASK_DIALOG_CLOSE_BUTTON_SIZE,
    TASK_DIALOG_DETAILS_MAXIMUM_HEIGHT,
    TASK_DIALOG_DETAILS_MINIMUM_HEIGHT,
    TASK_DIALOG_OVERLAY_MARGIN,
    TASK_DIALOG_SECTION_SPACING,
    TASK_DIALOG_TITLE_ICON_SIZE,
)
from ..runtime_models import (
    ProgressMode,
    TaskDialogAction,
    TaskFinalStatus,
    TaskPhase,
    TaskState,
)
from ..theme_tokens import THEME_TOKENS
from ..ui_state import set_ui_state, set_ui_variant

_ACTION_LABELS = {
    TaskDialogAction.DISCONNECT: "Disconnect",
    TaskDialogAction.KEEP_CONNECTION: "Keep Connection",
    TaskDialogAction.RETRY_CLEANUP: "Retry Cleanup",
    TaskDialogAction.FORCE_EXIT: "Force Exit",
}

_ACTION_VARIANTS = {
    TaskDialogAction.DISCONNECT: "dangerGhost",
    TaskDialogAction.KEEP_CONNECTION: "primary",
    TaskDialogAction.RETRY_CLEANUP: "primary",
    TaskDialogAction.FORCE_EXIT: "danger",
}

_ACTIVE_PHASES = (TaskPhase.PENDING, TaskPhase.RUNNING, TaskPhase.CANCELLING)


class TaskDialog(QDialog):
    """Application-owned modal overlay for one controller task."""

    cancelRequested = Signal(str)
    actionRequested = Signal(str, object)

    def __init__(self, initial_state: TaskState, parent: QWidget) -> None:
        if parent is None:
            raise ValueError("TaskDialog requires a parent")

        super().__init__(parent)
        self._task_id = initial_state.task_id
        self._state = initial_state
        self._cancel_emitted = False
        self._action_clicked = False
        self._overlay_host = self._resolve_overlay_host(parent)
        self._watched_widgets: list[QWidget] = []
        self._icon_manager = getattr(parent, "icon_manager", None) or IconManager()
        self._busy_indicator_angle = 0
        self._busy_indicator_source = QPixmap()
        self._busy_indicator_enabled = False

        self.setObjectName("taskDialogOverlay")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.setWindowTitle(initial_state.plan.title)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setSizeGripEnabled(False)

        self._build_layout(initial_state)
        self._install_geometry_watchers(parent)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.accept)

        self._busy_indicator_timer = QTimer(self)
        self._busy_indicator_timer.setInterval(80)
        self._busy_indicator_timer.timeout.connect(self._advance_busy_indicator)

        self.apply_state(initial_state)
        self._sync_overlay_geometry()

    def _build_layout(self, initial_state: TaskState) -> None:
        overlay_layout = QVBoxLayout(self)
        overlay_layout.setContentsMargins(
            TASK_DIALOG_OVERLAY_MARGIN,
            TASK_DIALOG_OVERLAY_MARGIN,
            TASK_DIALOG_OVERLAY_MARGIN,
            TASK_DIALOG_OVERLAY_MARGIN,
        )
        overlay_layout.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("taskDialogCard")
        self.card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        overlay_layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow_color = QColor(THEME_TOKENS["TEXT_PRIMARY"])
        shadow_color.setAlpha(72)
        shadow.setColor(shadow_color)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(*TASK_DIALOG_CARD_CONTENT_MARGINS)
        card_layout.setSpacing(TASK_DIALOG_SECTION_SPACING)

        header = QFrame(self.card)
        header.setObjectName("taskDialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.titleIcon = QLabel(header)
        self.titleIcon.setObjectName("taskDialogTitleIcon")
        self.titleIcon.setFixedSize(*TASK_DIALOG_CLOSE_BUTTON_SIZE)
        self.titleIcon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.titleIcon, 0, Qt.AlignmentFlag.AlignVCenter)

        self.titleLabel = QLabel(initial_state.plan.title, header)
        self.titleLabel.setObjectName("taskDialogTitleLabel")
        self.titleLabel.setWordWrap(True)
        self.titleLabel.setMinimumHeight(TASK_DIALOG_CLOSE_BUTTON_SIZE[1])
        self.titleLabel.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.titleLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header_layout.addWidget(self.titleLabel, 1, Qt.AlignmentFlag.AlignVCenter)

        self.closeButton = QToolButton(header)
        self.closeButton.setObjectName("taskDialogCloseButton")
        self.closeButton.setAccessibleName("Close or cancel task")
        self.closeButton.setToolTip("Close or cancel task")
        self.closeButton.setIcon(
            self._icon_manager.icon("common.close", size=16)
        )
        self.closeButton.setIconSize(QSize(16, 16))
        self.closeButton.setFixedSize(*TASK_DIALOG_CLOSE_BUTTON_SIZE)
        self.closeButton.clicked.connect(self.reject)
        header_layout.addWidget(self.closeButton, 0, Qt.AlignmentFlag.AlignVCenter)
        card_layout.addWidget(header)

        self.summaryLabel = QLabel(self.card)
        self.summaryLabel.setObjectName("taskDialogSummaryLabel")
        self.summaryLabel.setWordWrap(True)
        self.summaryLabel.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        card_layout.addWidget(self.summaryLabel)

        self.messageLabel = QLabel(self.card)
        self.messageLabel.setObjectName("taskDialogMessageLabel")
        self.messageLabel.setWordWrap(True)
        self.messageLabel.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        card_layout.addWidget(self.messageLabel)

        self.alertFrame = QFrame(self.card)
        self.alertFrame.setObjectName("taskDialogAlertFrame")
        alert_layout = QHBoxLayout(self.alertFrame)
        alert_layout.setContentsMargins(12, 10, 12, 10)
        alert_layout.setSpacing(10)

        self.alertIcon = QLabel(self.alertFrame)
        self.alertIcon.setObjectName("taskDialogAlertIcon")
        self.alertIcon.setFixedSize(18, 18)
        self.alertIcon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        alert_layout.addWidget(self.alertIcon, 0, Qt.AlignmentFlag.AlignTop)

        self.alertLabel = QLabel(self.alertFrame)
        self.alertLabel.setObjectName("taskDialogAlertLabel")
        self.alertLabel.setWordWrap(True)
        self.alertLabel.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        alert_layout.addWidget(self.alertLabel, 1)
        card_layout.addWidget(self.alertFrame)

        self.progressFrame = QFrame(self.card)
        self.progressFrame.setObjectName("taskDialogProgressFrame")
        progress_layout = QGridLayout(self.progressFrame)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setHorizontalSpacing(12)
        progress_layout.setVerticalSpacing(8)
        progress_layout.setColumnStretch(0, 1)

        self.overallLabel = QLabel("Overall", self.progressFrame)
        self.overallLabel.setObjectName("taskDialogOverallLabel")
        progress_layout.addWidget(self.overallLabel, 0, 0)

        self.overallProgressBar = QProgressBar(self.progressFrame)
        self.overallProgressBar.setObjectName("taskDialogOverallProgressBar")
        self.overallProgressBar.setProperty("dialogProgress", True)
        self.overallProgressBar.setTextVisible(False)
        progress_layout.addWidget(self.overallProgressBar, 1, 0)

        self.stepLabel = QLabel("Current Step", self.progressFrame)
        self.stepLabel.setObjectName("taskDialogStepLabel")
        progress_layout.addWidget(self.stepLabel, 2, 0)

        self.stepProgressBar = QProgressBar(self.progressFrame)
        self.stepProgressBar.setObjectName("taskDialogStepProgressBar")
        self.stepProgressBar.setProperty("dialogProgress", True)
        self.stepProgressBar.setTextVisible(False)
        progress_layout.addWidget(self.stepProgressBar, 3, 0)
        card_layout.addWidget(self.progressFrame)

        self.detailsButton = QToolButton(self.card)
        self.detailsButton.setObjectName("taskDialogDetailsButton")
        self.detailsButton.setText("Details")
        self.detailsButton.setCheckable(True)
        self.detailsButton.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.detailsButton.setIcon(
            self._icon_manager.icon("common.expand_down", size=16)
        )
        self.detailsButton.setIconSize(QSize(16, 16))
        self.detailsButton.toggled.connect(self._set_details_visible)
        card_layout.addWidget(
            self.detailsButton,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )

        self.detailsText = QPlainTextEdit(self.card)
        self.detailsText.setObjectName("taskDialogDetailsText")
        self.detailsText.setReadOnly(True)
        self.detailsText.setUndoRedoEnabled(False)
        self.detailsText.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.detailsText.setMinimumHeight(TASK_DIALOG_DETAILS_MINIMUM_HEIGHT)
        self.detailsText.setMaximumHeight(TASK_DIALOG_DETAILS_MAXIMUM_HEIGHT)
        self.detailsText.setVisible(False)
        card_layout.addWidget(self.detailsText)

        self.footer = QFrame(self.card)
        self.footer.setObjectName("taskDialogFooter")
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(0, 14, 0, 0)
        footer_layout.setSpacing(8)
        footer_layout.addStretch(1)

        self.actionBox = QDialogButtonBox(self.footer)
        self.actionBox.setObjectName("taskDialogActionBox")
        footer_layout.addWidget(self.actionBox)
        card_layout.addWidget(self.footer)

    def apply_state(self, state: TaskState) -> None:
        if state.task_id != self._task_id:
            raise ValueError("Task ID mismatch")

        changed = state != self._state
        self._state = state
        if changed:
            self._action_clicked = False

        result = state.result
        summary_text = result.summary if result else ""
        message_text = result.message if result else state.message
        alert_text = (
            result.warning.message
            if result and result.warning
            else result.error.message
            if result and result.error
            else ""
        )

        self.summaryLabel.setText(summary_text)
        self.summaryLabel.setVisible(bool(summary_text))
        self.messageLabel.setText(message_text)
        self.messageLabel.setVisible(bool(message_text))

        # The result message and error message frequently carry the same text.
        # Present it once in the primary message area and reserve the alert banner
        # for additional warning/error context.
        show_alert = bool(
            alert_text
            and alert_text not in {summary_text, message_text}
        )
        self.alertLabel.setText(alert_text if show_alert else "")
        self.alertFrame.setVisible(show_alert)

        details = self._details_sections(state)
        self.detailsText.setPlainText("\n\n".join(details))
        self.detailsButton.setVisible(bool(details))
        if not details:
            self.detailsButton.setChecked(False)
            self.detailsText.setVisible(False)

        multi_step = len(state.plan.steps) > 1
        self.overallLabel.setVisible(multi_step)
        self.overallProgressBar.setVisible(multi_step)
        if multi_step:
            self._set_progress(
                self.overallProgressBar,
                state.overall_current,
                state.overall_total,
                ProgressMode.DETERMINATE,
            )

        self.stepLabel.setText(state.current_step_title or "Current Step")
        self._set_progress(
            self.stepProgressBar,
            state.step_current,
            state.step_total,
            state.step_progress_mode,
        )

        visual_state = self._visual_state(state)
        self._apply_visual_state(visual_state)
        self._rebuild_action_buttons(state)

        self.closeButton.setEnabled(
            state.close_allowed
            or (
                state.plan.cancellable
                and state.phase in _ACTIVE_PHASES
                and not state.cancel_requested
            )
        )

        self._timer.stop()
        clean = (
            result is not None
            and result.status is TaskFinalStatus.SUCCEEDED
            and not result.warning
            and not result.error
        )
        if (
            state.close_allowed
            and state.auto_close_delay_ms is not None
            and clean
        ):
            self._timer.start(state.auto_close_delay_ms)

        self.card.adjustSize()
        self._sync_overlay_geometry()

    @staticmethod
    def _set_progress(
        bar: QProgressBar,
        current: int,
        total: int,
        mode: ProgressMode,
    ) -> None:
        if mode is ProgressMode.INDETERMINATE:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, max(total, 1))
            bar.setValue(current)

    def _request_cancel(self) -> None:
        active = (
            self._state.phase in _ACTIVE_PHASES
            and self._state.disposition_state.name == "NONE"
        )
        if (
            active
            and not self._cancel_emitted
            and self._state.plan.cancellable
            and not self._state.cancel_requested
        ):
            self._cancel_emitted = True
            self.cancelRequested.emit(self._task_id)
            for button in self.actionBox.buttons():
                button.setEnabled(False)
            self.closeButton.setEnabled(False)

    def _action(self, action: TaskDialogAction) -> None:
        if self._action_clicked:
            return
        self._action_clicked = True
        for button in self.actionBox.buttons():
            button.setEnabled(False)
        self.closeButton.setEnabled(False)
        self.actionRequested.emit(self._task_id, action)

    def _rebuild_action_buttons(self, state: TaskState) -> None:
        for button in tuple(self.actionBox.buttons()):
            self.actionBox.removeButton(button)
            button.deleteLater()

        for action in state.available_actions:
            button = QPushButton(_ACTION_LABELS[action], self.actionBox)
            button.setProperty("taskAction", action.name)
            set_ui_variant(button, _ACTION_VARIANTS[action])
            button.clicked.connect(partial(self._action, action))
            button.setEnabled(not self._action_clicked)
            self.actionBox.addButton(
                button,
                QDialogButtonBox.ButtonRole.ActionRole,
            )

        if (
            state.plan.cancellable
            and state.phase in _ACTIVE_PHASES
            and not state.cancel_requested
        ):
            button = QPushButton("Cancel", self.actionBox)
            button.setProperty("taskAction", "CANCEL")
            set_ui_variant(button, "secondary")
            button.clicked.connect(self._request_cancel)
            self.actionBox.addButton(
                button,
                QDialogButtonBox.ButtonRole.RejectRole,
            )
        elif state.close_allowed:
            button = self.actionBox.addButton(
                QDialogButtonBox.StandardButton.Close
            )
            set_ui_variant(button, "primary")
            button.clicked.connect(self.accept)

        self.footer.setVisible(bool(self.actionBox.buttons()))

    def _apply_visual_state(self, visual_state: str) -> None:
        for widget in (
            self.card,
            self.titleIcon,
            self.overallProgressBar,
            self.stepProgressBar,
        ):
            set_ui_state(widget, visual_state)

        result = self._state.result
        alert_state = (
            "warning"
            if result and result.warning
            else "error"
            if result and result.error
            else "neutral"
        )
        set_ui_state(self.alertFrame, alert_state)

        semantic_name = {
            "busy": "program.progress.busy",
            "success": "common.success",
            "warning": "common.warning",
            "error": "common.error",
        }.get(visual_state, "common.information")
        tone = {
            "success": "success",
            "warning": "warning",
            "error": "error",
        }.get(visual_state, "primary" if visual_state == "busy" else "neutral")
        source = self._icon_manager.icon(
            semantic_name,
            tone=tone,
            size=TASK_DIALOG_TITLE_ICON_SIZE,
        ).pixmap(TASK_DIALOG_TITLE_ICON_SIZE, TASK_DIALOG_TITLE_ICON_SIZE)
        self._set_title_indicator(source, animated=visual_state == "busy")

        if self.alertFrame.isVisible():
            alert_semantic = (
                "common.warning" if alert_state == "warning" else "common.error"
            )
            self.alertIcon.setPixmap(
                self._icon_manager.icon(
                    alert_semantic,
                    tone=alert_state,
                    size=18,
                ).pixmap(18, 18)
            )

    def _set_title_indicator(self, source: QPixmap, *, animated: bool) -> None:
        if animated and self._busy_indicator_enabled:
            if not self._busy_indicator_timer.isActive():
                self._busy_indicator_timer.start()
            return

        self._busy_indicator_source = QPixmap(source)
        self._busy_indicator_enabled = animated
        self._busy_indicator_angle = 0
        self._render_title_indicator()
        if animated:
            self._busy_indicator_timer.start()
        else:
            self._busy_indicator_timer.stop()

    def _advance_busy_indicator(self) -> None:
        if not self._busy_indicator_enabled or self._busy_indicator_source.isNull():
            self._busy_indicator_timer.stop()
            return
        self._busy_indicator_angle = (self._busy_indicator_angle + 30) % 360
        self._render_title_indicator()

    def _render_title_indicator(self) -> None:
        source = self._busy_indicator_source
        if source.isNull():
            self.titleIcon.clear()
            return

        canvas = QPixmap(self.titleIcon.size())
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            center_x = canvas.width() / 2
            center_y = canvas.height() / 2
            painter.translate(center_x, center_y)
            if self._busy_indicator_enabled:
                painter.rotate(self._busy_indicator_angle)
            painter.translate(-source.width() / 2, -source.height() / 2)
            painter.drawPixmap(0, 0, source)
        finally:
            painter.end()
        self.titleIcon.setPixmap(canvas)

    @staticmethod
    def _visual_state(state: TaskState) -> str:
        result = state.result
        if result is not None:
            if result.error or result.status is TaskFinalStatus.FAILED:
                return "error"
            if result.warning:
                return "warning"
            if result.status is TaskFinalStatus.SUCCEEDED:
                return "success"
            if result.status in {
                TaskFinalStatus.CANCELLED,
                TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST,
            }:
                return "warning"
        if state.phase is TaskPhase.CANCELLING:
            return "warning"
        if state.phase in {TaskPhase.PENDING, TaskPhase.RUNNING}:
            return "busy"
        return "neutral"

    @staticmethod
    def _details_sections(state: TaskState) -> list[str]:
        result = state.result
        if result is None:
            return []

        sections: list[str] = []
        if result.step_results:
            rendered_steps = "\n".join(
                f"{index}. {pformat(item, width=88, compact=False)}"
                for index, item in enumerate(result.step_results, start=1)
            )
            sections.append(f"Step results:\n{rendered_steps}")
        if result.warning and result.warning.details:
            sections.append(
                "Warning details:\n"
                + pformat(dict(result.warning.details), width=88, sort_dicts=True)
            )
        if result.error and result.error.details:
            sections.append(
                "Error details:\n"
                + pformat(dict(result.error.details), width=88, sort_dicts=True)
            )
        return sections

    def _set_details_visible(self, visible: bool) -> None:
        self.detailsText.setVisible(visible)
        semantic_name = "common.expand_up" if visible else "common.expand_down"
        self.detailsButton.setIcon(
            self._icon_manager.icon(semantic_name, size=16)
        )
        self.card.adjustSize()
        self._sync_overlay_geometry()

    def _install_geometry_watchers(self, parent: QWidget) -> None:
        for widget in (self._overlay_host, parent.window()):
            if widget is not None and widget not in self._watched_widgets:
                widget.installEventFilter(self)
                self._watched_widgets.append(widget)

    @staticmethod
    def _resolve_overlay_host(parent: QWidget) -> QWidget:
        central_widget = getattr(parent, "centralWidget", None)
        if callable(central_widget):
            resolved = central_widget()
            if isinstance(resolved, QWidget):
                return resolved
        return parent

    def _sync_overlay_geometry(self) -> None:
        host = self._overlay_host
        size = host.size()
        if size.width() <= 0 or size.height() <= 0:
            size = host.sizeHint().expandedTo(QSize(640, 480))

        global_top_left = host.mapToGlobal(QPoint(0, 0))
        self.setGeometry(global_top_left.x(), global_top_left.y(), size.width(), size.height())

        available_width = max(320, size.width() - 2 * TASK_DIALOG_OVERLAY_MARGIN)
        card_width = min(TASK_DIALOG_CARD_MAXIMUM_WIDTH, available_width)
        if available_width >= TASK_DIALOG_CARD_MINIMUM_WIDTH:
            card_width = max(TASK_DIALOG_CARD_MINIMUM_WIDTH, card_width)
        self.card.setFixedWidth(card_width)
        self.card.setMaximumHeight(
            max(240, size.height() - 2 * TASK_DIALOG_OVERLAY_MARGIN)
        )

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if watched in self._watched_widgets and event.type() in {
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
        }:
            QTimer.singleShot(0, self._sync_overlay_geometry)
        return super().eventFilter(watched, event)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        self._sync_overlay_geometry()
        super().showEvent(event)
        self.raise_()

    def done(self, result: int) -> None:
        self._busy_indicator_timer.stop()
        super().done(result)

    def reject(self) -> None:
        if self._state.close_allowed:
            super().reject()
        else:
            self._request_cancel()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._state.close_allowed:
            self._busy_indicator_timer.stop()
            super().closeEvent(event)
        else:
            self._request_cancel()
            event.ignore()
