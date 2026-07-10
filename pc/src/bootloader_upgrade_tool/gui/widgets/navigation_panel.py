"""Reusable navigation tree view without page-stack or backend dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import (
    NAVIGATION_MAXIMUM_WIDTH,
    NAVIGATION_MINIMUM_WIDTH,
)


@dataclass(frozen=True, slots=True)
class NavigationItemSpec:
    """One visible navigation node; leaves may carry any stable page-id object."""

    label: str
    semantic_icon: str
    page_id: object | None = None
    children: tuple["NavigationItemSpec", ...] = ()
    enabled: bool = True
    expanded: bool = True


class NavigationPanel(QFrame):
    """Tree-only navigation view; synchronization is owned by MainWindow later."""

    pageActivated = Signal(object)

    def __init__(
        self,
        items: tuple[NavigationItemSpec, ...] = (),
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("navigationPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(NAVIGATION_MINIMUM_WIDTH)
        self.setMaximumWidth(NAVIGATION_MAXIMUM_WIDTH)
        self._icon_manager = icon_manager or IconManager()
        self._items_by_page: dict[object, QTreeWidgetItem] = {}
        self._suppress_activation = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("navigationTree")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(18)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self.tree, 1)

        self.set_items(items)

    def set_items(self, items: tuple[NavigationItemSpec, ...]) -> None:
        self._suppress_activation = True
        try:
            self.tree.clear()
            self._items_by_page.clear()
            for spec in items:
                self._add_spec(None, spec, depth=0)
        finally:
            self._suppress_activation = False

    def page_item(self, page_id: object) -> QTreeWidgetItem:
        try:
            return self._items_by_page[page_id]
        except KeyError as exc:
            raise KeyError(f"unknown navigation page id: {page_id!r}") from exc

    def select_page(self, page_id: object, *, emit: bool = False) -> None:
        item = self.page_item(page_id)
        previous = self._suppress_activation
        self._suppress_activation = not emit
        try:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
        finally:
            self._suppress_activation = previous

    def selected_page(self) -> object | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _add_spec(
        self,
        parent_item: QTreeWidgetItem | None,
        spec: NavigationItemSpec,
        *,
        depth: int,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([spec.label])
        item.setData(0, Qt.ItemDataRole.UserRole, spec.page_id)
        item.setDisabled(not spec.enabled)
        item.setSizeHint(0, QSize(0, 34 if depth == 0 else 32))
        item.setIcon(0, self._icon_manager.icon(spec.semantic_icon, size=16))

        if parent_item is None:
            self.tree.addTopLevelItem(item)
        else:
            parent_item.addChild(item)

        if spec.page_id is not None:
            if spec.page_id in self._items_by_page:
                raise ValueError(f"duplicate navigation page id: {spec.page_id!r}")
            self._items_by_page[spec.page_id] = item

        for child in spec.children:
            self._add_spec(item, child, depth=depth + 1)
        item.setExpanded(spec.expanded)
        return item

    def _on_current_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if self._suppress_activation or current is None or current.isDisabled():
            return
        page_id = current.data(0, Qt.ItemDataRole.UserRole)
        if page_id is not None:
            self.pageActivated.emit(page_id)
