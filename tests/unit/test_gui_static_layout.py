import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QWidget,
)

from bootloader_upgrade_tool.gui import BootloaderMainWindow, MainWindow
from bootloader_upgrade_tool.gui.layout_metrics import (
    MAIN_AREA_MINIMUM_HEIGHT,
    RIBBON_TOTAL_HEIGHT,
    WINDOW_DEFAULT_SIZE,
    WINDOW_MINIMUM_SIZE,
)
from bootloader_upgrade_tool.gui.navigation import DEFAULT_PAGE_ID, PageId
from bootloader_upgrade_tool.gui.pages import (
    AdvancedPage,
    PlaceholderPage,
    ProgramTargetPage,
    SettingsPage,
)
from bootloader_upgrade_tool.gui.widgets.ribbon import RibbonTab


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_uses_frozen_shell_and_defaults() -> None:
    app = qt_app()
    window = BootloaderMainWindow()

    assert isinstance(window, MainWindow)
    assert window.objectName() == "bootloaderMainWindow"
    assert (window.width(), window.height()) == WINDOW_DEFAULT_SIZE
    assert (window.minimumWidth(), window.minimumHeight()) == WINDOW_MINIMUM_SIZE
    assert window.main_root.objectName() == "mainRoot"
    assert window.ribbon.objectName() == "topRibbonShell"
    assert window.ribbon.height() == RIBBON_TOTAL_HEIGHT
    assert window.ribbon.tab_order == tuple(RibbonTab)
    assert window.ribbon.current_tab is RibbonTab.OPERATE

    workspace = window.findChild(QSplitter, "workspaceVerticalSplitter")
    main_area = window.findChild(QSplitter, "mainAreaSplitter")
    assert workspace is window.workspace_splitter
    assert main_area is window.main_splitter
    assert workspace.orientation() == Qt.Orientation.Vertical
    assert main_area.orientation() == Qt.Orientation.Horizontal
    assert not workspace.childrenCollapsible()
    assert not main_area.childrenCollapsible()
    assert main_area.minimumHeight() == MAIN_AREA_MINIMUM_HEIGHT

    window.close()
    app.processEvents()


def test_navigation_program_pages_and_remaining_placeholders() -> None:
    app = qt_app()
    window = BootloaderMainWindow()
    tree = window.findChild(QTreeWidget, "navigationTree")

    assert tree is not None
    assert _nav_text(tree) == [
        ("Program", ["CPU1", "CPU2"]),
        ("Settings", []),
        ("Memory", ["CPU1", "CPU2"]),
        ("Advanced", []),
        ("Logs", []),
    ]
    assert window.router.registered_pages == tuple(PageId)
    assert window.router.current_page is DEFAULT_PAGE_ID
    assert window.navigation_panel.selected_page() is DEFAULT_PAGE_ID
    assert window.page_stack.count() == len(PageId)

    expected = {
        PageId.PROGRAM_CPU1: "CPU1 Program",
        PageId.PROGRAM_CPU2: "CPU2 Program",
        PageId.SETTINGS: "Settings",
        PageId.MEMORY_CPU1: "CPU1 Memory",
        PageId.MEMORY_CPU2: "CPU2 Memory",
        PageId.ADVANCED: "Advanced",
        PageId.LOGS: "Logs",
    }
    for page_id, title in expected.items():
        window.navigate_to(page_id)
        page = window.page_stack.currentWidget()
        assert page is window.pages[page_id]
        assert _current_page_title(window) == title

        banner = page.findChild(QWidget, f"{page.objectName()}PlaceholderBanner")
        if page_id in {PageId.PROGRAM_CPU1, PageId.PROGRAM_CPU2}:
            assert isinstance(page, ProgramTargetPage)
            assert banner is None
        elif page_id is PageId.SETTINGS:
            assert isinstance(page, SettingsPage)
            assert banner is None
        elif page_id is PageId.ADVANCED:
            assert isinstance(page, AdvancedPage)
            assert banner is None
        else:
            assert isinstance(page, PlaceholderPage)
            assert banner is not None
            assert "Layout Placeholder" in [
                label.text() for label in banner.findChildren(QLabel)
            ]

    assert window.program_cpu1_page is window.pages[PageId.PROGRAM_CPU1]
    assert window.program_cpu2_page is window.pages[PageId.PROGRAM_CPU2]
    assert window.settings_page is window.pages[PageId.SETTINGS]
    assert window.advanced_page is window.pages[PageId.ADVANCED]
    assert window.program_cpu1_page.interactions_enabled
    assert not window.program_cpu2_page.interactions_enabled

    window.close()
    app.processEvents()


def test_ribbon_navigation_and_core_object_names() -> None:
    app = qt_app()
    window = BootloaderMainWindow()

    window.view_ribbon.open_logs_button.click()
    assert window.router.current_page is PageId.LOGS
    window.settings_ribbon.open_settings_button.click()
    assert window.router.current_page is PageId.SETTINGS

    required = (
        "mainRoot",
        "topRibbonShell",
        "titleTabRow",
        "ribbonTabBar",
        "ribbonContentRow",
        "ribbonPageStack",
        "workspaceVerticalSplitter",
        "mainAreaSplitter",
        "navigationPanel",
        "navigationTree",
        "pageContentHost",
        "pageContentStack",
        "bottomDock",
        "bottomDockHeader",
        "consoleTitle",
        "consoleCopyButton",
        "consoleAutoScrollButton",
        "consoleClearButton",
        "consoleExpandButton",
        "bottomConsoleBody",
        "consoleOutput",
        "programCpu1Page",
        "programCpu2Page",
        "programCpu1HorizontalSplitter",
        "programCpu2HorizontalSplitter",
        "advancedPage",
        "advancedVerticalSplitter",
        "advancedTabs",
        "advancedSharedResultCard",
        "advancedResultOutput",
    )
    for name in required:
        assert len(
            [widget for widget in window.findChildren(QWidget) if widget.objectName() == name]
        ) == 1, name
    assert all(
        label.text() != "Console / Log" for label in window.findChildren(QLabel)
    )

    window.close()
    app.processEvents()


def _nav_text(tree: QTreeWidget) -> list[tuple[str, list[str]]]:
    result = []
    for row in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(row)
        result.append(
            (
                item.text(0),
                [item.child(index).text(0) for index in range(item.childCount())],
            )
        )
    return result


def _current_page_title(window: BootloaderMainWindow) -> str:
    stack = window.findChild(QStackedWidget, "pageContentStack")
    assert stack is not None and stack.currentWidget() is not None
    page = stack.currentWidget()
    header = page.findChild(QWidget, f"{page.objectName()}Header")
    assert header is not None
    title = header.findChild(QLabel)
    assert title is not None
    return title.text()


def test_package_entrypoints_are_available() -> None:
    from bootloader_upgrade_tool.gui import BootloaderMainWindow, MainWindow, main, run
    from bootloader_upgrade_tool.gui.application import run as compatibility_run

    assert MainWindow is BootloaderMainWindow
    assert callable(main)
    assert callable(run)
    assert callable(compatibility_run)
