"""Reusable page title rows for Phase 11 static pages."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..layout_metrics import PAGE_TITLE_ROW_HEIGHT
from ..ui_state import set_ui_role
from .status_widgets import StatusBadge


class PageHeader(QWidget):
    """Page title, optional description, and a right-aligned action area."""

    def __init__(
        self,
        title: str,
        *,
        description: str = "",
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setMinimumHeight(PAGE_TITLE_ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        text_host = QWidget(self)
        text_layout = QVBoxLayout(text_host)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        self.title_label = QLabel(title, text_host)
        set_ui_role(self.title_label, "pageTitle")
        text_layout.addWidget(self.title_label)

        self.description_label = QLabel(description, text_host)
        self.description_label.setVisible(bool(description))
        self.description_label.setWordWrap(True)
        set_ui_role(self.description_label, "pageDescription")
        text_layout.addWidget(self.description_label)

        layout.addWidget(text_host, 1, Qt.AlignmentFlag.AlignVCenter)

        self.actions_host = QWidget(self)
        self.actions_layout = QHBoxLayout(self.actions_host)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(6)
        layout.addWidget(self.actions_host, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_description(self, description: str) -> None:
        self.description_label.setText(description)
        self.description_label.setVisible(bool(description))

    def add_action_widget(self, widget: QWidget) -> None:
        self.actions_layout.addWidget(widget)

    def add_action_widgets(self, widgets: Iterable[QWidget]) -> None:
        for widget in widgets:
            self.add_action_widget(widget)


class TargetPageHeader(PageHeader):
    """Page header with target and optional static-preview badges."""

    def __init__(
        self,
        title: str,
        *,
        target_text: str,
        target_state: str = "neutral",
        description: str = "",
        preview: bool = False,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            title,
            description=description,
            object_name=object_name,
            parent=parent,
        )
        self.target_badge = StatusBadge(
            target_text,
            target_state,
            parent=self,
        )
        self.add_action_widget(self.target_badge)

        self.preview_badge = StatusBadge(
            "Layout Preview",
            "warning",
            parent=self,
        )
        self.preview_badge.setVisible(preview)
        self.add_action_widget(self.preview_badge)

    def set_target_status(self, text: str, state: str) -> None:
        self.target_badge.set_status(text, state)

    def set_preview_visible(self, visible: bool) -> None:
        self.preview_badge.setVisible(visible)
