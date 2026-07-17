"""Static Session Ribbon page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from ...icon_manager import IconManager
from ...ui_state import set_ui_role
from .ribbon_shell import (
    RibbonButtonSpec,
    RibbonGroup,
    create_ribbon_button,
    create_ribbon_page,
)


class SessionRibbon(QWidget):
    newRequested = Signal()
    openRequested = Signal()
    saveRequested = Signal()
    saveAsRequested = Signal()
    recentRequested = Signal()

    def __init__(
        self,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sessionRibbonPage")
        self._icon_manager = icon_manager or IconManager()

        page = create_ribbon_page("sessionRibbonContent", self)
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(page, 0, 0)
        row = page.layout()

        file_group = RibbonGroup("File", object_name="sessionFileRibbonGroup", parent=page)
        self.new_button = self._button(
            RibbonButtonSpec("New", "sessionNewButton", "ribbon.session.new", enabled=False),
            self.newRequested.emit,
            file_group,
        )
        self.open_button = self._button(
            RibbonButtonSpec("Open", "sessionOpenButton", "ribbon.session.open", enabled=False),
            self.openRequested.emit,
            file_group,
        )
        self.save_button = self._button(
            RibbonButtonSpec("Save", "sessionSaveButton", "ribbon.session.save", enabled=False),
            self.saveRequested.emit,
            file_group,
        )
        self.save_as_button = self._button(
            RibbonButtonSpec("Save\nAs", "sessionSaveAsButton", "ribbon.session.save_as", enabled=False),
            self.saveAsRequested.emit,
            file_group,
        )
        for button in (
            self.new_button,
            self.open_button,
            self.save_button,
            self.save_as_button,
        ):
            file_group.add_widget(button)
        row.addWidget(file_group)

        recent_group = RibbonGroup("Recent", object_name="sessionRecentRibbonGroup", parent=page)
        self.recent_button = self._button(
            RibbonButtonSpec("Recent", "sessionRecentButton", "ribbon.session.recent", enabled=False),
            self.recentRequested.emit,
            recent_group,
        )
        recent_group.add_widget(self.recent_button)
        row.addWidget(recent_group)

        state_group = RibbonGroup(
            "Session State", object_name="sessionStateRibbonGroup", parent=page
        )
        state_group.setMinimumWidth(220)
        state_group.setMaximumWidth(320)
        fields = QWidget(state_group)
        grid = QGridLayout(fields)
        grid.setContentsMargins(4, 0, 4, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self.current_value = self._add_value(grid, 0, "Current:", "Untitled", "sessionCurrentValue")
        self.modified_value = self._add_value(grid, 1, "Modified:", "No", "sessionModifiedValue")
        self.path_value = self._add_value(grid, 2, "Path:", "—", "sessionPathValue")
        state_group.add_widget(fields, 1)
        row.addWidget(state_group)
        row.addStretch(1)

    def set_session_state(self, *, current: str, modified: bool, path: str | None) -> None:
        self.current_value.setText(current)
        self.modified_value.setText("Yes" if modified else "No")
        self.path_value.setText(path or "—")

    def set_action_states(
        self,
        *,
        new_enabled: bool,
        open_enabled: bool,
        save_enabled: bool,
        save_as_enabled: bool,
        recent_enabled: bool,
        switch_reason: str | None = None,
    ) -> None:
        for button, enabled in (
            (self.new_button, new_enabled),
            (self.open_button, open_enabled),
            (self.save_button, save_enabled),
            (self.save_as_button, save_as_enabled),
            (self.recent_button, recent_enabled),
        ):
            button.setEnabled(enabled)
        for button in (self.new_button, self.open_button, self.recent_button):
            button.setToolTip(switch_reason or "")

    def _button(self, spec: RibbonButtonSpec, callback, parent: QWidget):
        button = create_ribbon_button(spec, icon_manager=self._icon_manager, parent=parent)
        button.clicked.connect(lambda _checked=False: callback())
        return button

    @staticmethod
    def _add_value(
        layout: QGridLayout,
        row: int,
        caption: str,
        value: str,
        object_name: str,
    ) -> QLabel:
        caption_label = QLabel(caption)
        set_ui_role(caption_label, "fieldLabel")
        layout.addWidget(caption_label, row, 0, alignment=Qt.AlignmentFlag.AlignRight)
        value_label = QLabel(value)
        value_label.setObjectName(object_name)
        set_ui_role(value_label, "valueLabel")
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(value_label, row, 1)
        return value_label
