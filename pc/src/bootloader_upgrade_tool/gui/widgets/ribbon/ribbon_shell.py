"""Compact Ribbon shell and reusable Ribbon controls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...icon_manager import IconManager
from ...layout_metrics import (
    RIBBON_CONTENT_ROW_HEIGHT,
    RIBBON_ICON_SIZE,
    RIBBON_TAB_ROW_HEIGHT,
    RIBBON_TOTAL_HEIGHT,
)
from ...ui_state import set_ui_properties, set_ui_variant


class RibbonTab(str, Enum):
    SESSION = "Session"
    OPERATE = "Operate"
    VIEW = "View"
    SETTINGS = "Settings"


RIBBON_TAB_ORDER: Final = (
    RibbonTab.SESSION,
    RibbonTab.OPERATE,
    RibbonTab.VIEW,
    RibbonTab.SETTINGS,
)
DEFAULT_RIBBON_TAB: Final = RibbonTab.OPERATE


@dataclass(frozen=True, slots=True)
class RibbonButtonSpec:
    text: str
    object_name: str
    semantic_icon: str
    checkable: bool = False
    enabled: bool = True
    tooltip: str = ""


class RibbonGroup(QFrame):
    """One captioned Ribbon group with a reusable body layout."""

    def __init__(
        self,
        caption: str,
        *,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        set_ui_properties(self, uiRole="ribbonGroup")
        self.setProperty("class", "ribbonGroup")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 2)
        outer.setSpacing(2)

        self.body = QWidget(self)
        self.body_layout = QHBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(4)
        outer.addWidget(self.body, 1)

        self.caption_label = QLabel(caption, self)
        self.caption_label.setProperty("class", "ribbonGroupCaption")
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption_label.setFixedHeight(18)
        outer.addWidget(self.caption_label, 0)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body_layout.addWidget(widget, stretch)

    def add_stretch(self, stretch: int = 1) -> None:
        self.body_layout.addStretch(stretch)


class RibbonShell(QFrame):
    """Frozen V1.0 Ribbon hierarchy with explicit tab and page stacks."""

    tabChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topRibbonShell")
        self.setFixedHeight(RIBBON_TOTAL_HEIGHT)
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._tab_buttons: dict[RibbonTab, QPushButton] = {}
        self._tab_pages: dict[RibbonTab, QWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_row = QFrame(self)
        self.title_row.setObjectName("titleTabRow")
        self.title_row.setFixedHeight(RIBBON_TAB_ROW_HEIGHT)
        title_layout = QHBoxLayout(self.title_row)
        title_layout.setContentsMargins(10, 0, 10, 0)
        title_layout.setSpacing(8)

        self.app_title = QLabel("Bootloader", self.title_row)
        self.app_title.setObjectName("appTitleLabel")
        self.app_title.setMinimumWidth(132)
        title_layout.addWidget(self.app_title, 0)

        self.tab_bar = QWidget(self.title_row)
        self.tab_bar.setObjectName("ribbonTabBar")
        self.tab_bar_layout = QHBoxLayout(self.tab_bar)
        self.tab_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.tab_bar_layout.setSpacing(2)
        title_layout.addWidget(self.tab_bar, 0)
        title_layout.addStretch(1)
        root.addWidget(self.title_row)

        self.content_row = QFrame(self)
        self.content_row.setObjectName("ribbonContentRow")
        self.content_row.setFixedHeight(RIBBON_CONTENT_ROW_HEIGHT)
        content_layout = QVBoxLayout(self.content_row)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.page_stack = QStackedWidget(self.content_row)
        self.page_stack.setObjectName("ribbonPageStack")
        content_layout.addWidget(self.page_stack)
        root.addWidget(self.content_row)

    @property
    def tab_order(self) -> tuple[RibbonTab, ...]:
        return tuple(self._tab_buttons)

    @property
    def current_tab(self) -> RibbonTab | None:
        widget = self.page_stack.currentWidget()
        for tab, page in self._tab_pages.items():
            if page is widget:
                return tab
        return None

    def add_tab(self, tab: RibbonTab, content: QWidget) -> None:
        if tab in self._tab_buttons:
            raise ValueError(f"duplicate Ribbon tab: {tab.value}")
        position = len(self._tab_buttons)
        if position >= len(RIBBON_TAB_ORDER) or tab is not RIBBON_TAB_ORDER[position]:
            expected = (
                RIBBON_TAB_ORDER[position].value
                if position < len(RIBBON_TAB_ORDER)
                else "no additional tab"
            )
            raise ValueError(
                f"Ribbon tabs must follow the frozen order; expected {expected}, "
                f"got {tab.value}"
            )
        if not isinstance(content, QWidget):
            raise TypeError("Ribbon tab content must be a QWidget")

        button = QPushButton(tab.value, self.tab_bar)
        button.setObjectName(f"ribbon{tab.name.title()}Tab")
        button.setCheckable(True)
        button.setMinimumWidth(76)
        button.setFixedHeight(RIBBON_TAB_ROW_HEIGHT)
        button.setProperty("class", "ribbonTabButton")
        set_ui_variant(button, "ghost")
        self.tab_bar_layout.addWidget(button)
        self._button_group.addButton(button)

        self.page_stack.addWidget(content)
        self._tab_buttons[tab] = button
        self._tab_pages[tab] = content
        button.clicked.connect(lambda _checked=False, selected=tab: self.set_current_tab(selected))

    def set_current_tab(self, tab: RibbonTab | str) -> None:
        resolved = tab if isinstance(tab, RibbonTab) else RibbonTab(tab)
        try:
            button = self._tab_buttons[resolved]
            page = self._tab_pages[resolved]
        except KeyError as exc:
            raise KeyError(f"Ribbon tab has not been added: {resolved.value}") from exc

        changed = self.page_stack.currentWidget() is not page
        button.setChecked(True)
        self.page_stack.setCurrentWidget(page)
        if changed:
            self.tabChanged.emit(resolved.value)

    def tab_button(self, tab: RibbonTab | str) -> QPushButton:
        resolved = tab if isinstance(tab, RibbonTab) else RibbonTab(tab)
        return self._tab_buttons[resolved]

    def tab_page(self, tab: RibbonTab | str) -> QWidget:
        resolved = tab if isinstance(tab, RibbonTab) else RibbonTab(tab)
        return self._tab_pages[resolved]


def create_ribbon_page(object_name: str, parent: QWidget | None = None) -> QFrame:
    page = QFrame(parent)
    page.setObjectName(object_name)
    layout = QHBoxLayout(page)
    layout.setContentsMargins(8, 4, 8, 2)
    layout.setSpacing(4)
    return page


def create_ribbon_button(
    spec: RibbonButtonSpec,
    *,
    icon_manager: IconManager,
    parent: QWidget | None = None,
) -> QToolButton:
    button = QToolButton(parent)
    button.setObjectName(spec.object_name)
    button.setText(spec.text)
    button.setIcon(icon_manager.icon(spec.semantic_icon, size=RIBBON_ICON_SIZE))
    button.setIconSize(QSize(RIBBON_ICON_SIZE, RIBBON_ICON_SIZE))
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    button.setCheckable(spec.checkable)
    button.setEnabled(spec.enabled)
    button.setMinimumWidth(64)
    button.setMaximumWidth(88)
    button.setFixedHeight(58)
    button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    button.setProperty("class", "ribbonToolButton")
    set_ui_variant(button, "ribbon")
    if spec.tooltip:
        button.setToolTip(spec.tooltip)
    return button
