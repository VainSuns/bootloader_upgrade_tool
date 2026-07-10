"""Stable page identifiers and local-only navigation synchronization.

This module owns no backend behavior. It synchronizes approved GUI page IDs,
the navigation tree, and a ``QStackedWidget`` without selecting protocol
commands or touching hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QStackedWidget, QWidget


class PageId(str, Enum):
    """Frozen top-level page identifiers from the Phase 11 V1.0 contract."""

    PROGRAM_CPU1 = "program.cpu1"
    PROGRAM_CPU2 = "program.cpu2"
    SETTINGS = "settings"
    MEMORY_CPU1 = "memory.cpu1"
    MEMORY_CPU2 = "memory.cpu2"
    ADVANCED = "advanced"
    LOGS = "logs"


DEFAULT_PAGE_ID: Final = PageId.PROGRAM_CPU1


@dataclass(frozen=True, slots=True)
class NavigationNode:
    """One approved navigation node."""

    label: str
    semantic_icon: str
    page_id: PageId | None = None
    children: tuple["NavigationNode", ...] = ()
    enabled: bool = True
    expanded: bool = True


NAVIGATION_TREE: Final[tuple[NavigationNode, ...]] = (
    NavigationNode(
        "Program",
        "navigation.program",
        children=(
            NavigationNode("CPU1", "navigation.program.cpu1", PageId.PROGRAM_CPU1),
            NavigationNode("CPU2", "navigation.program.cpu2", PageId.PROGRAM_CPU2),
        ),
    ),
    NavigationNode("Settings", "navigation.settings", PageId.SETTINGS),
    NavigationNode(
        "Memory",
        "navigation.memory",
        children=(
            NavigationNode("CPU1", "navigation.memory.cpu1", PageId.MEMORY_CPU1),
            NavigationNode("CPU2", "navigation.memory.cpu2", PageId.MEMORY_CPU2),
        ),
    ),
    NavigationNode("Advanced", "navigation.advanced", PageId.ADVANCED),
    NavigationNode("Logs", "navigation.logs", PageId.LOGS),
)

APPROVED_PAGE_IDS: Final = tuple(PageId)


def iter_navigation_page_ids(
    nodes: tuple[NavigationNode, ...] = NAVIGATION_TREE,
) -> tuple[PageId, ...]:
    """Flatten leaf page IDs in visible navigation order."""

    result: list[PageId] = []
    for node in nodes:
        if node.page_id is not None:
            result.append(node.page_id)
        result.extend(iter_navigation_page_ids(node.children))
    return tuple(result)


class NavigationRouter(QObject):
    """Synchronize a navigation panel and page stack through ``navigate_to``.

    The router is intentionally local-only. Pages must be registered explicitly,
    and navigation never invokes operations, sessions, transports, or protocols.
    """

    pageChanged = Signal(object)

    def __init__(
        self,
        page_stack: QStackedWidget,
        navigation_panel: QWidget,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(page_stack, QStackedWidget):
            raise TypeError("page_stack must be a QStackedWidget")
        if not hasattr(navigation_panel, "pageActivated"):
            raise TypeError("navigation_panel must expose pageActivated")
        if not callable(getattr(navigation_panel, "select_page", None)):
            raise TypeError("navigation_panel must expose select_page(page_id)")

        self._page_stack = page_stack
        self._navigation_panel = navigation_panel
        self._widgets: dict[PageId, QWidget] = {}
        self._current_page: PageId | None = None
        navigation_panel.pageActivated.connect(self._on_panel_page_activated)

    @property
    def current_page(self) -> PageId | None:
        return self._current_page

    @property
    def registered_pages(self) -> tuple[PageId, ...]:
        return tuple(self._widgets)

    def register_page(self, page_id: PageId, widget: QWidget) -> int:
        """Register one page and return its stack index."""

        if not isinstance(page_id, PageId):
            raise TypeError("page_id must be a PageId")
        if not isinstance(widget, QWidget):
            raise TypeError("widget must be a QWidget")
        if page_id in self._widgets:
            raise ValueError(f"duplicate GUI page registration: {page_id.value}")
        if widget in self._widgets.values():
            raise ValueError("the same widget cannot be registered for multiple GUI pages")

        existing_index = self._page_stack.indexOf(widget)
        index = existing_index if existing_index >= 0 else self._page_stack.addWidget(widget)
        self._widgets[page_id] = widget
        return index

    def navigate_to(self, page_id: PageId) -> None:
        """Select one registered page and synchronize navigation state."""

        if not isinstance(page_id, PageId):
            raise TypeError("page_id must be a PageId")
        try:
            widget = self._widgets[page_id]
        except KeyError as exc:
            raise KeyError(f"GUI page is not registered: {page_id.value}") from exc

        self._page_stack.setCurrentWidget(widget)
        self._navigation_panel.select_page(page_id, emit=False)
        if self._current_page != page_id:
            self._current_page = page_id
            self.pageChanged.emit(page_id)

    def _on_panel_page_activated(self, page_id: object) -> None:
        if not isinstance(page_id, PageId):
            raise TypeError("navigation panel emitted a non-PageId value")
        self.navigate_to(page_id)
