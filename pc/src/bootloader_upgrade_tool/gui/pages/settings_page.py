"""Static Phase 11 Settings page.

The page presents current-session and global configuration layouts only. It does
not persist settings, scan/open COM ports, create sessions, call operations,
parse image files, or access hardware.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import (
    PAGE_BLOCK_SPACING,
    PAGE_MARGINS,
    SETTINGS_ACTION_BAR_HEIGHT,
    SETTINGS_ACTION_BUTTON_MINIMUM_SIZE,
    SETTINGS_CATEGORY_DEFAULT_WIDTH,
    SETTINGS_CATEGORY_ITEM_HEIGHT,
    SETTINGS_CATEGORY_MAXIMUM_WIDTH,
    SETTINGS_CATEGORY_MINIMUM_WIDTH,
    SETTINGS_CONTENT_MINIMUM_WIDTH,
    SETTINGS_SCOPE_TAB_HEIGHT,
    SETTINGS_SCOPE_TAB_MINIMUM_WIDTH,
    SETTINGS_SPLITTER_HANDLE_WIDTH,
)
from ..ui_state import set_ui_role, set_ui_variant
from ..widgets.card import NoticeBanner, SectionCard
from ..widgets.form_rows import LabeledFieldRow, PathFieldRow, ReadOnlyValueRow
from ..widgets.input_controls import IndicatorComboBox, IndicatorSpinBox
from ..widgets.page_header import PageHeader

CURRENT_CATEGORIES: Final = ("Connection", "Target", "Program Options")
GLOBAL_CATEGORIES: Final = (
    "Tools",
    "Flash Service",
    "Transport",
    "Logging",
    "GUI Behavior",
)


@dataclass(frozen=True)
class _CategorySpec:
    title: str
    factory: Callable[[QWidget], QWidget]


class _SettingsCategoryPage(QScrollArea):
    """One internally scrollable settings category."""

    def __init__(
        self,
        title: str,
        *,
        object_name: str,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.content = QWidget(self)
        self.content.setObjectName(f"{object_name}Content")
        self.content.setMinimumWidth(SETTINGS_CONTENT_MINIMUM_WIDTH)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 8, 0)
        self.content_layout.setSpacing(PAGE_BLOCK_SPACING)

        self.title_label = QLabel(title, self.content)
        set_ui_role(self.title_label, "sectionTitle")
        self.content_layout.addWidget(self.title_label)
        self.setWidget(self.content)

    def add_card(self, card: SectionCard, stretch: int = 0) -> None:
        self.content_layout.addWidget(card, stretch)

    def finish(self) -> None:
        self.content_layout.addStretch(1)


class _SettingsScopePage(QWidget):
    """Category list, category stack, and fixed action bar for one scope."""

    categoryChanged = Signal(str)

    def __init__(
        self,
        scope_key: str,
        categories: Sequence[_CategorySpec],
        actions: Sequence[tuple[str, str, str]],
        *,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.scope_key = scope_key
        prefix = f"{scope_key}Settings"
        self.setObjectName(f"{prefix}Page")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName(f"{prefix}Splitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(SETTINGS_SPLITTER_HANDLE_WIDTH)
        root.addWidget(self.splitter, 1)

        self.category_list = QListWidget(self.splitter)
        self.category_list.setObjectName(f"{prefix}CategoryList")
        self.category_list.setMinimumWidth(SETTINGS_CATEGORY_MINIMUM_WIDTH)
        self.category_list.setMaximumWidth(SETTINGS_CATEGORY_MAXIMUM_WIDTH)
        self.category_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.category_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.splitter.addWidget(self.category_list)

        self.category_stack = QStackedWidget(self.splitter)
        self.category_stack.setObjectName(f"{prefix}ContentStack")
        self.category_stack.setMinimumWidth(SETTINGS_CONTENT_MINIMUM_WIDTH)
        self.splitter.addWidget(self.category_stack)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes(
            [SETTINGS_CATEGORY_DEFAULT_WIDTH, SETTINGS_CONTENT_MINIMUM_WIDTH]
        )

        self.category_pages: dict[str, QWidget] = {}
        for spec in categories:
            item = QListWidgetItem(spec.title)
            item.setSizeHint(QSize(SETTINGS_CATEGORY_DEFAULT_WIDTH, SETTINGS_CATEGORY_ITEM_HEIGHT))
            self.category_list.addItem(item)
            page = spec.factory(self.category_stack)
            self.category_pages[spec.title] = page
            self.category_stack.addWidget(page)

        self.category_list.currentRowChanged.connect(self._on_category_changed)
        self.category_list.setCurrentRow(0)

        self.action_bar = QFrame(self)
        self.action_bar.setObjectName(f"{prefix}ActionBar")
        self.action_bar.setFixedHeight(SETTINGS_ACTION_BAR_HEIGHT)
        action_layout = QHBoxLayout(self.action_bar)
        action_layout.setContentsMargins(12, 8, 12, 8)
        action_layout.setSpacing(8)
        action_layout.addStretch(1)

        self.action_buttons: dict[str, QPushButton] = {}
        for object_name, text, variant in actions:
            button = QPushButton(text, self.action_bar)
            button.setObjectName(object_name)
            button.setMinimumSize(*SETTINGS_ACTION_BUTTON_MINIMUM_SIZE)
            set_ui_variant(button, variant)
            button.setEnabled(False)
            action_layout.addWidget(button)
            self.action_buttons[object_name] = button
        root.addWidget(self.action_bar)

    def select_category(self, title: str) -> None:
        titles = [self.category_list.item(i).text() for i in range(self.category_list.count())]
        try:
            row = titles.index(title)
        except ValueError as exc:
            raise KeyError(f"unknown {self.scope_key} settings category: {title!r}") from exc
        self.category_list.setCurrentRow(row)

    def _on_category_changed(self, row: int) -> None:
        if not 0 <= row < self.category_stack.count():
            return
        self.category_stack.setCurrentIndex(row)
        item = self.category_list.item(row)
        if item is not None:
            self.categoryChanged.emit(item.text())


class SettingsPage(QWidget):
    """Approved static Settings page with Current and Global scopes."""

    scopeChanged = Signal(str)

    def __init__(
        self,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        set_ui_role(self, "page")
        self._icon_manager = icon_manager or IconManager()

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(PAGE_BLOCK_SPACING)

        self.header = PageHeader(
            "Settings",
            description=(
                "Review current-session configuration and global defaults. "
                "Tool paths apply to the current run and are not persisted."
            ),
            object_name="settingsPageHeader",
            parent=self,
        )
        root.addWidget(self.header)

        self.content_container = QWidget(self)
        self.content_container.setObjectName("settingsContentContainer")
        self.content_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.content_container.setMinimumWidth(
            SETTINGS_CATEGORY_MINIMUM_WIDTH
            + SETTINGS_SPLITTER_HANDLE_WIDTH
            + SETTINGS_CONTENT_MINIMUM_WIDTH
        )
        content_layout = QVBoxLayout(self.content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        self.scope_tabs = QTabBar(self.content_container)
        self.scope_tabs.setObjectName("settingsScopeTabs")
        self.scope_tabs.setFixedHeight(SETTINGS_SCOPE_TAB_HEIGHT)
        self.scope_tabs.setMinimumWidth(2 * SETTINGS_SCOPE_TAB_MINIMUM_WIDTH)
        self.scope_tabs.setExpanding(False)
        self.scope_tabs.setDrawBase(False)
        self.scope_tabs.setStyleSheet(
            "QTabBar#settingsScopeTabs::tab {"
            f" min-width: {SETTINGS_SCOPE_TAB_MINIMUM_WIDTH}px;"
            " min-height: 24px; max-height: 24px; padding: 5px 14px; }"
        )
        self.scope_tabs.addTab("Current Configuration")
        self.scope_tabs.addTab("Global Configuration")
        content_layout.addWidget(self.scope_tabs, 0, Qt.AlignmentFlag.AlignLeft)

        self.scope_stack = QStackedWidget(self.content_container)
        self.scope_stack.setObjectName("settingsContentStack")
        content_layout.addWidget(self.scope_stack, 1)

        self.current_scope = _SettingsScopePage(
            "current",
            (
                _CategorySpec("Connection", self._create_current_connection),
                _CategorySpec("Target", self._create_current_target),
                _CategorySpec("Program Options", self._create_current_program_options),
            ),
            (
                ("resetCurrentButton", "Reset Current", "secondary"),
                ("applyCurrentButton", "Apply Current", "primary"),
            ),
            parent=self.scope_stack,
        )
        self.global_scope = _SettingsScopePage(
            "global",
            (
                _CategorySpec("Tools", self._create_global_tools),
                _CategorySpec("Flash Service", self._create_global_flash_service),
                _CategorySpec("Transport", self._create_global_transport),
                _CategorySpec("Logging", self._create_global_logging),
                _CategorySpec("GUI Behavior", self._create_global_gui_behavior),
            ),
            (
                ("reloadGlobalButton", "Reload Global", "secondary"),
                ("saveGlobalButton", "Save Global", "primary"),
            ),
            parent=self.scope_stack,
        )
        self.scope_stack.addWidget(self.current_scope)
        self.scope_stack.addWidget(self.global_scope)
        for title, page in self.global_scope.category_pages.items():
            page.setEnabled(title == "Tools")
        self.keep_sci8_txt.setEnabled(False)
        self.scope_tabs.currentChanged.connect(self._set_scope_index)
        self.scope_tabs.setCurrentIndex(0)

        root.addWidget(self.content_container, 1)

    @property
    def current_scope_key(self) -> str:
        return "current" if self.scope_stack.currentIndex() == 0 else "global"

    def set_scope(self, scope: str) -> None:
        normalized = scope.strip().lower()
        if normalized not in {"current", "global"}:
            raise ValueError("scope must be 'current' or 'global'")
        self.scope_tabs.setCurrentIndex(0 if normalized == "current" else 1)

    def _set_scope_index(self, index: int) -> None:
        if index not in {0, 1}:
            return
        self.scope_stack.setCurrentIndex(index)
        self.scopeChanged.emit("current" if index == 0 else "global")

    def set_connection_mirror(self, port: str, baudrate: int, target_key: str | None = None) -> None:
        """Mirror Operate Ribbon values without creating another input source."""

        self.current_port_edit.setText(port)
        self.current_baud_combo.setCurrentText(str(baudrate))
        target = target_key.upper() if target_key in {"cpu1", "cpu2"} else "Not identified"
        self.current_target_combo.setCurrentText(target)
        profile = self.findChild(QLabel, "currentTargetProfileValue")
        if profile is not None:
            profile.setText(target)

    def set_timeout_controls_enabled(self, enabled: bool) -> None:
        for control in (
            self.current_tx_timeout,
            self.current_rx_timeout,
            self.current_autobaud_timeout,
        ):
            control.setEnabled(bool(enabled))

    # Current configuration -------------------------------------------------
    def _create_current_connection(self, parent: QWidget) -> QWidget:
        page = self._category_page("Connection", "currentConnectionPage", parent)
        card = self._card("SCI / RS232 Connection", page.content)
        self.current_transport_combo = self._combo(
            ["SCI / RS232"], "currentTransportCombo", card.body
        )
        card.add_widget(self._row("Transport", self.current_transport_combo, card.body))

        self.current_port_edit = self._line_edit(
            "", "Select or enter a COM port in the Operate Ribbon", "currentPortEdit", card.body
        )
        self.current_port_edit.setReadOnly(True)
        card.add_widget(self._row("Port", self.current_port_edit, card.body))

        self.current_baud_combo = self._combo(
            ["9600", "19200", "38400", "57600", "115200"],
            "currentBaudCombo",
            card.body,
        )
        self.current_baud_combo.setEnabled(False)
        card.add_widget(self._row("Baud", self.current_baud_combo, card.body))

        self.current_tx_timeout = self._spin(1000, "currentTxTimeoutSpin", card.body, 1)
        self.current_rx_timeout = self._spin(1000, "currentRxTimeoutSpin", card.body, 1)
        self.current_autobaud_timeout = self._spin(
            5000, "currentAutobaudTimeoutSpin", card.body, 1
        )
        card.add_widget(self._row("TX timeout (ms)", self.current_tx_timeout, card.body))
        card.add_widget(self._row("RX timeout (ms)", self.current_rx_timeout, card.body))
        card.add_widget(
            self._row("Autobaud timeout (ms)", self.current_autobaud_timeout, card.body)
        )
        page.add_card(card)
        page.finish()
        return page

    def _create_current_target(self, parent: QWidget) -> QWidget:
        page = self._category_page("Target", "currentTargetPage", parent)
        card = self._card("Active Target", page.content)
        self.current_target_combo = self._combo(
            ["Not identified", "CPU1", "CPU2"], "currentTargetCombo", card.body
        )
        self.current_target_combo.setEnabled(False)
        card.add_widget(self._row("Target", self.current_target_combo, card.body))
        card.add_widget(
            ReadOnlyValueRow(
                "Device",
                "TMS320F28377D",
                value_object_name="currentDeviceValue",
                object_name="currentDeviceRow",
                parent=card.body,
            )
        )
        card.add_widget(
            ReadOnlyValueRow(
                "Target profile",
                "Not identified",
                value_object_name="currentTargetProfileValue",
                object_name="currentTargetProfileRow",
                parent=card.body,
            )
        )
        card.add_widget(
            ReadOnlyValueRow(
                "CPU2 runtime",
                "Discovery supported; upgrade workflow disabled",
                value_object_name="currentCpu2AvailabilityValue",
                object_name="currentCpu2AvailabilityRow",
                parent=card.body,
            )
        )
        page.add_card(card)
        page.finish()
        return page

    def _create_current_program_options(self, parent: QWidget) -> QWidget:
        page = self._category_page(
            "Program Options", "currentProgramOptionsPage", parent
        )
        card = self._card("Program Workflow Defaults", page.content)
        self.current_force_load = self._check("Force Load", "currentForceLoadCheck", card.body)
        self.current_auto_run = self._check(
            "Auto Run after Load", "currentAutoRunCheck", card.body
        )
        self.current_confirm_app = self._check(
            "Confirm App", "currentConfirmAppCheck", card.body
        )
        self.current_confirm_app.setEnabled(False)
        card.add_widget(self._row("Force reload", self.current_force_load, card.body))
        card.add_widget(self._row("Run after load", self.current_auto_run, card.body))
        card.add_widget(
            self._row(
                "Confirm after run",
                self.current_confirm_app,
                card.body,
                helper=(
                    "Reserved. Current confirmed-only workflow requires explicit "
                    "APP_CONFIRMED after a successful trial run."
                ),
            )
        )
        page.add_card(card)
        page.finish()
        return page

    # Global configuration --------------------------------------------------
    def _create_global_tools(self, parent: QWidget) -> QWidget:
        page = self._category_page("Tools", "globalToolsPage", parent)
        card = self._card("C2000 Image Tools", page.content)
        self.hex2000_path = self._path(
            "hex2000 path", "globalHex2000PathEdit", "globalHex2000BrowseButton", card.body
        )
        self.output_directory = self._path(
            "Output directory",
            "globalOutputDirectoryEdit",
            "globalOutputDirectoryBrowseButton",
            card.body,
        )
        self.keep_sci8_txt = self._check(
            "Keep generated SCI8 TXT", "globalKeepSci8TxtCheck", card.body
        )
        card.add_widget(self.hex2000_path)
        card.add_widget(self.output_directory)
        card.add_widget(self._row("Intermediate files", self.keep_sci8_txt, card.body))
        page.add_card(card)
        page.finish()
        return page

    def _create_global_flash_service(self, parent: QWidget) -> QWidget:
        page = self._category_page(
            "Flash Service", "globalFlashServicePage", parent
        )
        cpu1 = self._card("CPU1 Flash Service", page.content)
        self.cpu1_service_image = self._path(
            "Service image",
            "globalCpu1ServiceImageEdit",
            "globalCpu1ServiceImageBrowseButton",
            cpu1.body,
        )
        self.cpu1_service_map = self._path(
            "Service map",
            "globalCpu1ServiceMapEdit",
            "globalCpu1ServiceMapBrowseButton",
            cpu1.body,
        )
        self.cpu1_descriptor_symbol = self._line_edit(
            "",
            "Descriptor symbol from map/symbol data",
            "globalCpu1DescriptorSymbolEdit",
            cpu1.body,
        )
        cpu1.add_widget(self.cpu1_service_image)
        cpu1.add_widget(self.cpu1_service_map)
        cpu1.add_widget(
            self._row("Descriptor symbol", self.cpu1_descriptor_symbol, cpu1.body)
        )
        cpu1.add_widget(
            ReadOnlyValueRow(
                "Descriptor address",
                "Resolved from map/symbol; never hardcoded",
                value_object_name="globalCpu1DescriptorAddressValue",
                object_name="globalCpu1DescriptorAddressRow",
                parent=cpu1.body,
            )
        )
        page.add_card(cpu1)

        cpu2 = self._card("CPU2 Flash Service", page.content)
        self.cpu2_service_image = self._path(
            "Service image",
            "globalCpu2ServiceImageEdit",
            "globalCpu2ServiceImageBrowseButton",
            cpu2.body,
        )
        self.cpu2_service_map = self._path(
            "Service map",
            "globalCpu2ServiceMapEdit",
            "globalCpu2ServiceMapBrowseButton",
            cpu2.body,
        )
        self.cpu2_descriptor_symbol = self._line_edit(
            "",
            "CPU2 runtime is deferred",
            "globalCpu2DescriptorSymbolEdit",
            cpu2.body,
        )
        for widget in (
            self.cpu2_service_image,
            self.cpu2_service_map,
            self.cpu2_descriptor_symbol,
        ):
            widget.setEnabled(False)
        cpu2.add_widget(self.cpu2_service_image)
        cpu2.add_widget(self.cpu2_service_map)
        cpu2.add_widget(
            self._row("Descriptor symbol", self.cpu2_descriptor_symbol, cpu2.body)
        )
        cpu2.add_widget(
            ReadOnlyValueRow(
                "Descriptor address",
                "Unavailable until CPU2 integration",
                value_object_name="globalCpu2DescriptorAddressValue",
                object_name="globalCpu2DescriptorAddressRow",
                parent=cpu2.body,
            )
        )
        page.add_card(cpu2)
        page.finish()
        return page

    def _create_global_transport(self, parent: QWidget) -> QWidget:
        page = self._category_page("Transport", "globalTransportPage", parent)
        serial_card = self._card("SCI / RS232 Defaults", page.content)
        self.global_baud_combo = self._combo(
            ["9600", "19200", "38400", "57600", "115200"],
            "globalBaudCombo",
            serial_card.body,
        )
        self.global_tx_timeout = self._spin(1000, "globalTxTimeoutSpin", serial_card.body)
        self.global_rx_timeout = self._spin(1000, "globalRxTimeoutSpin", serial_card.body)
        self.global_autobaud_timeout = self._spin(
            5000, "globalAutobaudTimeoutSpin", serial_card.body
        )
        serial_card.add_widget(self._row("Default baud", self.global_baud_combo, serial_card.body))
        serial_card.add_widget(self._row("TX timeout (ms)", self.global_tx_timeout, serial_card.body))
        serial_card.add_widget(self._row("RX timeout (ms)", self.global_rx_timeout, serial_card.body))
        serial_card.add_widget(
            self._row("Autobaud timeout (ms)", self.global_autobaud_timeout, serial_card.body)
        )
        page.add_card(serial_card)

        tcp_card = self._card("TCP / W5300", page.content)
        tcp_notice = NoticeBanner(
            "Deferred transport",
            "TCP is visible for architecture review but disabled until the CPU1 SCI path is complete.",
            state="unavailable",
            object_name="globalTcpDeferredBanner",
            parent=tcp_card.body,
        )
        tcp_card.add_widget(tcp_notice)
        tcp_card.setEnabled(False)
        page.add_card(tcp_card)
        page.finish()
        return page

    def _create_global_logging(self, parent: QWidget) -> QWidget:
        page = self._category_page("Logging", "globalLoggingPage", parent)
        card = self._card("Logging Defaults", page.content)
        self.log_level_combo = self._combo(
            ["INFO", "DEBUG", "WARNING", "ERROR"], "globalLogLevelCombo", card.body
        )
        self.log_directory = self._path(
            "Log directory",
            "globalLogDirectoryEdit",
            "globalLogDirectoryBrowseButton",
            card.body,
        )
        self.log_file_count = self._spin(20, "globalLogFileCountSpin", card.body, 1, 999)
        self.console_block_count = self._spin(
            5000, "globalConsoleBlockCountSpin", card.body, 100, 100000
        )
        self.export_structured_results = self._check(
            "Export structured operation results",
            "globalStructuredResultCheck",
            card.body,
        )
        card.add_widget(self._row("Log level", self.log_level_combo, card.body))
        card.add_widget(self.log_directory)
        card.add_widget(self._row("Retained log files", self.log_file_count, card.body))
        card.add_widget(self._row("Console block limit", self.console_block_count, card.body))
        card.add_widget(
            self._row("Result export", self.export_structured_results, card.body)
        )
        page.add_card(card)
        page.finish()
        return page

    def _create_global_gui_behavior(self, parent: QWidget) -> QWidget:
        page = self._category_page(
            "GUI Behavior", "globalGuiBehaviorPage", parent
        )
        card = self._card("Window and Safety Behavior", page.content)
        self.start_page_combo = self._combo(
            ["Program / CPU1", "Settings", "Logs"], "globalStartPageCombo", card.body
        )
        self.remember_window = self._check(
            "Remember window geometry", "globalRememberWindowCheck", card.body, True
        )
        self.restore_splitters = self._check(
            "Restore splitter positions", "globalRestoreSplittersCheck", card.body, True
        )
        self.auto_scroll_console = self._check(
            "Auto-scroll Console", "globalAutoScrollConsoleCheck", card.body, True
        )
        self.confirm_destructive = self._check(
            "Require confirmation for destructive operations",
            "globalConfirmDestructiveCheck",
            card.body,
            True,
        )
        self.confirm_destructive.setEnabled(False)
        card.add_widget(self._row("Start page", self.start_page_combo, card.body))
        card.add_widget(self._row("Window geometry", self.remember_window, card.body))
        card.add_widget(self._row("Splitter state", self.restore_splitters, card.body))
        card.add_widget(self._row("Console", self.auto_scroll_console, card.body))
        card.add_widget(
            self._row(
                "Safety confirmations",
                self.confirm_destructive,
                card.body,
                helper="Mandatory safety behavior; not configurable in static layout.",
            )
        )
        page.add_card(card)
        page.finish()
        return page

    # Helpers ---------------------------------------------------------------
    def _category_page(self, title: str, object_name: str, parent: QWidget) -> _SettingsCategoryPage:
        return _SettingsCategoryPage(title, object_name=object_name, parent=parent)

    def _card(self, title: str, parent: QWidget) -> SectionCard:
        return SectionCard(title, object_name=_object_name(title, "Card"), parent=parent)

    def _row(
        self,
        label: str,
        editor: QWidget,
        parent: QWidget,
        *,
        helper: str = "",
    ) -> LabeledFieldRow:
        return LabeledFieldRow(
            label,
            editor,
            helper_text=helper,
            object_name=f"{editor.objectName()}Row",
            parent=parent,
        )

    def _line_edit(
        self,
        text: str,
        placeholder: str,
        object_name: str,
        parent: QWidget,
    ) -> QLineEdit:
        edit = QLineEdit(text, parent)
        edit.setObjectName(object_name)
        edit.setPlaceholderText(placeholder)
        return edit

    def _combo(self, values: Sequence[str], object_name: str, parent: QWidget) -> QComboBox:
        combo = IndicatorComboBox(parent, icon_manager=self._icon_manager)
        combo.setObjectName(object_name)
        combo.addItems(list(values))
        return combo

    def _spin(
        self,
        value: int,
        object_name: str,
        parent: QWidget,
        minimum: int = 0,
        maximum: int = 600000,
    ) -> QSpinBox:
        spin = IndicatorSpinBox(parent, icon_manager=self._icon_manager)
        spin.setObjectName(object_name)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setGroupSeparatorShown(True)
        return spin

    def _check(
        self,
        text: str,
        object_name: str,
        parent: QWidget,
        checked: bool = False,
    ) -> QCheckBox:
        checkbox = QCheckBox(text, parent)
        checkbox.setObjectName(object_name)
        checkbox.setChecked(checked)
        return checkbox

    def _path(
        self,
        label: str,
        edit_name: str,
        button_name: str,
        parent: QWidget,
    ) -> PathFieldRow:
        return PathFieldRow(
            label,
            placeholder="Select a path during controller integration",
            icon_manager=self._icon_manager,
            edit_object_name=edit_name,
            button_object_name=button_name,
            object_name=f"{edit_name}Row",
            parent=parent,
        )

    @staticmethod
    def _disable_combo_item(combo: QComboBox, index: int) -> None:
        model = combo.model()
        if isinstance(model, QStandardItemModel):
            item = model.item(index)
            if item is not None:
                item.setEnabled(False)


def _object_name(text: str, suffix: str) -> str:
    words = "".join(ch if ch.isalnum() else " " for ch in text).split()
    return "settings" + "".join(word[:1].upper() + word[1:] for word in words) + suffix


__all__ = ["CURRENT_CATEGORIES", "GLOBAL_CATEGORIES", "SettingsPage"]
