"""Local-only View Ribbon controls for Console and Logs."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QWidget

from ...icon_manager import IconManager
from ...navigation import PageId
from .ribbon_shell import (
    RibbonButtonSpec,
    RibbonGroup,
    create_ribbon_button,
    create_ribbon_page,
)


class ViewRibbon(QWidget):
    consoleVisibilityChanged = Signal(bool)
    clearConsoleRequested = Signal()
    consoleAutoScrollChanged = Signal(bool)
    pageRequested = Signal(object)
    exportLogsRequested = Signal()
    openLogFolderRequested = Signal()

    def __init__(
        self,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("viewRibbonPage")
        self._icon_manager = icon_manager or IconManager()

        page = create_ribbon_page("viewRibbonContent", self)
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(page, 0, 0)
        row = page.layout()

        console_group = RibbonGroup(
            "Console", object_name="viewConsoleRibbonGroup", parent=page
        )
        self.console_toggle_button = self._button(
            RibbonButtonSpec(
                "Console",
                "viewConsoleToggleButton",
                "ribbon.view.console",
                checkable=True,
            ),
            console_group,
        )
        self.console_toggle_button.setChecked(True)
        self.console_clear_button = self._button(
            RibbonButtonSpec(
                "Clear",
                "viewConsoleClearButton",
                "ribbon.view.clear_console",
            ),
            console_group,
        )
        self.console_auto_scroll_button = self._button(
            RibbonButtonSpec(
                "Auto\nScroll",
                "viewConsoleAutoScrollButton",
                "ribbon.view.auto_scroll",
                checkable=True,
            ),
            console_group,
        )
        self.console_auto_scroll_button.setChecked(True)
        for button in (
            self.console_toggle_button,
            self.console_clear_button,
            self.console_auto_scroll_button,
        ):
            console_group.add_widget(button)
        row.addWidget(console_group)

        logs_group = RibbonGroup("Logs", object_name="viewLogsRibbonGroup", parent=page)
        self.open_logs_button = self._button(
            RibbonButtonSpec(
                "Open\nLogs", "viewOpenLogsButton", "ribbon.view.open_logs"
            ),
            logs_group,
        )
        self.export_logs_button = self._button(
            RibbonButtonSpec(
                "Export",
                "viewExportLogsButton",
                "ribbon.view.export_logs",
                enabled=False,
                tooltip="Enabled when the Logs page provides local export.",
            ),
            logs_group,
        )
        self.open_log_folder_button = self._button(
            RibbonButtonSpec(
                "Folder",
                "viewOpenLogFolderButton",
                "ribbon.view.open_log_folder",
                enabled=False,
                tooltip="Enabled when a local log folder is configured.",
            ),
            logs_group,
        )
        for button in (
            self.open_logs_button,
            self.export_logs_button,
            self.open_log_folder_button,
        ):
            logs_group.add_widget(button)
        row.addWidget(logs_group)
        row.addStretch(1)

        self.console_toggle_button.toggled.connect(self.consoleVisibilityChanged.emit)
        self.console_clear_button.clicked.connect(lambda _checked=False: self.clearConsoleRequested.emit())
        self.console_auto_scroll_button.toggled.connect(
            self.consoleAutoScrollChanged.emit
        )
        self.open_logs_button.clicked.connect(
            lambda _checked=False: self.pageRequested.emit(PageId.LOGS)
        )
        self.export_logs_button.clicked.connect(lambda _checked=False: self.exportLogsRequested.emit())
        self.open_log_folder_button.clicked.connect(lambda _checked=False: self.openLogFolderRequested.emit())

    def set_console_visible(self, visible: bool) -> None:
        self.console_toggle_button.setChecked(bool(visible))

    def set_console_auto_scroll(self, enabled: bool) -> None:
        self.console_auto_scroll_button.setChecked(bool(enabled))

    def _button(self, spec: RibbonButtonSpec, parent: QWidget):
        return create_ribbon_button(
            spec,
            icon_manager=self._icon_manager,
            parent=parent,
        )
