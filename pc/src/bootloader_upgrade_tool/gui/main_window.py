"""Phase 11 GUI static layout skeleton.

Scope:
    - PySide6 static GUI layout only.
    - UniFlash-like engineering tool layout.
    - Stable objectName values for later controller wiring.

Out of scope:
    - No serial transport.
    - No autobaud.
    - No Flash erase/program/verify.
    - No metadata writes.
    - No real DSP hardware operation.
    - No operation-library wiring in this skeleton.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .styles import (
    BOTTOM_DOCK_COLLAPSED_HEIGHT,
    BOTTOM_DOCK_EXPANDED_HEIGHT,
    LOG_DETAIL_DEFAULT_HEIGHT,
    MEMORY_CONTROL_BAR_HEIGHT,
    MEMORY_DEFAULT_ROWS,
    MEMORY_WORD_COLUMNS,
    NAVIGATION_MAX_WIDTH,
    NAVIGATION_MIN_WIDTH,
    NAVIGATION_WIDTH,
    PAGE_CONTENT_MAX_WIDTH,
    ADVANCED_TAB_MIN_WIDTH,
    ADVANCED_RAM_TAB_MIN_WIDTH,
    ADVANCED_TWO_COLUMN_MIN_WIDTH,
    ADVANCED_RESULT_MIN_HEIGHT,
    ADVANCED_TABS_MIN_HEIGHT,
    PROGRAM_PAGE_MIN_WIDTH,
    PROGRAM_APP_CARD_MIN_HEIGHT,
    PROGRAM_STATUS_CARD_MIN_HEIGHT,
    PROGRAM_RESULT_CARD_MIN_HEIGHT,
    SETTINGS_PAGE_MIN_WIDTH,
    RIBBON_CONTENT_ROW_HEIGHT,
    TITLE_TAB_ROW_HEIGHT,
    TOP_RIBBON_TOTAL_HEIGHT,
    WINDOW_DEFAULT_SIZE,
    WINDOW_MINIMUM_SIZE,
    WINDOW_TITLE,
)


@dataclass(frozen=True)
class PageKey:
    PROGRAM_CPU1: str = "program_cpu1"
    PROGRAM_CPU2: str = "program_cpu2"
    SESSION_SETTINGS: str = "session_settings"
    MEMORY_CPU1: str = "memory_cpu1"
    MEMORY_CPU2: str = "memory_cpu2"
    ADVANCED: str = "advanced"
    LOGS: str = "logs"
    GLOBAL_SETTINGS: str = "global_settings"


PAGES = PageKey()


class BootloaderMainWindow(QMainWindow):
    """Main window with frozen Phase 11 static layout."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("bootloaderMainWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_DEFAULT_SIZE)
        self.setMinimumSize(*WINDOW_MINIMUM_SIZE)

        self.page_indexes: dict[str, int] = {}

        root = QWidget(self)
        root.setObjectName("mainRoot")
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.ribbon = RibbonShell(self)
        self.ribbon.setObjectName("topRibbonShell")
        root_layout.addWidget(self.ribbon, 0)
        self._build_ribbon_tabs()

        self.main_splitter = QSplitter(Qt.Horizontal, root)
        self.main_splitter.setObjectName("mainAreaSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.main_splitter, 1)

        self.navigation_panel = self._create_navigation_panel()
        self.main_splitter.addWidget(self.navigation_panel)

        self.page_stack = QStackedWidget(self.main_splitter)
        self.page_stack.setObjectName("pageContentStack")
        self.main_splitter.addWidget(self.page_stack)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([NAVIGATION_WIDTH, WINDOW_DEFAULT_SIZE[0] - NAVIGATION_WIDTH])

        self._build_pages()

        self.bottom_dock = BottomConsoleDock(root)
        self.bottom_dock.setObjectName("bottomDock")
        root_layout.addWidget(self.bottom_dock, 0)

        self._wire_static_navigation()
        self._select_default_page()

    def _build_ribbon_tabs(self) -> None:
        self.ribbon.add_tab("Session", self._create_session_ribbon())
        self.ribbon.add_tab("Operate", self._create_operate_ribbon())
        self.ribbon.add_tab("View", self._create_view_ribbon())
        self.ribbon.add_tab("Settings", self._create_settings_ribbon())
        self.ribbon.set_current_tab("Operate")

    def _create_session_ribbon(self) -> QWidget:
        row = ribbon_row()
        row.layout().addWidget(ribbon_group(
            "File",
            [
                ribbon_button("New", "sessionNewButton"),
                ribbon_button("Open", "sessionOpenButton"),
                ribbon_button("Save", "sessionSaveButton"),
                ribbon_button("Save\nAs", "sessionSaveAsButton"),
            ],
        ))
        row.layout().addWidget(ribbon_group(
            "Recent",
            [ribbon_button("Recent ▼", "sessionRecentButton")],
        ))
        row.layout().addWidget(self._create_session_state_group())
        row.layout().addStretch(1)
        return row

    def _create_session_state_group(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("sessionStateRibbonGroup")
        frame.setProperty("class", "ribbonGroup")
        frame.setMinimumWidth(220)
        frame.setMaximumWidth(320)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 6, 10, 2)
        layout.setSpacing(2)

        fields = QWidget(frame)
        field_layout = QGridLayout(fields)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setHorizontalSpacing(8)
        field_layout.setVerticalSpacing(2)
        add_field(field_layout, 0, "Current:", "Untitled", "sessionCurrentValue")
        add_field(field_layout, 1, "Modified:", "No", "sessionModifiedValue")
        add_field(field_layout, 2, "Path:", "—", "sessionPathValue")
        layout.addWidget(fields, 1)
        layout.addWidget(ribbon_caption("Session State"), 0, alignment=Qt.AlignBottom | Qt.AlignHCenter)
        return frame

    def _create_operate_ribbon(self) -> QWidget:
        row = ribbon_row()
        row.layout().addWidget(self._create_transport_block())
        row.layout().addWidget(ribbon_group(
            "Operate",
            [
                ribbon_button("Connect", "connectButton"),
                ribbon_button("Load\nImage", "loadImageButton"),
                ribbon_button("Run", "runButton"),
            ],
        ))
        row.layout().addWidget(self._create_status_block())
        row.layout().addStretch(1)
        return row

    def _create_transport_block(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("transportRibbonGroup")
        frame.setProperty("class", "ribbonGroup")
        frame.setMinimumWidth(260)
        frame.setMaximumWidth(300)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 4, 10, 2)
        layout.setSpacing(2)

        tabs = QTabWidget(frame)
        tabs.setObjectName("transportTabs")
        tabs.setDocumentMode(True)
        tabs.setMaximumHeight(78)

        sci = QWidget()
        sci_layout = QGridLayout(sci)
        sci_layout.setContentsMargins(8, 4, 8, 4)
        sci_layout.setHorizontalSpacing(6)
        sci_layout.setVerticalSpacing(3)
        sci_layout.addWidget(QLabel("Port:"), 0, 0)
        port = QComboBox()
        port.setObjectName("sciPortCombo")
        port.addItems(["COM1", "COM2", "COM3", "COM4"])
        sci_layout.addWidget(port, 0, 1)
        sci_layout.addWidget(QLabel("Baud:"), 1, 0)
        baud = QComboBox()
        baud.setObjectName("sciBaudCombo")
        baud.addItems(["9600", "115200"])
        sci_layout.addWidget(baud, 1, 1)
        tabs.addTab(sci, "SCI")

        tcp = QWidget()
        tcp.setEnabled(False)
        tcp_layout = QGridLayout(tcp)
        tcp_layout.setContentsMargins(8, 4, 8, 4)
        tcp_layout.setHorizontalSpacing(6)
        tcp_layout.setVerticalSpacing(3)
        tcp_layout.addWidget(QLabel("IP:"), 0, 0)
        ip = QLineEdit("192.168.1.100")
        ip.setObjectName("tcpIpLineEdit")
        tcp_layout.addWidget(ip, 0, 1)
        tcp_layout.addWidget(QLabel("Port:"), 1, 0)
        tcp_port = QLineEdit("5000")
        tcp_port.setObjectName("tcpPortLineEdit")
        tcp_layout.addWidget(tcp_port, 1, 1)
        tabs.addTab(tcp, "TCP")
        tabs.setTabEnabled(1, False)
        tabs.setToolTip("Reserved for future W5300 TCP transport.")

        layout.addWidget(tabs, 1)
        layout.addWidget(ribbon_caption("Transport"), 0, alignment=Qt.AlignBottom | Qt.AlignHCenter)
        return frame

    def _create_status_block(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("cpuStatusRibbonGroup")
        frame.setProperty("class", "ribbonGroup")
        frame.setMinimumWidth(125)
        frame.setMaximumWidth(150)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 2)
        layout.setSpacing(2)

        status_box = QWidget(frame)
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        status_layout.addWidget(status_indicator_row("CPU1", "cpu1StatusIndicator"), 0, alignment=Qt.AlignHCenter)
        status_layout.addWidget(status_indicator_row("CPU2", "cpu2StatusIndicator"), 0, alignment=Qt.AlignHCenter)
        layout.addWidget(status_box, 1, alignment=Qt.AlignCenter)
        layout.addWidget(ribbon_caption("Status"), 0, alignment=Qt.AlignBottom | Qt.AlignHCenter)
        return frame

    def _create_view_ribbon(self) -> QWidget:
        row = ribbon_row()
        row.layout().addWidget(ribbon_group(
            "Console",
            [
                ribbon_button("Console", "consoleToggleButton", checkable=True),
                ribbon_button("Clear", "consoleClearButton"),
                ribbon_button("Auto\nScroll", "consoleAutoScrollButton", checkable=True),
            ],
        ))
        row.layout().addWidget(ribbon_group(
            "Logs",
            [
                ribbon_button("Open\nLogs", "openLogsButton"),
                ribbon_button("Export", "exportLogsButton"),
                ribbon_button("Folder", "openLogFolderButton"),
            ],
        ))
        row.layout().addStretch(1)
        return row

    def _create_settings_ribbon(self) -> QWidget:
        row = ribbon_row()
        row.layout().addWidget(ribbon_group(
            "Global",
            [
                ribbon_button("Global\nSettings", "globalSettingsButton"),
                ribbon_button("Save", "globalSettingsSaveButton"),
                ribbon_button("Reload", "globalSettingsReloadButton"),
            ],
        ))
        row.layout().addStretch(1)
        return row

    def _create_navigation_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("navigationPanel")
        panel.setMinimumWidth(NAVIGATION_MIN_WIDTH)
        panel.setMaximumWidth(NAVIGATION_MAX_WIDTH)
        panel.resize(NAVIGATION_WIDTH, panel.height())
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.navigation_tree = QTreeWidget(panel)
        self.navigation_tree.setObjectName("navigationTree")
        self.navigation_tree.setHeaderHidden(True)
        self.navigation_tree.setIndentation(18)
        self.navigation_tree.setRootIsDecorated(True)
        self.navigation_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.navigation_tree)

        program = nav_item("Program")
        program.addChild(nav_item("CPU1", PAGES.PROGRAM_CPU1))
        program.addChild(nav_item("CPU2", PAGES.PROGRAM_CPU2))

        settings = nav_item("Settings", PAGES.SESSION_SETTINGS)

        memory = nav_item("Memory")
        memory.addChild(nav_item("CPU1", PAGES.MEMORY_CPU1))
        memory.addChild(nav_item("CPU2", PAGES.MEMORY_CPU2))

        advanced = nav_item("Advanced", PAGES.ADVANCED)
        logs = nav_item("Logs", PAGES.LOGS)

        self.navigation_tree.addTopLevelItems([program, settings, memory, advanced, logs])
        self.navigation_tree.expandAll()
        return panel

    def _build_pages(self) -> None:
        self._add_page(PAGES.PROGRAM_CPU1, create_program_page("CPU1"))
        self._add_page(PAGES.PROGRAM_CPU2, create_program_page("CPU2"))
        self._add_page(PAGES.SESSION_SETTINGS, create_session_settings_page())
        self._add_page(PAGES.MEMORY_CPU1, create_memory_page("CPU1"))
        self._add_page(PAGES.MEMORY_CPU2, create_memory_page("CPU2"))
        self._add_page(PAGES.ADVANCED, create_advanced_page())
        self._add_page(PAGES.LOGS, create_logs_page())
        self._add_page(PAGES.GLOBAL_SETTINGS, create_global_settings_page())

    def _add_page(self, key: str, widget: QWidget) -> None:
        self.page_indexes[key] = self.page_stack.addWidget(widget)

    def _wire_static_navigation(self) -> None:
        self.navigation_tree.itemClicked.connect(self._on_navigation_item_clicked)
        self.ribbon.findChild(QToolButton, "openLogsButton").clicked.connect(lambda: self.show_page(PAGES.LOGS))
        self.ribbon.findChild(QToolButton, "globalSettingsButton").clicked.connect(lambda: self.show_page(PAGES.GLOBAL_SETTINGS))
        self.ribbon.findChild(QToolButton, "consoleToggleButton").clicked.connect(self.bottom_dock.toggle_collapsed)
        self.ribbon.findChild(QToolButton, "consoleClearButton").clicked.connect(self.bottom_dock.clear)

    def _select_default_page(self) -> None:
        root = self.navigation_tree.topLevelItem(0)
        cpu1 = root.child(0)
        self.navigation_tree.setCurrentItem(cpu1)
        self.show_page(PAGES.PROGRAM_CPU1)

    def _on_navigation_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        key = item.data(0, Qt.UserRole)
        if key:
            self.show_page(key)

    def show_page(self, key: str) -> None:
        index = self.page_indexes.get(key)
        if index is not None:
            self.page_stack.setCurrentIndex(index)


class RibbonShell(QFrame):
    """Custom compact ribbon with fixed title row and content row."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(TOP_RIBBON_TOTAL_HEIGHT)
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._tab_buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_row = QFrame(self)
        self.title_row.setObjectName("titleTabRow")
        self.title_row.setFixedHeight(TITLE_TAB_ROW_HEIGHT)
        title_layout = QHBoxLayout(self.title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)

        title = QLabel("Bootloader", self.title_row)
        title.setObjectName("appTitleLabel")
        title.setFixedWidth(150)
        title_layout.addWidget(title)
        title_layout.addSpacing(8)

        self.tab_bar = QWidget(self.title_row)
        self.tab_bar_layout = QHBoxLayout(self.tab_bar)
        self.tab_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.tab_bar_layout.setSpacing(0)
        title_layout.addWidget(self.tab_bar, 0)
        title_layout.addStretch(1)
        layout.addWidget(self.title_row)

        self.content_stack = QStackedWidget(self)
        self.content_stack.setObjectName("ribbonContentRow")
        self.content_stack.setFixedHeight(RIBBON_CONTENT_ROW_HEIGHT)
        layout.addWidget(self.content_stack)

    def add_tab(self, title: str, content: QWidget) -> None:
        button = QPushButton(title, self.tab_bar)
        button.setCheckable(True)
        button.setProperty("class", "ribbonTabButton")
        self.tab_bar_layout.addWidget(button)
        self._button_group.addButton(button)
        index = self.content_stack.addWidget(content)
        button.clicked.connect(lambda checked=False, idx=index: self.content_stack.setCurrentIndex(idx))
        self._tab_buttons[title] = button

    def set_current_tab(self, title: str) -> None:
        button = self._tab_buttons[title]
        button.setChecked(True)
        self.content_stack.setCurrentIndex(list(self._tab_buttons.keys()).index(title))


class BottomConsoleDock(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = False
        self.setFixedHeight(BOTTOM_DOCK_EXPANDED_HEIGHT)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 8)
        self.layout.setSpacing(8)

        self.header = QFrame(self)
        self.header.setObjectName("bottomDockHeader")
        self.header.setFixedHeight(BOTTOM_DOCK_COLLAPSED_HEIGHT)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 0, 8, 0)
        header_layout.setSpacing(8)
        self.title = QLabel("Console", self.header)
        self.title.setObjectName("bottomDockTitle")
        header_layout.addWidget(self.title)
        header_layout.addStretch(1)
        self.clear_button = QPushButton("Clear", self.header)
        self.clear_button.setObjectName("bottomConsoleClearButton")
        self.auto_scroll = QCheckBox("Auto Scroll", self.header)
        self.auto_scroll.setObjectName("bottomConsoleAutoScrollCheck")
        self.auto_scroll.setChecked(True)
        self.toggle_button = QPushButton("Collapse", self.header)
        self.toggle_button.setObjectName("bottomConsoleToggleButton")
        header_layout.addWidget(self.clear_button)
        header_layout.addWidget(self.auto_scroll)
        header_layout.addWidget(self.toggle_button)
        self.layout.addWidget(self.header)

        self.console_body_shell = QWidget(self)
        self.console_body_shell.setObjectName("bottomConsoleBodyShell")
        shell_layout = QHBoxLayout(self.console_body_shell)
        shell_layout.setContentsMargins(12, 0, 12, 0)
        shell_layout.setSpacing(0)

        self.console_body = QFrame(self.console_body_shell)
        self.console_body.setObjectName("bottomConsoleBody")
        self.console_body.setProperty("class", "card")
        body_layout = QVBoxLayout(self.console_body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.setSpacing(0)

        self.console = QTextEdit(self.console_body)
        self.console.setObjectName("consoleOutput")
        self.console.setReadOnly(True)
        self.console.setPlainText(
            "[INFO] Phase 11 static layout skeleton loaded.\n"
            "[INFO] This UI does not connect to hardware.\n"
            "[INFO] Later Codex tasks should wire logic without changing layout objectName values."
        )
        body_layout.addWidget(self.console, 1)
        shell_layout.addWidget(self.console_body, 1)
        self.layout.addWidget(self.console_body_shell, 1)

        self.clear_button.clicked.connect(self.clear)
        self.toggle_button.clicked.connect(self.toggle_collapsed)

    def clear(self) -> None:
        self.console.clear()

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.console_body_shell.setVisible(not self._collapsed)
        self.clear_button.setVisible(not self._collapsed)
        self.auto_scroll.setVisible(not self._collapsed)
        self.setFixedHeight(BOTTOM_DOCK_COLLAPSED_HEIGHT if self._collapsed else BOTTOM_DOCK_EXPANDED_HEIGHT)
        self.title.setText("Console")
        self.toggle_button.setText("Expand" if self._collapsed else "Collapse")


def ribbon_row() -> QWidget:
    row = QFrame()
    row.setObjectName("ribbonRow")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    return row


def ribbon_group(caption: str, buttons: Iterable[QToolButton]) -> QFrame:
    frame = QFrame()
    frame.setProperty("class", "ribbonGroup")
    frame.setMinimumWidth(80)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(8, 7, 8, 2)
    layout.setSpacing(2)

    button_row = QWidget(frame)
    row_layout = QHBoxLayout(button_row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(4)
    for button in buttons:
        row_layout.addWidget(button)
    layout.addWidget(button_row, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter)
    layout.addWidget(ribbon_caption(caption), 0, alignment=Qt.AlignBottom | Qt.AlignHCenter)
    return frame


def ribbon_caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "ribbonGroupCaption")
    label.setAlignment(Qt.AlignCenter)
    return label


def ribbon_button(text: str, object_name: str, *, checkable: bool = False) -> QToolButton:
    button = QToolButton()
    button.setObjectName(object_name)
    button.setProperty("class", "ribbonToolButton")
    button.setText(text)
    button.setIcon(make_placeholder_icon())
    button.setIconSize(QSize(28, 28))
    button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    button.setCheckable(checkable)
    button.setMinimumWidth(68)
    button.setFixedHeight(72)
    return button


def make_placeholder_icon(color: QColor | None = None) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color or QColor("#2f6fed"), 2)
    painter.setPen(pen)
    painter.setBrush(QColor("#eaf2ff"))
    painter.drawRoundedRect(6, 6, 20, 20, 5, 5)
    painter.drawLine(12, 16, 20, 16)
    painter.drawLine(16, 12, 16, 20)
    painter.end()
    return QIcon(pixmap)


def status_indicator_row(label: str, object_name: str) -> QWidget:
    row = QWidget()
    row.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignCenter)
    indicator = QLabel(row)
    indicator.setObjectName(object_name)
    indicator.setFixedSize(12, 12)
    indicator.setStyleSheet("border-radius: 6px; background: #9aa4b2;")
    layout.addWidget(indicator, 0, alignment=Qt.AlignVCenter)
    text = QLabel(label, row)
    text.setMinimumWidth(38)
    layout.addWidget(text, 0, alignment=Qt.AlignVCenter)
    return row


def nav_item(text: str, key: str | None = None) -> QTreeWidgetItem:
    item = QTreeWidgetItem([text])
    if key:
        item.setData(0, Qt.UserRole, key)
    return item


def add_field(layout: QGridLayout, row: int, label: str, value: str, value_object_name: str) -> None:
    label_widget = QLabel(label)
    label_widget.setProperty("class", "fieldLabel")
    value_widget = QLabel(value)
    value_widget.setObjectName(value_object_name)
    value_widget.setProperty("class", "valueLabel")
    value_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(label_widget, row, 0, alignment=Qt.AlignRight)
    layout.addWidget(value_widget, row, 1)


def create_page(title: str, object_name: str, *, scroll: bool = True) -> QWidget:
    outer = QFrame()
    outer.setObjectName(object_name)
    outer.setProperty("class", "pageFrame")
    outer_layout = QVBoxLayout(outer)
    outer_layout.setContentsMargins(16, 14, 16, 12)
    outer_layout.setSpacing(10)

    title_label = QLabel(title)
    title_label.setProperty("class", "pageTitle")
    outer_layout.addWidget(title_label, 0)

    if scroll:
        scroll_area = QScrollArea(outer)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        content = QWidget()
        content.setObjectName(f"{object_name}Content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area, 1)
        return outer

    return outer


def get_scroll_content(page: QWidget) -> QWidget:
    scroll_area = page.findChild(QScrollArea)
    assert scroll_area is not None
    return scroll_area.widget()


def card(title: str, object_name: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName(object_name)
    frame.setProperty("class", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(8)
    title_label = QLabel(title)
    title_label.setProperty("class", "cardTitle")
    layout.addWidget(title_label)
    return frame


class ExpanderCard(QFrame):
    """Simple settings expander used for collapsible configuration sections."""

    def __init__(self, title: str, object_name: str, *, expanded: bool = True) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setProperty("class", "expanderCard")

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.header = QToolButton(self)
        self.header.setObjectName(object_name + "Header")
        self.header.setProperty("class", "expanderHeader")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        outer_layout.addWidget(self.header)

        self.body = QFrame(self)
        self.body.setObjectName(object_name + "Body")
        self.body.setProperty("class", "expanderContent")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 10, 12, 12)
        self.body_layout.setSpacing(8)
        outer_layout.addWidget(self.body)

        self.header.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)


def expander_card(title: str, object_name: str, *, expanded: bool = True) -> ExpanderCard:
    return ExpanderCard(title, object_name, expanded=expanded)


def path_row(label: str, object_name: str, browse_name: str) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(QLabel(label))
    edit = QLineEdit()
    edit.setObjectName(object_name)
    edit.setPlaceholderText("Select file...")
    layout.addWidget(edit, 1)
    browse = QPushButton("Browse...")
    browse.setObjectName(browse_name)
    layout.addWidget(browse)
    return row


def summary_grid(
    fields: list[tuple[str, str]],
    columns: int = 2,
    *,
    label_min_width: int = 120,
    value_min_width: int = 120,
) -> QWidget:
    """Create a non-overlapping label/value grid.

    The static layout must remain readable when the main window is not
    maximized.  Minimum label/value widths prevent dense cards from squeezing
    fields into each other; enclosing scroll areas provide scrolling when the
    available width is smaller than the readable layout width.
    """

    widget = QWidget()
    layout = QGridLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(24)
    layout.setVerticalSpacing(6)

    for idx, (label, value) in enumerate(fields):
        row = idx // columns
        group_col = idx % columns
        label_col = group_col * 2
        value_col = label_col + 1

        label_widget = QLabel(label)
        label_widget.setProperty("class", "fieldLabel")
        label_widget.setMinimumWidth(label_min_width)
        label_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        value_widget = QLabel(value)
        value_widget.setObjectName(f"value_{label.strip(':').replace(' ', '_').replace('/', '_').lower()}")
        value_widget.setProperty("class", "valueLabel")
        value_widget.setMinimumWidth(value_min_width)
        value_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout.addWidget(label_widget, row, label_col, alignment=Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(value_widget, row, value_col, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        layout.setColumnMinimumWidth(label_col, label_min_width)
        layout.setColumnMinimumWidth(value_col, value_min_width)
        layout.setColumnStretch(value_col, 1)

    return widget


def create_program_page(cpu: str) -> QWidget:
    page = create_page(f"{cpu} Program", f"{cpu.lower()}ProgramPage")
    content = get_scroll_content(page)
    content.setMinimumWidth(PROGRAM_PAGE_MIN_WIDTH)
    layout = content.layout()

    app_card = card("App Image", f"{cpu.lower()}AppImageCard")
    app_card.setMinimumHeight(PROGRAM_APP_CARD_MIN_HEIGHT)
    app_card.layout().addWidget(path_row("App image path:", f"{cpu.lower()}AppImagePathEdit", f"{cpu.lower()}AppImageBrowseButton"))
    app_card.layout().addWidget(summary_grid([
        ("File name:", "—"),
        ("Entry point:", "—"),
        ("Image size:", "—"),
        ("CRC32:", "—"),
        ("Parse status:", "Not parsed"),
    ], columns=2, label_min_width=110, value_min_width=140))
    layout.addWidget(app_card, 0)

    options_card = card("Options", f"{cpu.lower()}OptionsCard")
    options_card.setMinimumHeight(72)
    options_layout = QHBoxLayout()
    options_layout.setContentsMargins(0, 0, 0, 0)
    options_layout.setSpacing(24)
    for text, name in [
        ("Force Load", "forceLoadCheck"),
        ("Auto Run after Load", "autoRunAfterLoadCheck"),
        ("Confirm App", "confirmAppCheck"),
    ]:
        checkbox = QCheckBox(text)
        checkbox.setObjectName(f"{cpu.lower()}{name}")
        options_layout.addWidget(checkbox)
    options_layout.addStretch(1)
    options_card.layout().addLayout(options_layout)
    layout.addWidget(options_card, 0)

    status_card = card("Status Summary", f"{cpu.lower()}StatusSummaryCard")
    status_card.setMinimumHeight(PROGRAM_STATUS_CARD_MIN_HEIGHT)
    status_card.layout().addWidget(summary_grid([
        ("Metadata Valid:", "Unknown"),
        ("Entry Point Valid:", "Unknown"),
        ("IMAGE_VALID:", "Unknown"),
        ("Flash App CRC32:", "—"),
        ("BOOT_ATTEMPT:", "Unknown"),
        ("Loaded Image Matches:", "Unknown"),
        ("APP_CONFIRMED:", "Unknown"),
        ("Confirmed Bootable:", "Unknown"),
    ], columns=2, label_min_width=150, value_min_width=130))
    layout.addWidget(status_card, 0)

    result_card = card("Details / Result", f"{cpu.lower()}DetailsResultCard")
    result_card.setMinimumHeight(PROGRAM_RESULT_CARD_MIN_HEIGHT)
    result_text = QTextEdit()
    result_text.setObjectName(f"{cpu.lower()}DetailsResultText")
    result_text.setReadOnly(True)
    result_text.setMinimumHeight(160)
    result_text.setPlainText("Operation details will appear here.")
    result_card.layout().addWidget(result_text, 1)
    layout.addWidget(result_card, 0)
    layout.addStretch(1)
    return page


def create_session_settings_page() -> QWidget:
    page = create_page("Session Settings", "sessionSettingsPage")
    content = get_scroll_content(page)
    content.setMinimumWidth(SETTINGS_PAGE_MIN_WIDTH)
    layout = content.layout()

    erase_card = expander_card("Erase Settings", "eraseSettingsCard", expanded=True)
    radio1 = QRadioButton("Necessary Sectors Only")
    radio1.setObjectName("eraseNecessarySectorsOnlyRadio")
    radio1.setChecked(True)
    radio2 = QRadioButton("Entire Flash")
    radio2.setObjectName("eraseEntireFlashRadio")
    erase_card.body_layout.addWidget(radio1)
    erase_card.body_layout.addWidget(radio2)
    layout.addWidget(erase_card, 0)
    layout.addStretch(1)
    layout.addWidget(action_bar([("Reload", "sessionSettingsReloadButton"), ("Save", "sessionSettingsSaveButton")]))
    return page


def create_global_settings_page() -> QWidget:
    page = create_page("Global Settings", "globalSettingsPage")
    content = get_scroll_content(page)
    content.setMinimumWidth(SETTINGS_PAGE_MIN_WIDTH)
    layout = content.layout()

    for section, fields in [
        ("Tool Paths", ["hex2000 path", "temporary directory", "generated file directory", "keep intermediate files"]),
        ("Flash Service", ["CPU1 service .out", "CPU1 service .map", "CPU2 service .out", "CPU2 service .map", "descriptor symbol name", "parsed descriptor address", "ABI", "capabilities"]),
        ("Default Transport", ["default transport", "SCI default port", "SCI default baud", "TX timeout", "RX timeout", "autobaud timeout"]),
        ("Logging", ["log directory", "log level", "auto scroll", "save OperationResult JSON", "export directory"]),
        ("GUI Behavior", ["restore last layout", "confirm before destructive operations", "confirm before Run"]),
    ]:
        section_card = expander_card(section, f"global{section.replace(' ', '')}Card", expanded=True)
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        for row, field in enumerate(fields):
            label = QLabel(f"{field}:")
            label.setProperty("class", "fieldLabel")
            label.setMinimumWidth(180)
            form.addWidget(label, row, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
            if field.startswith("keep") or field.startswith("auto scroll") or field.startswith("save OperationResult") or field.startswith("restore") or field.startswith("confirm"):
                widget = QCheckBox()
            else:
                widget = QLineEdit()
                widget.setMaximumWidth(PAGE_CONTENT_MAX_WIDTH)
            widget.setObjectName("global" + "".join(part.capitalize() for part in field.replace(".", " ").split()))
            form.addWidget(widget, row, 1)
        form.setColumnStretch(1, 1)
        section_card.body_layout.addLayout(form)
        layout.addWidget(section_card)
    layout.addStretch(1)
    layout.addWidget(action_bar([("Reload", "globalPageReloadButton"), ("Save", "globalPageSaveButton")]))
    return page


def action_bar(buttons: list[tuple[str, str]]) -> QWidget:
    bar = QWidget()
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch(1)
    for text, name in buttons:
        button = QPushButton(text)
        button.setObjectName(name)
        layout.addWidget(button)
    return bar


def create_advanced_page() -> QWidget:
    page = QFrame()
    page.setObjectName("advancedPage")
    page.setProperty("class", "pageFrame")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(16, 14, 16, 12)
    layout.setSpacing(10)
    title = QLabel("Advanced")
    title.setProperty("class", "pageTitle")
    layout.addWidget(title)

    tabs = QTabWidget(page)
    tabs.setObjectName("advancedTabs")
    tabs.setMinimumHeight(ADVANCED_TABS_MIN_HEIGHT)
    tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    tabs.addTab(create_diagnostics_tab(), "Diagnostics")
    tabs.addTab(create_flash_tab(), "Flash")
    tabs.addTab(create_metadata_tab(), "Metadata")
    tabs.addTab(create_execution_tab(), "Execution")
    tabs.addTab(create_ram_image_tab(), "RAM Image")
    layout.addWidget(tabs, 1)

    result_card = card("Result / Details", "advancedResultDetailsCard")
    result_card.setMinimumHeight(ADVANCED_RESULT_MIN_HEIGHT)
    result = QTextEdit()
    result.setObjectName("advancedResultDetailsText")
    result.setReadOnly(True)
    result.setMinimumHeight(64)
    result.setPlainText("Advanced operation details will appear here.")
    result_card.layout().addWidget(result, 1)
    layout.addWidget(result_card, 0)
    return page


def warning_banner(text: str) -> QWidget:
    banner = QFrame()
    banner.setProperty("class", "warningBanner")
    layout = QHBoxLayout(banner)
    layout.setContentsMargins(10, 6, 10, 6)
    label = QLabel("⚠ " + text)
    label.setProperty("class", "warningText")
    layout.addWidget(label)
    layout.addStretch(1)
    return banner


def advanced_scroll_tab(object_name: str, *, minimum_content_width: int = ADVANCED_TAB_MIN_WIDTH) -> tuple[QScrollArea, QVBoxLayout]:
    """Create an Advanced tab body that does not squeeze dense content.

    The Advanced pages contain two-column cards and action rows.  On a
    non-fullscreen window, fixed minimum content width with scrollbars is more
    readable than proportional squeezing.
    """

    scroll_area = QScrollArea()
    scroll_area.setObjectName(object_name)
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QFrame.NoFrame)
    scroll_area.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    content = QWidget()
    content.setObjectName(object_name + "Content")
    content.setMinimumWidth(minimum_content_width)
    content.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(10, 10, 10, 24)
    layout.setSpacing(10)
    scroll_area.setWidget(content)
    return scroll_area, layout


def two_column_grid(object_name: str) -> tuple[QWidget, QGridLayout]:
    grid_widget = QWidget()
    grid_widget.setObjectName(object_name)
    grid_layout = QGridLayout(grid_widget)
    grid_layout.setContentsMargins(0, 0, 0, 0)
    grid_layout.setSpacing(10)
    grid_layout.setColumnMinimumWidth(0, ADVANCED_TWO_COLUMN_MIN_WIDTH)
    grid_layout.setColumnMinimumWidth(1, ADVANCED_TWO_COLUMN_MIN_WIDTH)
    grid_layout.setColumnStretch(0, 1)
    grid_layout.setColumnStretch(1, 1)
    return grid_widget, grid_layout


def create_diagnostics_tab() -> QWidget:
    tab, layout = advanced_scroll_tab("diagnosticsTabScroll")
    layout.addWidget(action_button_card("Diagnostic Actions", ["Device", "Protocol", "Metadata", "Service", "Last Error"], "diagnostic"), 0)

    grid_widget, grid = two_column_grid("diagnosticsSummaryGrid")
    grid.addWidget(info_card("Device Info", ["Target CPU", "Device ID", "Bootloader version", "Build type", "Connection state"]), 0, 0)
    grid.addWidget(info_card("Protocol Info", ["Protocol version", "Supported commands", "Max payload words", "Word order", "Last sequence"]), 0, 1)
    grid.addWidget(info_card("Metadata Summary", ["Metadata valid", "IMAGE_VALID", "BOOT_ATTEMPT", "APP_CONFIRMED", "Entry point", "Confirmed bootable"]), 1, 0)
    grid.addWidget(info_card("Service Status", ["Service state", "Loaded CRC32", "ABI", "Capabilities", "Reuse eligible"]), 1, 1)
    grid.addWidget(info_card("Last Error", ["Error code", "Stage", "Message", "Details preview"]), 2, 0, 1, 2)
    layout.addWidget(grid_widget, 0)
    layout.addStretch(1)
    return tab


def create_flash_tab() -> QWidget:
    tab, layout = advanced_scroll_tab("flashTabScroll")
    layout.addWidget(warning_banner("Advanced Flash operations may modify Flash and metadata."), 0)
    layout.addWidget(action_button_card("Flash Actions", ["Erase", "Program", "Verify", "IMAGE\nVALID"], "flash"), 0)

    grid, grid_layout = two_column_grid("flashContextGrid")
    grid_layout.addWidget(info_card("Current Image Context", ["Target", "App Image", "File name", "Entry point", "Image size", "CRC32"]), 0, 0)
    grid_layout.addWidget(info_card("Flash Operation Context", ["Erase mode", "Flash range", "Metadata area", "Bootloader area", "Service state"]), 0, 1)
    layout.addWidget(grid, 0)
    layout.addWidget(notes_card(["Program only writes App image data.", "Verify only checks App image data.", "IMAGE_VALID is a separate metadata commit step.", "Erase mode is configured in Session Settings."]))
    layout.addStretch(1)
    return tab


def create_metadata_tab() -> QWidget:
    tab, layout = advanced_scroll_tab("metadataTabScroll")
    layout.addWidget(warning_banner("Advanced metadata operations affect boot decision records."), 0)
    layout.addWidget(action_button_card("Metadata Actions", ["Refresh", "BOOT\nATTEMPT", "APP\nCONFIRMED"], "metadata"), 0)

    grid, grid_layout = two_column_grid("metadataStateGrid")
    grid_layout.addWidget(info_card("Metadata State", ["Metadata Valid", "IMAGE_VALID", "BOOT_ATTEMPT", "APP_CONFIRMED", "Entry Point Valid", "Confirmed Bootable"]), 0, 0)
    grid_layout.addWidget(info_card("Image Binding", ["Current IMAGE_VALID sequence", "Target", "Entry point", "Image size", "Image CRC32", "Binding status"]), 0, 1)
    timeline = card("Record Timeline / Record Status", "metadataRecordTimelineCard")
    timeline.setMinimumHeight(96)
    timeline.layout().addWidget(QLabel("IMAGE_VALID  →  BOOT_ATTEMPT  →  APP_CONFIRMED\nvalid              exists             missing"))
    grid_layout.addWidget(timeline, 1, 0, 1, 2)
    layout.addWidget(grid, 0)
    layout.addWidget(notes_card(["BOOT_ATTEMPT must match the current IMAGE_VALID.", "APP_CONFIRMED must match the current IMAGE_VALID and BOOT_ATTEMPT.", "New IMAGE_VALID records invalidate old BOOT_ATTEMPT / APP_CONFIRMED records."]))
    layout.addStretch(1)
    return tab


def create_execution_tab() -> QWidget:
    tab, layout = advanced_scroll_tab("executionTabScroll")
    layout.addWidget(warning_banner("Execution operations may transfer control to the target App."), 0)
    layout.addWidget(action_button_card("Execution Actions", ["Run\nFlash App"], "execution"), 0)

    grid, grid_layout = two_column_grid("executionContextGrid")
    grid_layout.addWidget(info_card("Run Context", ["Target", "App image selected", "Flash app present", "Entry point", "Image CRC32", "Last run state"]), 0, 0)
    grid_layout.addWidget(info_card("Boot Decision State", ["Metadata Valid", "IMAGE_VALID", "BOOT_ATTEMPT", "APP_CONFIRMED", "Entry Point Valid", "Confirmed Bootable"]), 0, 1)
    grid_layout.addWidget(info_card("Entry Point / Image Identity", ["Entry point address", "Entry point valid", "Image size words", "Flash CRC32", "Loaded image CRC32", "Loaded Image Matches Flash"]), 1, 0, 1, 2)
    layout.addWidget(grid, 0)
    layout.addWidget(notes_card(["Run Flash App transfers control to the selected App entry."]))
    layout.addStretch(1)
    return tab


def create_ram_image_tab() -> QWidget:
    tab, layout = advanced_scroll_tab("ramImageTabScroll", minimum_content_width=ADVANCED_RAM_TAB_MIN_WIDTH)
    layout.addWidget(action_button_card("Operations", ["Load", "Run"], "ram"), 0)

    image_row = QWidget()
    image_row.setObjectName("ramImageCpuRow")
    image_row_layout = QHBoxLayout(image_row)
    image_row_layout.setContentsMargins(0, 0, 0, 0)
    image_row_layout.setSpacing(10)
    image_row_layout.addWidget(ram_cpu_image_card("CPU1 RAM Image", "ramCpu1"), 1)
    image_row_layout.addWidget(ram_cpu_image_card("CPU2 RAM Image", "ramCpu2"), 1)
    layout.addWidget(image_row, 0)
    layout.addStretch(1)
    return tab


def ram_cpu_image_card(title: str, prefix: str) -> QFrame:
    image_card = card(title, f"{prefix}ImageCard")
    image_card.setMinimumWidth(430)
    image_card.setMinimumHeight(210)
    image_card.layout().addWidget(path_row("Image path:", f"{prefix}ImagePathEdit", f"{prefix}ImageBrowseButton"))
    image_card.layout().addWidget(summary_grid([
        ("File name:", "—"),
        ("Entry point:", "—"),
        ("Load address:", "—"),
        ("Image size:", "—"),
        ("CRC32:", "—"),
        ("Parse status:", "Not parsed"),
    ], columns=1, label_min_width=110, value_min_width=180))
    return image_card


def action_button_card(title: str, labels: list[str], prefix: str) -> QWidget:
    frame = card(title, f"{prefix}ActionsCard")
    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)
    for label in labels:
        name = prefix + "".join(part.capitalize() for part in label.replace("\n", " ").split()) + "Button"
        row_layout.addWidget(ribbon_button(label, name))
    row_layout.addStretch(1)
    frame.layout().addWidget(row)
    return frame


def info_card(title: str, labels: list[str]) -> QWidget:
    frame = card(title, title.replace(" ", "").lower() + "Card")
    fields = [(label + ":", "—" if label != "Last Error" else "No error") for label in labels]
    frame.layout().addWidget(summary_grid(fields, columns=1))
    return frame


def notes_card(notes: list[str]) -> QWidget:
    frame = card("Notes", "notesCard")
    for note in notes:
        frame.layout().addWidget(QLabel("• " + note))
    return frame


def create_memory_page(cpu: str) -> QWidget:
    page = QFrame()
    page.setObjectName(f"{cpu.lower()}MemoryPage")
    page.setProperty("class", "pageFrame")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(16, 14, 16, 12)
    layout.setSpacing(10)
    title = QLabel(f"Memory {cpu}")
    title.setProperty("class", "pageTitle")
    layout.addWidget(title)

    control = QFrame(page)
    control.setObjectName(f"{cpu.lower()}MemoryControlBar")
    control.setFixedHeight(MEMORY_CONTROL_BAR_HEIGHT)
    control_layout = QHBoxLayout(control)
    control_layout.setContentsMargins(0, 0, 0, 0)
    control_layout.setSpacing(8)
    control_layout.addWidget(QLabel("Address:"))
    address = QLineEdit("0x080000")
    address.setObjectName(f"{cpu.lower()}MemoryAddressEdit")
    address.setFixedWidth(130)
    control_layout.addWidget(address)
    control_layout.addWidget(QLabel("Rows:"))
    rows = QLineEdit(str(MEMORY_DEFAULT_ROWS))
    rows.setObjectName(f"{cpu.lower()}MemoryRowsEdit")
    rows.setFixedWidth(70)
    control_layout.addWidget(rows)
    refresh = QPushButton("Refresh")
    refresh.setObjectName(f"{cpu.lower()}MemoryRefreshButton")
    control_layout.addWidget(refresh)
    control_layout.addStretch(1)
    export = QPushButton("Export")
    export.setObjectName(f"{cpu.lower()}MemoryExportButton")
    control_layout.addWidget(export)
    layout.addWidget(control)

    table = QTableWidget(MEMORY_DEFAULT_ROWS, MEMORY_WORD_COLUMNS + 1, page)
    table.setObjectName(f"{cpu.lower()}MemoryTable")
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    headers = ["Address"] + [f"+{i:X}" for i in range(MEMORY_WORD_COLUMNS)]
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
    table.setColumnWidth(0, 110)
    for col in range(1, MEMORY_WORD_COLUMNS + 1):
        table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Stretch)
    for row in range(MEMORY_DEFAULT_ROWS):
        address_value = 0x080000 + row * 0x10
        address_item = QTableWidgetItem(f"0x{address_value:06X}")
        address_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 0, address_item)
        for col in range(1, MEMORY_WORD_COLUMNS + 1):
            item = QTableWidgetItem("????")
            item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, col, item)
    layout.addWidget(table, 1)
    return page


def create_logs_page() -> QWidget:
    page = QFrame()
    page.setObjectName("logsPage")
    page.setProperty("class", "pageFrame")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(16, 14, 16, 12)
    layout.setSpacing(10)
    title = QLabel("Logs")
    title.setProperty("class", "pageTitle")
    layout.addWidget(title)

    filter_bar = QFrame(page)
    filter_bar.setObjectName("logsFilterBar")
    filter_layout = QHBoxLayout(filter_bar)
    filter_layout.setContentsMargins(0, 0, 0, 0)
    filter_layout.setSpacing(8)
    filter_layout.addWidget(QLabel("Level:"))
    level = QComboBox()
    level.setObjectName("logsLevelCombo")
    level.addItems(["All", "Debug", "Info", "Warning", "Error"])
    filter_layout.addWidget(level)
    filter_layout.addWidget(QLabel("Source:"))
    source = QComboBox()
    source.setObjectName("logsSourceCombo")
    source.addItems(["All", "Session", "Transport", "Program", "Flash", "Metadata", "RAM", "Memory", "GUI"])
    filter_layout.addWidget(source)
    filter_layout.addWidget(QLabel("Search:"))
    search = QLineEdit()
    search.setObjectName("logsSearchEdit")
    filter_layout.addWidget(search, 1)
    for text, name in [("Clear", "logsClearFilterButton"), ("Export", "logsExportButton"), ("Open Folder", "logsOpenFolderButton")]:
        button = QPushButton(text)
        button.setObjectName(name)
        filter_layout.addWidget(button)
    layout.addWidget(filter_bar)

    splitter = QSplitter(Qt.Vertical, page)
    splitter.setObjectName("logsVerticalSplitter")

    table = QTableWidget(6, 6, splitter)
    table.setObjectName("logsTable")
    table.setHorizontalHeaderLabels(["Time", "Level", "Source", "Operation", "Stage", "Message"])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
    table.setColumnWidth(0, 145)
    for col, width in [(1, 80), (2, 110), (3, 130), (4, 130)]:
        table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
        table.setColumnWidth(col, width)
    table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
    rows = [
        ("10:21:03.123", "INFO", "Session", "Connect", "Done", "Connected to CPU1."),
        ("10:21:05.421", "INFO", "Flash", "LoadImage", "Erase", "Erase image area started."),
        ("10:21:06.884", "INFO", "Flash", "LoadImage", "Program", "Program image data."),
        ("10:21:08.006", "WARNING", "Metadata", "Run", "Validate", "BOOT_ATTEMPT required before confirm."),
        ("10:21:10.224", "INFO", "Execution", "Run", "Done", "RUN command sent."),
        ("10:21:13.509", "ERROR", "Metadata", "Confirm", "Validate", "APP_CONFIRMED rejected: no matching BOOT_ATTEMPT."),
    ]
    for r, row_values in enumerate(rows):
        for c, value in enumerate(row_values):
            table.setItem(r, c, QTableWidgetItem(value))
    splitter.addWidget(table)

    detail = card("Detail", "logsDetailCard")
    detail.setMinimumHeight(LOG_DETAIL_DEFAULT_HEIGHT)
    detail_text = QTextEdit()
    detail_text.setObjectName("logsDetailText")
    detail_text.setReadOnly(True)
    detail_text.setPlainText("Selected log entry / OperationResult details will appear here.")
    detail.layout().addWidget(detail_text)
    splitter.addWidget(detail)
    splitter.setSizes([WINDOW_DEFAULT_SIZE[1] - LOG_DETAIL_DEFAULT_HEIGHT, LOG_DETAIL_DEFAULT_HEIGHT])
    layout.addWidget(splitter, 1)
    return page
