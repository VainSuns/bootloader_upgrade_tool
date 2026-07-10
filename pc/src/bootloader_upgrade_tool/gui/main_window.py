"""Phase 11 Batch 4 main-window shell for static GUI review.

This module is an assembly and local-navigation layer only. It does not open
serial ports, perform autobaud, invoke operations, access protocol transports,
erase/program/verify Flash, write metadata, transfer control, reset a target,
or implement CPU2/W5300 backends.
"""

from __future__ import annotations

from typing import Final, cast

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QShowEvent
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
from .pages import PlaceholderPage, PlaceholderPageSpec
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

_PLACEHOLDER_SPECS: Final = (
    PlaceholderPageSpec(
        PageId.PROGRAM_CPU1, "CPU1 Program", "programCpu1Page", "Batch 5"
    ),
    PlaceholderPageSpec(
        PageId.PROGRAM_CPU2, "CPU2 Program", "programCpu2Page", "Batch 5"
    ),
    PlaceholderPageSpec(PageId.SETTINGS, "Settings", "settingsPage", "Batch 6"),
    PlaceholderPageSpec(
        PageId.MEMORY_CPU1, "CPU1 Memory", "memoryCpu1Page", "Batch 8"
    ),
    PlaceholderPageSpec(
        PageId.MEMORY_CPU2, "CPU2 Memory", "memoryCpu2Page", "Batch 8"
    ),
    PlaceholderPageSpec(PageId.ADVANCED, "Advanced", "advancedPage", "Batch 7"),
    PlaceholderPageSpec(PageId.LOGS, "Logs", "logsPage", "Batch 8"),
)


class BootloaderMainWindow(QMainWindow):
    """Approved V1.0 shell with modular Ribbon, navigation, pages, and Console."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("bootloaderMainWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_DEFAULT_SIZE)
        self.setMinimumSize(*WINDOW_MINIMUM_SIZE)
        self._initial_layout_scheduled = False
        self._initial_layout_applied = False
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
        self.pages: dict[PageId, PlaceholderPage] = {}
        self._register_placeholder_pages()
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

    def navigate_to(self, page_id: PageId | str) -> None:
        self.router.navigate_to(page_id)

    def show_page(self, page_id: PageId | str) -> None:
        """Compatibility wrapper; new code should call :meth:`navigate_to`."""

        self.navigate_to(page_id)

    def set_console_expanded(self, expanded: bool) -> None:
        self.console_controller.set_expanded(expanded)

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

    def _register_placeholder_pages(self) -> None:
        for spec in _PLACEHOLDER_SPECS:
            page = PlaceholderPage(
                spec,
                icon_manager=self.icon_manager,
                parent=self.page_stack,
            )
            self.pages[spec.page_id] = page
            self.router.register_page(spec.page_id, page)

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
