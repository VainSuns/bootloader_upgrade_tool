import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from bootloader_upgrade_tool.gui.navigation import (
    APPROVED_PAGE_IDS,
    DEFAULT_PAGE_ID,
    NAVIGATION_TREE,
    NavigationRouter,
    PageId,
    coerce_page_id,
    iter_navigation_page_ids,
)
from bootloader_upgrade_tool.gui.widgets.navigation_panel import NavigationPanel


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_page_ids_and_navigation_tree_are_frozen() -> None:
    assert tuple(page.value for page in PageId) == (
        "program.cpu1",
        "program.cpu2",
        "settings",
        "memory.cpu1",
        "memory.cpu2",
        "advanced",
        "logs",
    )
    assert APPROVED_PAGE_IDS == tuple(PageId)
    assert DEFAULT_PAGE_ID is PageId.PROGRAM_CPU1
    assert iter_navigation_page_ids() == tuple(PageId)
    assert tuple(node.label for node in NAVIGATION_TREE) == (
        "Program",
        "Settings",
        "Memory",
        "Advanced",
        "Logs",
    )
    assert coerce_page_id("logs") is PageId.LOGS
    with pytest.raises(ValueError, match="unknown GUI page id"):
        coerce_page_id("global-settings")


def test_navigation_panel_defaults_to_approved_page_ids() -> None:
    app = qt_app()
    panel = NavigationPanel()

    assert panel.objectName() == "navigationPanel"
    assert panel.tree.objectName() == "navigationTree"
    assert panel.tree.topLevelItemCount() == 5
    assert panel.approved_page_ids == tuple(PageId)

    program = panel.tree.topLevelItem(0)
    memory = panel.tree.topLevelItem(2)
    assert program.text(0) == "Program"
    assert program.childCount() == 2
    assert memory.text(0) == "Memory"
    assert memory.childCount() == 2

    panel.select_page(PageId.PROGRAM_CPU1)
    assert panel.selected_page() == PageId.PROGRAM_CPU1

    panel.close()
    app.processEvents()


def test_navigation_router_is_the_only_stack_synchronization_path() -> None:
    app = qt_app()
    panel = NavigationPanel()
    stack = QStackedWidget()
    router = NavigationRouter(stack, panel)
    pages = {page_id: QWidget() for page_id in PageId}
    for page_id, widget in pages.items():
        router.register_page(page_id, widget)

    changes: list[PageId] = []
    router.pageChanged.connect(changes.append)

    router.navigate_to(PageId.PROGRAM_CPU1)
    assert stack.currentWidget() is pages[PageId.PROGRAM_CPU1]
    assert panel.selected_page() == PageId.PROGRAM_CPU1
    assert router.current_page is PageId.PROGRAM_CPU1

    panel.select_page(PageId.LOGS, emit=True)
    assert stack.currentWidget() is pages[PageId.LOGS]
    assert router.current_page is PageId.LOGS
    assert changes == [PageId.PROGRAM_CPU1, PageId.LOGS]

    with pytest.raises(KeyError, match="not registered"):
        NavigationRouter(QStackedWidget(), NavigationPanel()).navigate_to(PageId.SETTINGS)

    with pytest.raises(ValueError, match="duplicate GUI page"):
        router.register_page(PageId.LOGS, QWidget())

    second_panel = NavigationPanel()
    second_stack = QStackedWidget()
    second_router = NavigationRouter(second_stack, second_panel)
    shared_widget = QWidget()
    second_router.register_page(PageId.PROGRAM_CPU1, shared_widget)
    with pytest.raises(ValueError, match="same widget"):
        second_router.register_page(PageId.PROGRAM_CPU2, shared_widget)

    second_panel.close()
    second_stack.close()
    panel.close()
    stack.close()
    app.processEvents()
