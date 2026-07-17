"""Final Phase 11 static GUI shell.

This module assembles the approved Ribbon, navigation, Program, Settings,
Memory, Advanced, Logs pages, and global Console. It does not open transports,
invoke operations, touch Flash/metadata, run/reset a target, or implement
CPU2/W5300 backend behavior.
"""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .console_splitter import ConsoleSplitterController
from .icon_manager import IconManager
from .layout_metrics import (
    CONSOLE_DEFAULT_EXPANDED_HEIGHT,
    MAIN_AREA_MINIMUM_HEIGHT,
    MAIN_AREA_SPLITTER_HANDLE_WIDTH,
    NAVIGATION_DEFAULT_WIDTH,
    PAGE_CONTENT_MINIMUM_WIDTH,
    RIBBON_TOTAL_HEIGHT,
    WINDOW_DEFAULT_SIZE,
    WINDOW_MINIMUM_SIZE,
    WINDOW_TITLE,
    WORKSPACE_SPLITTER_HANDLE_WIDTH,
)
from .navigation import DEFAULT_PAGE_ID, PageId, NavigationRouter
from .pages import (
    AdvancedPage,
    LogsPage,
    MemoryTargetPage,
    ProgramTargetPage,
    SettingsPage,
)
from .ui_state import set_ui_role, set_ui_variant
from .widgets.console_widget import ConsoleWidget
from .widgets.navigation_panel import NavigationPanel
from .widgets.ribbon import (
    OperateRibbon,
    RibbonTab,
    SessionRibbon,
    SettingsRibbon,
    ViewRibbon,
    create_default_ribbon,
)


class BootloaderMainWindow(QMainWindow):
    """Approved V1.0 shell with modular Ribbon, pages, and global Console."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("bootloaderMainWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_DEFAULT_SIZE)
        self.setMinimumSize(*WINDOW_MINIMUM_SIZE)
        self._initial_layout_scheduled = False
        self._initial_layout_applied = False
        self._close_authorized = False
        self.runtime_binding = None
        self.session_binding = None
        self.icon_manager = IconManager()

        self.main_root = QWidget(self)
        self.main_root.setObjectName("mainRoot")
        self.setCentralWidget(self.main_root)
        root_layout = QVBoxLayout(self.main_root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.ribbon = create_default_ribbon(
            icon_manager=self.icon_manager,
            parent=self.main_root,
        )
        root_layout.addWidget(self.ribbon, 0)
        set_ui_role(self.ribbon.app_title, "cardTitle")
        for tab in RibbonTab:
            set_ui_variant(self.ribbon.tab_button(tab), "ribbon")
        self.session_ribbon = cast(
            SessionRibbon, self.ribbon.tab_page(RibbonTab.SESSION)
        )
        self.operate_ribbon = cast(
            OperateRibbon, self.ribbon.tab_page(RibbonTab.OPERATE)
        )
        self.view_ribbon = cast(
            ViewRibbon, self.ribbon.tab_page(RibbonTab.VIEW)
        )
        self.settings_ribbon = cast(
            SettingsRibbon, self.ribbon.tab_page(RibbonTab.SETTINGS)
        )

        self.workspace_splitter = self._create_workspace_splitter()
        root_layout.addWidget(self.workspace_splitter, 1)
        self.main_splitter = self._create_main_splitter()
        self.workspace_splitter.addWidget(self.main_splitter)

        self.navigation_panel = NavigationPanel(
            icon_manager=self.icon_manager,
            parent=self.main_splitter,
        )
        self.main_splitter.addWidget(self.navigation_panel)
        self.page_content_host, self.page_stack = self._create_page_host()
        self.main_splitter.addWidget(self.page_content_host)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)

        self.bottom_dock = ConsoleWidget(
            icon_manager=self.icon_manager,
            parent=self.workspace_splitter,
        )
        self.workspace_splitter.addWidget(self.bottom_dock)
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 0)

        self.router = NavigationRouter(
            self.page_stack,
            self.navigation_panel,
            parent=self,
        )
        self.pages: dict[PageId, QWidget] = {}
        self._register_pages()
        self.view_ribbon.pageRequested.connect(self.navigate_to)
        self.settings_ribbon.pageRequested.connect(self.navigate_to)
        self.console_controller = ConsoleSplitterController(
            self.workspace_splitter,
            self.bottom_dock,
            self.view_ribbon,
            window_height=self.height,
            parent=self,
        )

        self._set_initial_splitter_sizes()
        self.navigate_to(DEFAULT_PAGE_ID)

    @property
    def console_expanded_height(self) -> int:
        return self.console_controller.expanded_height

    def navigate_to(self, page_id: PageId) -> None:
        self.router.navigate_to(page_id)

    def set_console_expanded(self, expanded: bool) -> None:
        self.console_controller.set_expanded(expanded)

    def attach_runtime_binding(self, binding) -> None:
        self.runtime_binding = binding

    def attach_session_binding(self, binding) -> None:
        self.session_binding = binding

    def authorize_close(self) -> None:
        self._close_authorized = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if self._close_authorized:
            self._close_authorized = False
            event.accept()
            return
        if self.session_binding is not None and not self.session_binding.request_close():
            event.ignore()
            return
        if self.runtime_binding is None:
            event.accept()
            return
        result = self.runtime_binding.request_application_close()
        if result.decision.name == "ALLOW_IMMEDIATE":
            event.accept()
        else:
            event.ignore()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if self._initial_layout_applied or self._initial_layout_scheduled:
            return
        self._initial_layout_scheduled = True
        QTimer.singleShot(0, self._apply_initial_layout)

    def _create_workspace_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Vertical, self.main_root)
        splitter.setObjectName("workspaceVerticalSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(WORKSPACE_SPLITTER_HANDLE_WIDTH)
        return splitter

    def _create_main_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal, self.workspace_splitter)
        splitter.setObjectName("mainAreaSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(MAIN_AREA_SPLITTER_HANDLE_WIDTH)
        splitter.setMinimumHeight(MAIN_AREA_MINIMUM_HEIGHT)
        return splitter

    def _create_page_host(self) -> tuple[QWidget, QStackedWidget]:
        host = QWidget(self.main_splitter)
        host.setObjectName("pageContentHost")
        host.setMinimumWidth(PAGE_CONTENT_MINIMUM_WIDTH)
        host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        stack = QStackedWidget(host)
        stack.setObjectName("pageContentStack")
        layout.addWidget(stack)
        return host, stack

    def _register_pages(self) -> None:
        self.program_cpu1_page = ProgramTargetPage(
            "cpu1",
            icon_manager=self.icon_manager,
            parent=self.page_stack,
        )
        self.program_cpu2_page = ProgramTargetPage(
            "cpu2",
            icon_manager=self.icon_manager,
            parent=self.page_stack,
        )
        self.settings_page = SettingsPage(
            icon_manager=self.icon_manager,
            parent=self.page_stack,
        )
        self.memory_cpu1_page = MemoryTargetPage(
            "cpu1",
            icon_manager=self.icon_manager,
            parent=self.page_stack,
        )
        self.memory_cpu2_page = MemoryTargetPage(
            "cpu2",
            icon_manager=self.icon_manager,
            parent=self.page_stack,
        )
        self.advanced_page = AdvancedPage(
            icon_manager=self.icon_manager,
            parent=self.page_stack,
        )
        self.logs_page = LogsPage(
            icon_manager=self.icon_manager,
            parent=self.page_stack,
        )

        ordered_pages = (
            (PageId.PROGRAM_CPU1, self.program_cpu1_page),
            (PageId.PROGRAM_CPU2, self.program_cpu2_page),
            (PageId.SETTINGS, self.settings_page),
            (PageId.MEMORY_CPU1, self.memory_cpu1_page),
            (PageId.MEMORY_CPU2, self.memory_cpu2_page),
            (PageId.ADVANCED, self.advanced_page),
            (PageId.LOGS, self.logs_page),
        )
        for page_id, page in ordered_pages:
            self.pages[page_id] = page
            self.router.register_page(page_id, page)

    def _set_initial_splitter_sizes(self) -> None:
        self.main_splitter.setSizes(
            [
                NAVIGATION_DEFAULT_WIDTH,
                max(
                    PAGE_CONTENT_MINIMUM_WIDTH,
                    WINDOW_DEFAULT_SIZE[0] - NAVIGATION_DEFAULT_WIDTH,
                ),
            ]
        )
        workspace_height = max(1, WINDOW_DEFAULT_SIZE[1] - RIBBON_TOTAL_HEIGHT)
        self.workspace_splitter.setSizes(
            [
                max(
                    MAIN_AREA_MINIMUM_HEIGHT,
                    workspace_height - CONSOLE_DEFAULT_EXPANDED_HEIGHT,
                ),
                CONSOLE_DEFAULT_EXPANDED_HEIGHT,
            ]
        )

    def _apply_initial_layout(self) -> None:
        self._initial_layout_scheduled = False
        if self._initial_layout_applied:
            return
        self._initial_layout_applied = True
        self.console_controller.apply_initial_state()


MainWindow = BootloaderMainWindow

__all__ = ["BootloaderMainWindow", "MainWindow"]
