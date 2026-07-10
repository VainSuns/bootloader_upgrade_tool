"""Card, banner, and separator widgets shared by Phase 11 pages."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import ADVANCED_CARD_BODY_MARGIN, ADVANCED_CARD_HEADER_HEIGHT
from ..ui_state import set_ui_properties, set_ui_role, set_ui_state


class CardFrame(QFrame):
    """A border-owning card surface with no implicit internal layout."""

    def __init__(
        self,
        *,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        set_ui_role(self, "card")


class CardHeader(QFrame):
    """Card title row with an optional semantic icon, subtitle, and actions."""

    def __init__(
        self,
        title: str,
        *,
        subtitle: str = "",
        semantic_icon: str | None = None,
        icon_manager: IconManager | None = None,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(ADVANCED_CARD_HEADER_HEIGHT)
        set_ui_role(self, "cardHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setVisible(semantic_icon is not None)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        text_host = QWidget(self)
        text_layout = QVBoxLayout(text_host)
        text_layout.setContentsMargins(0, 3, 0, 3)
        text_layout.setSpacing(0)

        self.title_label = QLabel(title, text_host)
        set_ui_role(self.title_label, "cardTitle")
        text_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(subtitle, text_host)
        self.subtitle_label.setVisible(bool(subtitle))
        set_ui_role(self.subtitle_label, "helperText")
        text_layout.addWidget(self.subtitle_label)

        layout.addWidget(text_host, 1)

        self.actions_host = QWidget(self)
        self.actions_layout = QHBoxLayout(self.actions_host)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(4)
        layout.addWidget(self.actions_host, 0, Qt.AlignmentFlag.AlignVCenter)

        if semantic_icon is not None:
            manager = icon_manager or IconManager()
            icon = manager.icon(semantic_icon, size=16)
            self.icon_label.setPixmap(icon.pixmap(QSize(16, 16)))

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))

    def add_action_widget(self, widget: QWidget) -> None:
        self.actions_layout.addWidget(widget)

    def add_action_widgets(self, widgets: Iterable[QWidget]) -> None:
        for widget in widgets:
            self.add_action_widget(widget)


class SectionCard(CardFrame):
    """A card with a standard header and a caller-owned vertical body layout."""

    def __init__(
        self,
        title: str,
        *,
        subtitle: str = "",
        semantic_icon: str | None = None,
        icon_manager: IconManager | None = None,
        body_margins: tuple[int, int, int, int] | None = None,
        body_spacing: int = 8,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(object_name=object_name, parent=parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = CardHeader(
            title,
            subtitle=subtitle,
            semantic_icon=semantic_icon,
            icon_manager=icon_manager,
            parent=self,
        )
        outer.addWidget(self.header)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        margin = ADVANCED_CARD_BODY_MARGIN
        margins = body_margins or (margin, margin, margin, margin)
        self.body_layout.setContentsMargins(*margins)
        self.body_layout.setSpacing(body_spacing)
        outer.addWidget(self.body, 1)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body_layout.addWidget(widget, stretch)

    def add_stretch(self, stretch: int = 1) -> None:
        self.body_layout.addStretch(stretch)


class NoticeBanner(QFrame):
    """A compact text banner with a semantic state and optional icon."""

    def __init__(
        self,
        title: str,
        message: str = "",
        *,
        state: str = "neutral",
        semantic_icon: str | None = None,
        icon_manager: IconManager | None = None,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)
        set_ui_properties(self, uiRole="banner", state=state)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setVisible(semantic_icon is not None)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_host = QWidget(self)
        text_layout = QVBoxLayout(text_host)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.title_label = QLabel(title, text_host)
        set_ui_role(self.title_label, "cardTitle")
        text_layout.addWidget(self.title_label)

        self.message_label = QLabel(message, text_host)
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(bool(message))
        set_ui_role(self.message_label, "helperText")
        text_layout.addWidget(self.message_label)
        layout.addWidget(text_host, 1)

        self._icon_manager = icon_manager or IconManager()
        self._semantic_icon = semantic_icon
        if semantic_icon is not None:
            self._update_icon(state)

    def set_state(self, state: str) -> None:
        set_ui_state(self, state)
        self._update_icon(state)

    def _update_icon(self, state: str) -> None:
        if self._semantic_icon is None:
            return
        tone = _tone_for_state(state)
        icon = self._icon_manager.icon(self._semantic_icon, tone=tone, size=16)
        self.icon_label.setPixmap(icon.pixmap(QSize(16, 16)))

    def set_message(self, message: str) -> None:
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))


class SeparatorLine(QFrame):
    """A one-pixel themed horizontal or vertical separator."""

    def __init__(
        self,
        orientation: Qt.Orientation = Qt.Orientation.Horizontal,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        set_ui_role(self, "separator")
        if orientation == Qt.Orientation.Horizontal:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(1)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)


def _tone_for_state(state: str) -> str:
    if state in {"success", "connected", "clean", "protected"}:
        return "success"
    if state in {"warning", "dirty"}:
        return "warning"
    if state == "error":
        return "error"
    if state in {"busy", "connecting"}:
        return "primary"
    return "neutral"
