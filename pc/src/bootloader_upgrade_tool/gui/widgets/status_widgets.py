"""Status, scope, and state-label widgets for static GUI pages."""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ..icon_manager import IconManager
from ..ui_state import set_ui_properties, set_ui_scope, set_ui_state

_STATE_ICON_KEYS: Final = {
    "neutral": "common.help_unknown",
    "idle": "common.help_unknown",
    "unknown": "common.help_unknown",
    "disconnected": "common.help_unknown",
    "connecting": "program.progress.busy",
    "connected": "common.success",
    "busy": "program.progress.busy",
    "success": "common.success",
    "warning": "common.warning",
    "error": "common.error",
    "dirty": "common.warning",
    "clean": "common.success",
    "protected": "common.success",
    "unavailable": "common.help_unknown",
}


class StatusDot(QLabel):
    """Auxiliary eight-pixel state dot; never the sole status indicator."""

    def __init__(
        self,
        state: str = "neutral",
        *,
        accessible_name: str = "Status",
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setFixedSize(8, 8)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(accessible_name)
        set_ui_properties(self, uiRole="statusDot", state=state)

    def set_state(self, state: str) -> None:
        set_ui_state(self, state)


class StatusBadge(QLabel):
    """Text-bearing semantic status badge."""

    def __init__(
        self,
        text: str,
        state: str = "neutral",
        *,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        if object_name:
            self.setObjectName(object_name)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        set_ui_properties(self, uiRole="statusBadge", state=state)

    def set_status(self, text: str, state: str) -> None:
        self.setText(text)
        set_ui_state(self, state)


class ScopeBadge(QLabel):
    """Badge for Current or Global Settings scope."""

    def __init__(
        self,
        text: str,
        scope: str,
        *,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        if object_name:
            self.setObjectName(object_name)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        set_ui_properties(self, uiRole="scopeBadge", scope=scope)

    def set_scope(self, text: str, scope: str) -> None:
        self.setText(text)
        set_ui_scope(self, scope)


class StateIconLabel(QWidget):
    """Semantic state icon plus text, suitable for summaries and result rows."""

    def __init__(
        self,
        text: str,
        state: str = "neutral",
        *,
        semantic_icon: str | None = None,
        icon_manager: IconManager | None = None,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self._icon_manager = icon_manager or IconManager()
        self._semantic_icon_override = semantic_icon
        self._state = state

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        self.text_label = QLabel(text, self)
        self.text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.text_label, 1)

        self.set_state(state)

    @property
    def state(self) -> str:
        return self._state

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)

    def set_state(self, state: str, *, text: str | None = None) -> None:
        set_ui_state(self, state)
        self._state = state
        if text is not None:
            self.text_label.setText(text)

        semantic_name = self._semantic_icon_override or _STATE_ICON_KEYS[state]
        tone = _tone_for_state(state)
        icon = self._icon_manager.icon(semantic_name, tone=tone, size=16)
        self.icon_label.setPixmap(icon.pixmap(QSize(16, 16)))
        self.icon_label.setAccessibleName(f"{state} status icon")


def _tone_for_state(state: str) -> str:
    if state in {"success", "connected", "clean", "protected"}:
        return "success"
    if state in {"warning", "dirty"}:
        return "warning"
    if state == "error":
        return "error"
    if state in {"busy", "connecting"}:
        return "primary"
    if state == "unavailable":
        return "disabled"
    return "neutral"
