"""Global plain-text Console widget with local-only controls and highlighting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import (
    CONSOLE_HEADER_HEIGHT,
    CONSOLE_ICON_SIZE,
    CONSOLE_TOOL_BUTTON_SIZE,
)
from ..syntax.console_highlighter import ConsoleSyntaxHighlighter
from ..ui_state import UI_LEVELS, set_ui_properties, set_ui_variant
from .status_widgets import StatusBadge

_LEVEL_TEXT = {
    "debug": "DEBUG",
    "info": "INFO",
    "warning": "WARNING",
    "error": "ERROR",
    "success": "SUCCESS",
    "protocol": "PROTOCOL",
}


@dataclass(frozen=True, slots=True)
class ConsoleRecord:
    """One frozen-format Console line before it is appended to the view."""

    timestamp: datetime
    level: str
    source: str
    message: str

    def render(self) -> str:
        if self.level not in UI_LEVELS:
            allowed = ", ".join(sorted(UI_LEVELS))
            raise ValueError(
                f"unknown Console level {self.level!r}; expected: {allowed}"
            )
        source = _single_line(self.source).replace(":", "/").strip() or "GUI"
        message = _single_line(self.message)
        stamp = self.timestamp.strftime("%H:%M:%S.%f")[:-3]
        return f"[{stamp}] [{_LEVEL_TEXT[self.level]}] {source}: {message}"


class ConsoleWidget(QFrame):
    """One reusable global Console panel; splitter sizing remains MainWindow-owned."""

    expandedChanged = Signal(bool)

    def __init__(
        self,
        *,
        icon_manager: IconManager | None = None,
        maximum_block_count: int = 5000,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if maximum_block_count <= 0:
            raise ValueError("maximum_block_count must be greater than zero")

        self.setObjectName("bottomDock")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._icon_manager = icon_manager or IconManager()
        self._expanded = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QFrame(self)
        self.header.setObjectName("bottomDockHeader")
        self.header.setFrameShape(QFrame.Shape.NoFrame)
        self.header.setFixedHeight(CONSOLE_HEADER_HEIGHT)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 0, 6, 0)
        header_layout.setSpacing(6)

        self.icon_label = QLabel(self.header)
        self.icon_label.setObjectName("consoleIcon")
        self.icon_label.setFixedSize(CONSOLE_ICON_SIZE, CONSOLE_ICON_SIZE)
        self.icon_label.setPixmap(
            self._icon_manager.icon("console.panel", size=CONSOLE_ICON_SIZE).pixmap(
                QSize(CONSOLE_ICON_SIZE, CONSOLE_ICON_SIZE)
            )
        )
        header_layout.addWidget(self.icon_label)

        self.title_label = QLabel("Console", self.header)
        self.title_label.setObjectName("consoleTitle")
        header_layout.addWidget(self.title_label)

        self.state_badge = StatusBadge(
            "Idle",
            "idle",
            object_name="consoleStateBadge",
            parent=self.header,
        )
        header_layout.addWidget(self.state_badge)
        header_layout.addStretch(1)

        self.copy_button = self._tool_button(
            "consoleCopyButton",
            "Copy Console",
            "console.copy",
        )
        self.copy_button.clicked.connect(self.copy_all)
        header_layout.addWidget(self.copy_button)

        self.auto_scroll_button = self._tool_button(
            "consoleAutoScrollButton",
            "Auto-scroll Console",
            "console.auto_scroll",
            checkable=True,
            checked=True,
        )
        header_layout.addWidget(self.auto_scroll_button)

        self.clear_button = self._tool_button(
            "consoleClearButton",
            "Clear Console",
            "console.clear",
        )
        self.clear_button.clicked.connect(self.clear)
        header_layout.addWidget(self.clear_button)

        self.expand_button = self._tool_button(
            "consoleExpandButton",
            "Collapse Console",
            "console.collapse",
            checkable=True,
            checked=True,
        )
        self.expand_button.clicked.connect(self.set_expanded)
        header_layout.addWidget(self.expand_button)
        outer.addWidget(self.header)

        self.body = QFrame(self)
        self.body.setObjectName("bottomConsoleBody")
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        set_ui_properties(self.body, uiRole="consolePanel")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.output = QPlainTextEdit(self.body)
        self.output.setObjectName("consoleOutput")
        self.output.setReadOnly(True)
        self.output.setUndoRedoEnabled(False)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setMaximumBlockCount(maximum_block_count)
        body_layout.addWidget(self.output, 1)
        outer.addWidget(self.body, 1)

        self.highlighter = ConsoleSyntaxHighlighter(self.output.document())

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def auto_scroll(self) -> bool:
        return self.auto_scroll_button.isChecked()

    def set_console_state(self, text: str, state: str) -> None:
        self.state_badge.set_status(text, state)

    def set_maximum_block_count(self, count: int) -> None:
        if count <= 0:
            raise ValueError("maximum block count must be greater than zero")
        self.output.setMaximumBlockCount(count)

    def append_record(self, record: ConsoleRecord) -> None:
        self.output.appendPlainText(record.render())
        if self.auto_scroll:
            cursor = self.output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.output.setTextCursor(cursor)
            self.output.ensureCursorVisible()

    def append_message(
        self,
        level: str,
        source: str,
        message: str,
        *,
        timestamp: datetime | None = None,
    ) -> None:
        stamp = timestamp or datetime.now().astimezone()
        lines = message.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for line in lines or [""]:
            self.append_record(ConsoleRecord(stamp, level, source, line))

    def copy_all(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self.output.toPlainText())

    def clear(self) -> None:
        self.output.clear()

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if self._expanded == expanded:
            self.expand_button.setChecked(expanded)
            return
        self._expanded = expanded
        self.body.setVisible(expanded)
        self.expand_button.setChecked(expanded)
        self.expand_button.setToolTip(
            "Collapse Console" if expanded else "Expand Console"
        )
        semantic_icon = "console.collapse" if expanded else "console.expand"
        self.expand_button.setIcon(
            self._icon_manager.icon(semantic_icon, size=CONSOLE_ICON_SIZE)
        )
        self.expandedChanged.emit(expanded)

    def _tool_button(
        self,
        object_name: str,
        tool_tip: str,
        semantic_icon: str,
        *,
        checkable: bool = False,
        checked: bool = False,
    ) -> QToolButton:
        button = QToolButton(self.header)
        button.setObjectName(object_name)
        button.setToolTip(tool_tip)
        button.setAccessibleName(tool_tip)
        button.setCheckable(checkable)
        button.setChecked(checked)
        button.setFixedSize(*CONSOLE_TOOL_BUTTON_SIZE)
        button.setIconSize(QSize(CONSOLE_ICON_SIZE, CONSOLE_ICON_SIZE))
        button.setIcon(self._icon_manager.icon(semantic_icon, size=CONSOLE_ICON_SIZE))
        set_ui_variant(button, "consoleTool")
        return button


def _single_line(text: str) -> str:
    return str(text).replace("\r", " ").replace("\n", " ")
