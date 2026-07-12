"""Static Phase 11 Batch 7 Advanced page.

The page exposes approved diagnostics, Flash, metadata, execution, and RAM-image
layout contracts only.  It does not import or invoke operations, sessions,
transports, protocol clients, image preparation, DSP code, or hardware access.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import (
    ADVANCED_BUTTON_HEIGHT,
    ADVANCED_BUTTON_ICON_SIZE,
    ADVANCED_FIELD_HEIGHT,
    ADVANCED_FIELD_LABEL_WIDTH,
    ADVANCED_RESULT_MINIMUM_HEIGHT,
    ADVANCED_SPLITTER_HANDLE_WIDTH,
    ADVANCED_SPLITTER_INITIAL_SIZES,
    ADVANCED_TAB_BAR_HEIGHT,
    ADVANCED_TAB_ICON_SIZE,
    ADVANCED_TAB_MINIMUM_WIDTH,
    ADVANCED_TABS_MINIMUM_HEIGHT,
    PAGE_BLOCK_SPACING,
    PAGE_MARGINS,
)
from ..ui_state import set_ui_role, set_ui_variant
from ..widgets.card import SectionCard
from ..widgets.input_controls import IndicatorComboBox
from ..widgets.page_header import PageHeader
from ..widgets.sector_selector import FlashSectorOption, SectorMaskSelector

ADVANCED_TAB_LABELS: Final = (
    "Diagnostics",
    "Flash",
    "Metadata",
    "Execution",
    "RAM Image",
)

ERASE_SCOPE_LABELS: Final = (
    "Required App Sectors",
    "Entire Application Region",
    "Custom Sector Mask",
)

ADVANCED_IMAGE_SUMMARY_LABEL_WIDTH: Final = 96

CPU1_FLASH_SECTOR_OPTIONS: Final = (
    FlashSectorOption("A", 0x080000, 0x081FFF, 0, protected=True),
    FlashSectorOption("B", 0x082000, 0x083FFF, 1),
    FlashSectorOption("C", 0x084000, 0x085FFF, 2),
    FlashSectorOption("D", 0x086000, 0x087FFF, 3),
    FlashSectorOption("E", 0x088000, 0x08FFFF, 4),
    FlashSectorOption("F", 0x090000, 0x097FFF, 5),
    FlashSectorOption("G", 0x098000, 0x09FFFF, 6),
    FlashSectorOption("H", 0x0A0000, 0x0A7FFF, 7),
    FlashSectorOption("I", 0x0A8000, 0x0AFFFF, 8),
    FlashSectorOption("J", 0x0B0000, 0x0B7FFF, 9),
    FlashSectorOption("K", 0x0B8000, 0x0BFFFF, 10),
    FlashSectorOption("L", 0x0BA000, 0x0BBFFF, 11),
    FlashSectorOption("M", 0x0BC000, 0x0BDFFF, 12),
)


class AdvancedPage(QWidget):
    """Advanced workspace; actions emit intent for the runtime binding."""

    statusRequested = Signal(str)

    def __init__(
        self,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("advancedPage")
        set_ui_role(self, "page")
        self._icon_manager = icon_manager or IconManager()

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(PAGE_BLOCK_SPACING)

        self.header = PageHeader(
            "Advanced",
            description=(
                "Review read-only diagnostics for the currently connected target."
            ),
            object_name="advancedPageHeader",
            parent=self,
        )
        root.addWidget(self.header)

        self.content_container = QWidget(self)
        self.content_container.setObjectName("advancedContentContainer")
        self.content_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        content_layout = QHBoxLayout(self.content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.vertical_splitter = QSplitter(
            Qt.Orientation.Vertical,
            self.content_container,
        )
        self.vertical_splitter.setObjectName("advancedVerticalSplitter")
        self.vertical_splitter.setChildrenCollapsible(False)
        self.vertical_splitter.setHandleWidth(ADVANCED_SPLITTER_HANDLE_WIDTH)
        content_layout.addWidget(self.vertical_splitter)

        self.tabs = QTabWidget(self.vertical_splitter)
        self.tabs.setObjectName("advancedTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setMinimumHeight(ADVANCED_TABS_MINIMUM_HEIGHT)
        self.tabs.tabBar().setObjectName("advancedTabBar")
        self.tabs.tabBar().setFixedHeight(ADVANCED_TAB_BAR_HEIGHT)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setStyleSheet(
            "QTabBar#advancedTabBar::tab {"
            f" min-width: {ADVANCED_TAB_MINIMUM_WIDTH}px;"
            " min-height: 24px; max-height: 24px; padding: 5px 12px; }"
        )
        self.vertical_splitter.addWidget(self.tabs)

        self.diagnostics_tab = self._create_diagnostics_tab()
        self.flash_tab = self._create_flash_tab()
        self.metadata_tab = self._create_metadata_tab()
        self.execution_tab = self._create_execution_tab()
        self.ram_image_tab = self._create_ram_image_tab()

        for page, semantic_icon, label in (
            (self.diagnostics_tab, "advanced.tab.diagnostics", "Diagnostics"),
            (self.flash_tab, "advanced.tab.flash", "Flash"),
            (self.metadata_tab, "advanced.tab.metadata", "Metadata"),
            (self.execution_tab, "advanced.tab.execution", "Execution"),
            (self.ram_image_tab, "advanced.tab.ram_image", "RAM Image"),
        ):
            self.tabs.addTab(
                page,
                self._icon_manager.icon(
                    semantic_icon,
                    size=ADVANCED_TAB_ICON_SIZE,
                ),
                label,
            )

        self.result_card = SectionCard(
            "Shared Result",
            subtitle=(
                "Read-only local result area shared by all Advanced tabs; "
                "not a hardware activity log."
            ),
            semantic_icon="program.result.card",
            icon_manager=self._icon_manager,
            object_name="advancedSharedResultCard",
            parent=self.vertical_splitter,
        )
        self.result_card.setMinimumHeight(ADVANCED_RESULT_MINIMUM_HEIGHT)
        self.result_copy_button = self._header_tool_button(
            self.result_card,
            "Copy",
            "console.copy",
            "advancedResultCopyButton",
        )
        self.result_clear_button = self._header_tool_button(
            self.result_card,
            "Clear",
            "logs.clear",
            "advancedResultClearButton",
        )
        self.result_output = QPlainTextEdit(self.result_card.body)
        self.result_output.setObjectName("advancedResultOutput")
        self.result_output.setReadOnly(True)
        self.result_output.setUndoRedoEnabled(False)
        self.result_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.result_output.document().setMaximumBlockCount(1000)
        self.result_output.setPlainText(
            "Static layout preview.\nNo diagnostic, Flash, metadata, execution, "
            "or RAM operation has been executed."
        )
        self.result_card.add_widget(self.result_output, 1)
        self.vertical_splitter.addWidget(self.result_card)
        self.vertical_splitter.setStretchFactor(0, 68)
        self.vertical_splitter.setStretchFactor(1, 32)
        self.vertical_splitter.setSizes(list(ADVANCED_SPLITTER_INITIAL_SIZES))

        self.result_copy_button.clicked.connect(self._copy_result)
        self.result_clear_button.clicked.connect(self.result_output.clear)

        root.addWidget(self.content_container, 1)

    def set_status_controls_enabled(self, enabled: bool) -> None:
        for button in (
            self.read_device_info_button,
            self.read_protocol_info_button,
            self.get_last_error_button,
            self.refresh_status_button,
        ):
            button.setEnabled(bool(enabled))

    def set_connected_target(self, text: str) -> None:
        self.diagnostics_target_value.setText(text)

    def set_diagnostic_value(self, name: str, text: str) -> None:
        try:
            value = {
                "target": self.diagnostics_target_value,
                "device": self.diagnostics_device_value,
                "device_id": self.diagnostics_device_id_value,
                "cpu_id": self.diagnostics_cpu_id_value,
                "protocol_version": self.diagnostics_protocol_version_value,
                "last_error": self.diagnostics_last_error_value,
            }[name]
        except KeyError as exc:
            raise KeyError(f"unknown diagnostic value: {name!r}") from exc
        value.setText(text)

    def set_metadata_summary(self, values: dict[str, object]) -> None:
        for name, value in values.items():
            widget = self.metadata_summary_values.get(name)
            if widget is not None:
                widget.setText(str(value))

    def set_cpu1_flash_image_summary(
        self,
        *,
        target: str = "CPU1 / TMS320F28377D",
        entry_point: str = "—",
        image_size: str = "—",
        crc32: str = "—",
    ) -> None:
        """Update the CPU1 Flash image summary."""

        self._set_image_summary_values(
            self.cpu1_flash_target_value,
            self.cpu1_flash_entry_point_value,
            self.cpu1_flash_image_size_value,
            self.cpu1_flash_crc32_value,
            target=target,
            entry_point=entry_point,
            image_size=image_size,
            crc32=crc32,
        )

    def set_cpu2_flash_image_summary(
        self,
        *,
        target: str = "CPU2 / TMS320F28377D",
        entry_point: str = "—",
        image_size: str = "—",
        crc32: str = "—",
    ) -> None:
        """Update the CPU2 Flash image summary."""

        self._set_image_summary_values(
            self.cpu2_flash_target_value,
            self.cpu2_flash_entry_point_value,
            self.cpu2_flash_image_size_value,
            self.cpu2_flash_crc32_value,
            target=target,
            entry_point=entry_point,
            image_size=image_size,
            crc32=crc32,
        )

    def set_flash_image_summary(
        self,
        *,
        target: str = "CPU1 / TMS320F28377D",
        entry_point: str = "—",
        image_size: str = "—",
        crc32: str = "—",
    ) -> None:
        """Compatibility wrapper for the former CPU1-only Flash summary."""

        self.set_cpu1_flash_image_summary(
            target=target,
            entry_point=entry_point,
            image_size=image_size,
            crc32=crc32,
        )

    def set_cpu1_ram_image_summary(
        self,
        *,
        target: str = "CPU1 / TMS320F28377D",
        entry_point: str = "—",
        image_size: str = "—",
        crc32: str = "—",
    ) -> None:
        """Update the CPU1 RAM image summary."""

        self._set_image_summary_values(
            self.cpu1_ram_target_value,
            self.cpu1_ram_entry_point_value,
            self.cpu1_ram_image_size_value,
            self.cpu1_ram_crc32_value,
            target=target,
            entry_point=entry_point,
            image_size=image_size,
            crc32=crc32,
        )

    def set_cpu2_ram_image_summary(
        self,
        *,
        target: str = "CPU2 / TMS320F28377D",
        entry_point: str = "—",
        image_size: str = "—",
        crc32: str = "—",
    ) -> None:
        """Update the CPU2 RAM image summary."""

        self._set_image_summary_values(
            self.cpu2_ram_target_value,
            self.cpu2_ram_entry_point_value,
            self.cpu2_ram_image_size_value,
            self.cpu2_ram_crc32_value,
            target=target,
            entry_point=entry_point,
            image_size=image_size,
            crc32=crc32,
        )

    def set_ram_image_summary(
        self,
        *,
        target: str = "CPU1 / TMS320F28377D",
        entry_point: str = "—",
        image_size: str = "—",
        crc32: str = "—",
    ) -> None:
        """Compatibility wrapper for the former CPU1-only RAM summary."""

        self.set_cpu1_ram_image_summary(
            target=target,
            entry_point=entry_point,
            image_size=image_size,
            crc32=crc32,
        )

    # Diagnostics ---------------------------------------------------------
    def _create_diagnostics_tab(self) -> QScrollArea:
        scroll, body, layout = self._tab_page("advancedDiagnosticsTab")

        identity = self._card(
            "Device and Protocol",
            "Unknown until a future controller reads the connected target.",
            "advancedDiagnosticsIdentityCard",
            body,
        )
        self.diagnostics_values: dict[str, QLabel] = {}
        for label, value, suffix, key in (
            ("Target", "Not connected", "Target", "target"),
            ("Device", "—", "Device", "device"),
            ("Device ID", "—", "DeviceId", "device_id"),
            ("CPU ID", "—", "CpuId", "cpu_id"),
            ("Protocol version", "—", "ProtocolVersion", "protocol_version"),
            ("Last error", "—", "LastError", "last_error"),
        ):
            row = self._value_row(label, value, f"advancedDiagnostics{suffix}Row", identity.body)
            value_widget = row.findChild(QLabel, f"advancedDiagnostics{suffix}RowValue")
            assert value_widget is not None
            self.diagnostics_values[key] = value_widget
            setattr(self, f"diagnostics_{key}_value", value_widget)
            identity.add_widget(row)
        layout.addWidget(identity)

        action_card = self._card(
            "Read-only Diagnostics",
            "Read device identity, protocol information, and the last reported error.",
            "advancedDiagnosticsActionsCard",
            body,
        )
        action_row = QHBoxLayout()
        self.read_device_info_button = self._action_button(
            "Read Device Info",
            "advanced.diagnostics.device_info",
            "advancedReadDeviceInfoButton",
            action_card.body,
        )
        self.read_protocol_info_button = self._action_button(
            "Read Protocol Info",
            "advanced.diagnostics.protocol_info",
            "advancedReadProtocolInfoButton",
            action_card.body,
        )
        self.get_last_error_button = self._action_button(
            "Get Last Error",
            "advanced.diagnostics.last_error",
            "advancedGetLastErrorButton",
            action_card.body,
        )
        for button in (
            self.read_device_info_button,
            self.read_protocol_info_button,
            self.get_last_error_button,
        ):
            action_row.addWidget(button)
        for button, operation in (
            (self.read_device_info_button, "get_device_info"),
            (self.read_protocol_info_button, "get_protocol_info"),
            (self.get_last_error_button, "get_last_error"),
        ):
            button.clicked.connect(
                lambda _checked=False, operation=operation: self.statusRequested.emit(operation)
            )
        action_row.addStretch(1)
        action_card.add_widget(self._layout_host(action_row, "advancedDiagnosticsActions", action_card.body))
        layout.addWidget(action_card)
        layout.addStretch(1)
        return scroll

    # Flash ---------------------------------------------------------------
    def _create_flash_tab(self) -> QScrollArea:
        scroll, body, layout = self._tab_page("advancedFlashTab")

        image_card = self._card(
            "Flash App Images",
            (
                "Keep CPU1 and CPU2 image paths and parsed identity information available. "
                "Flash operations use the image associated with the currently connected target."
            ),
            "advancedFlashImageCard",
            body,
        )
        self.flash_image_selectors = QWidget(image_card.body)
        self.flash_image_selectors.setObjectName("advancedFlashImageSelectors")
        selector_layout = QGridLayout(self.flash_image_selectors)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setHorizontalSpacing(PAGE_BLOCK_SPACING)
        selector_layout.setVerticalSpacing(0)
        selector_layout.setColumnStretch(0, 1)
        selector_layout.setColumnStretch(1, 1)

        (
            self.cpu1_flash_image_panel,
            self.cpu1_flash_image_edit,
            self.cpu1_flash_browse_button,
            self.cpu1_flash_path_host,
            self.cpu1_flash_image_summary_grid,
            self.cpu1_flash_target_value,
            self.cpu1_flash_entry_point_value,
            self.cpu1_flash_image_size_value,
            self.cpu1_flash_crc32_value,
        ) = self._create_target_image_selector(
            target="CPU1",
            image_label="Flash App Image",
            object_prefix="advancedCpu1Flash",
            semantic_icon="advanced.flash.browse_image",
            parent=self.flash_image_selectors,
        )
        (
            self.cpu2_flash_image_panel,
            self.cpu2_flash_image_edit,
            self.cpu2_flash_browse_button,
            self.cpu2_flash_path_host,
            self.cpu2_flash_image_summary_grid,
            self.cpu2_flash_target_value,
            self.cpu2_flash_entry_point_value,
            self.cpu2_flash_image_size_value,
            self.cpu2_flash_crc32_value,
        ) = self._create_target_image_selector(
            target="CPU2",
            image_label="Flash App Image",
            object_prefix="advancedCpu2Flash",
            semantic_icon="advanced.flash.browse_image",
            parent=self.flash_image_selectors,
        )
        selector_layout.addWidget(self.cpu1_flash_image_panel, 0, 0)
        selector_layout.addWidget(self.cpu2_flash_image_panel, 0, 1)
        image_card.add_widget(self.flash_image_selectors)

        # Compatibility aliases for the former CPU1-only Flash selector and summary.
        self.flash_image_edit = self.cpu1_flash_image_edit
        self.flash_browse_button = self.cpu1_flash_browse_button
        self.flash_image_summary_grid = self.cpu1_flash_image_summary_grid
        self.flash_target_value = self.cpu1_flash_target_value
        self.flash_entry_point_value = self.cpu1_flash_entry_point_value
        self.flash_image_size_value = self.cpu1_flash_image_size_value
        self.flash_crc32_value = self.cpu1_flash_crc32_value
        layout.addWidget(image_card)

        scope_card = self._card(
            "Erase Scope",
            "Select only the current target application region required by the operation.",
            "advancedEraseScopeCard",
            body,
        )
        self.erase_scope_combo = IndicatorComboBox(parent=scope_card.body)
        self.erase_scope_combo.setObjectName("advancedEraseScopeCombo")
        self.erase_scope_combo.addItems(list(ERASE_SCOPE_LABELS))
        self.erase_scope_combo.setMinimumHeight(ADVANCED_FIELD_HEIGHT)
        scope_card.add_widget(
            self._field_row(
                "Scope",
                self.erase_scope_combo,
                "advancedEraseScopeRow",
                scope_card.body,
            )
        )
        self.custom_sector_selector = SectorMaskSelector(
            CPU1_FLASH_SECTOR_OPTIONS,
            object_name="advancedCustomSectorMaskSelector",
            parent=scope_card.body,
        )
        self.custom_sector_selector.setMinimumHeight(ADVANCED_FIELD_HEIGHT)
        self.custom_sector_selector.setEnabled(False)
        # Compatibility alias retained for code that referenced the former
        # manually editable line edit.
        self.custom_sector_mask_edit = self.custom_sector_selector.summary_edit
        self.custom_sector_mask_edit.setObjectName("advancedCustomSectorMaskEdit")
        self.custom_sector_mask_button = self.custom_sector_selector.edit_button
        scope_card.add_widget(
            self._field_row(
                "Custom mask",
                self.custom_sector_selector,
                "advancedCustomSectorMaskRow",
                scope_card.body,
            )
        )
        self.erase_scope_combo.currentTextChanged.connect(
            lambda text: self.custom_sector_selector.setEnabled(
                text == "Custom Sector Mask"
            )
        )
        sector_notice = QLabel(
            "Sector A is always protected. Bootloader or reserved-sector erase "
            "requests must be rejected as safety errors.",
            scope_card.body,
        )
        sector_notice.setObjectName("advancedSectorAProtectionNotice")
        sector_notice.setWordWrap(True)
        set_ui_role(sector_notice, "helperText")
        scope_card.add_widget(sector_notice)
        layout.addWidget(scope_card)

        operation_card = self._card(
            "Low-level Flash Operations",
            "SERVICE_ATTACH remains internal to operation-layer Flash and metadata calls.",
            "advancedFlashOperationsCard",
            body,
        )
        self.erase_button = self._action_button(
            "Erase",
            "advanced.flash.erase",
            "advancedEraseButton",
            operation_card.body,
            variant="dangerGhost",
        )
        self.program_only_button = self._action_button(
            "Program Only",
            "advanced.flash.program",
            "advancedProgramOnlyButton",
            operation_card.body,
        )
        self.verify_only_button = self._action_button(
            "Verify Only",
            "advanced.flash.verify",
            "advancedVerifyOnlyButton",
            operation_card.body,
        )
        operation_row = QHBoxLayout()
        operation_row.addWidget(self.erase_button)
        operation_row.addWidget(self.program_only_button)
        operation_row.addWidget(self.verify_only_button)
        operation_row.addStretch(1)
        operation_card.add_widget(self._layout_host(operation_row, "advancedFlashActionRow", operation_card.body))
        verify_notice = QLabel(
            "Verify Only performs verification only; it does not write IMAGE_VALID.",
            operation_card.body,
        )
        verify_notice.setObjectName("advancedVerifyOnlyNotice")
        verify_notice.setWordWrap(True)
        set_ui_role(verify_notice, "helperText")
        operation_card.add_widget(verify_notice)
        layout.addWidget(operation_card)
        layout.addStretch(1)
        return scroll

    # Metadata ------------------------------------------------------------
    def _create_metadata_tab(self) -> QScrollArea:
        scroll, body, layout = self._tab_page("advancedMetadataTab")
        self.metadata_card = self._card(
            "Current-image Metadata",
            (
                "Refresh reads the current target metadata summary. "
                "Write actions remain explicit and bind to the current IMAGE_VALID identity."
            ),
            "advancedMetadataCard",
            body,
        )
        self.metadata_summary_grid = QWidget(self.metadata_card.body)
        self.metadata_summary_grid.setObjectName("advancedMetadataSummaryGrid")
        summary_layout = QGridLayout(self.metadata_summary_grid)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setHorizontalSpacing(PAGE_BLOCK_SPACING)
        summary_layout.setVerticalSpacing(0)
        summary_layout.setColumnStretch(0, 1)
        summary_layout.setColumnStretch(1, 1)

        self.metadata_summary_values: dict[str, QLabel] = {}
        for row, column, label, value, suffix, key in (
            (0, 0, "Metadata Valid", "Unknown", "MetadataValid", "metadata_valid"),
            (0, 1, "IMAGE_VALID", "Unknown", "ImageValid", "image_valid"),
            (1, 0, "Flash App CRC32", "Unknown", "FlashAppCrc32", "image_crc32"),
            (1, 1, "BOOT_ATTEMPT", "Unknown", "BootAttempt", "boot_attempt"),
            (2, 0, "Entry Point", "Unknown", "EntryPoint", "entry_point"),
            (2, 1, "APP_CONFIRMED", "Unknown", "AppConfirmed", "app_confirmed"),
        ):
            value_row = self._value_row(label, value, f"advancedMetadata{suffix}Row", self.metadata_summary_grid)
            summary_layout.addWidget(value_row, row, column)
            summary_value = value_row.findChild(QLabel, f"advancedMetadata{suffix}RowValue")
            assert summary_value is not None
            self.metadata_summary_values[key] = summary_value

        self.metadata_card.add_widget(self.metadata_summary_grid)

        self.refresh_status_button = self._action_button(
            "Refresh Status",
            "advanced.diagnostics.refresh_status",
            "advancedRefreshStatusButton",
            self.metadata_card.body,
        )
        self.write_image_valid_button = self._action_button(
            "Write IMAGE_VALID",
            "advanced.metadata.image_valid",
            "advancedWriteImageValidButton",
            self.metadata_card.body,
        )
        self.write_boot_attempt_button = self._action_button(
            "Write BOOT_ATTEMPT",
            "advanced.metadata.boot_attempt",
            "advancedWriteBootAttemptButton",
            self.metadata_card.body,
        )
        self.write_app_confirmed_button = self._action_button(
            "Write APP_CONFIRMED",
            "advanced.metadata.app_confirmed",
            "advancedWriteAppConfirmedButton",
            self.metadata_card.body,
        )
        row = QHBoxLayout()
        for button in (
            self.refresh_status_button,
            self.write_image_valid_button,
            self.write_boot_attempt_button,
            self.write_app_confirmed_button,
        ):
            row.addWidget(button)
        row.addStretch(1)
        self.metadata_card.add_widget(
            self._layout_host(
                row,
                "advancedMetadataActionRow",
                self.metadata_card.body,
            )
        )
        self.refresh_status_button.clicked.connect(
            lambda _checked=False: self.statusRequested.emit("get_metadata_summary")
        )

        note = QLabel(
            "BOOT_ATTEMPT and APP_CONFIRMED cannot reuse records from an older image. "
            "APP_CONFIRMED additionally requires the matching IMAGE_VALID and an "
            "existing BOOT_ATTEMPT.",
            self.metadata_card.body,
        )
        note.setObjectName("advancedMetadataBindingNotice")
        note.setWordWrap(True)
        set_ui_role(note, "helperText")
        self.metadata_card.add_widget(note)
        layout.addWidget(self.metadata_card)
        layout.addStretch(1)
        return scroll

    # Execution -----------------------------------------------------------
    def _create_execution_tab(self) -> QScrollArea:
        scroll, body, layout = self._tab_page("advancedExecutionTab")
        card = self._card(
            "Flash App Execution",
            "Run and reset controls remain disabled until capability and policy integration.",
            "advancedExecutionCard",
            body,
        )
        self.execution_entry_point = QLineEdit(card.body)
        self.execution_entry_point.setObjectName("advancedExecutionEntryPointEdit")
        self.execution_entry_point.setText("—")
        self.execution_entry_point.setReadOnly(True)
        self.execution_entry_point.setMinimumHeight(ADVANCED_FIELD_HEIGHT)
        card.add_widget(
            self._field_row(
                "Entry point",
                self.execution_entry_point,
                "advancedExecutionEntryPointRow",
                card.body,
            )
        )
        self.run_flash_app_button = self._action_button(
            "Run Flash App",
            "advanced.execution.run_flash_app",
            "advancedRunFlashAppButton",
            card.body,
        )
        self.reset_target_button = self._action_button(
            "Reset Target",
            "advanced.execution.reset_target",
            "advancedResetTargetButton",
            card.body,
            variant="secondary",
        )
        row = QHBoxLayout()
        row.setContentsMargins(ADVANCED_FIELD_LABEL_WIDTH + 10, 0, 0, 0)
        row.addWidget(self.run_flash_app_button)
        row.addWidget(self.reset_target_button)
        row.addStretch(1)
        card.add_widget(self._layout_host(row, "advancedExecutionActionRow", card.body))
        reset_note = QLabel(
            "Reset Target is a disabled placeholder until a supported capability "
            "and explicit reset policy are available.",
            card.body,
        )
        reset_note.setObjectName("advancedResetTargetNotice")
        reset_note.setWordWrap(True)
        set_ui_role(reset_note, "helperText")
        card.add_widget(reset_note)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    # RAM Image -----------------------------------------------------------
    def _create_ram_image_tab(self) -> QScrollArea:
        scroll, body, layout = self._tab_page("advancedRamImageTab")

        image_card = self._card(
            "RAM Images",
            (
                "Keep CPU1 and CPU2 RAM image paths and parsed identity information available. "
                "Operations apply to the image associated with the currently connected target."
            ),
            "advancedRamImageCard",
            body,
        )
        self.ram_image_selectors = QWidget(image_card.body)
        self.ram_image_selectors.setObjectName("advancedRamImageSelectors")
        selector_layout = QGridLayout(self.ram_image_selectors)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setHorizontalSpacing(PAGE_BLOCK_SPACING)
        selector_layout.setVerticalSpacing(0)
        selector_layout.setColumnStretch(0, 1)
        selector_layout.setColumnStretch(1, 1)

        (
            self.cpu1_ram_image_panel,
            self.cpu1_ram_image_edit,
            self.cpu1_ram_browse_button,
            self.cpu1_ram_path_host,
            self.cpu1_ram_image_summary_grid,
            self.cpu1_ram_target_value,
            self.cpu1_ram_entry_point_value,
            self.cpu1_ram_image_size_value,
            self.cpu1_ram_crc32_value,
        ) = self._create_target_image_selector(
            target="CPU1",
            image_label="RAM Image",
            object_prefix="advancedCpu1Ram",
            semantic_icon="advanced.ram.browse_image",
            parent=self.ram_image_selectors,
        )
        (
            self.cpu2_ram_image_panel,
            self.cpu2_ram_image_edit,
            self.cpu2_ram_browse_button,
            self.cpu2_ram_path_host,
            self.cpu2_ram_image_summary_grid,
            self.cpu2_ram_target_value,
            self.cpu2_ram_entry_point_value,
            self.cpu2_ram_image_size_value,
            self.cpu2_ram_crc32_value,
        ) = self._create_target_image_selector(
            target="CPU2",
            image_label="RAM Image",
            object_prefix="advancedCpu2Ram",
            semantic_icon="advanced.ram.browse_image",
            parent=self.ram_image_selectors,
        )
        selector_layout.addWidget(self.cpu1_ram_image_panel, 0, 0)
        selector_layout.addWidget(self.cpu2_ram_image_panel, 0, 1)
        image_card.add_widget(self.ram_image_selectors)

        # Compatibility aliases for the former CPU1-only RAM summary.
        self.ram_image_summary_grid = self.cpu1_ram_image_summary_grid
        self.ram_target_value = self.cpu1_ram_target_value
        self.ram_entry_point_value = self.cpu1_ram_entry_point_value
        self.ram_image_size_value = self.cpu1_ram_image_size_value
        self.ram_crc32_value = self.cpu1_ram_crc32_value
        layout.addWidget(image_card)

        operation_card = self._card(
            "RAM Operations",
            (
                "Load, CRC check, and run remain separate operations for the "
                "currently connected target."
            ),
            "advancedRamOperationsCard",
            body,
        )
        self.ram_load_button = self._action_button(
            "Load",
            "advanced.ram.load_image",
            "advancedRamLoadButton",
            operation_card.body,
        )
        self.ram_crc_button = self._action_button(
            "Check CRC",
            "advanced.ram.check_crc",
            "advancedRamCheckCrcButton",
            operation_card.body,
        )
        self.ram_run_button = self._action_button(
            "Run",
            "advanced.ram.run_image",
            "advancedRamRunButton",
            operation_card.body,
        )
        operation_row = QHBoxLayout()
        operation_row.setContentsMargins(0, 0, 0, 0)
        operation_row.setSpacing(8)
        operation_row.addWidget(self.ram_load_button)
        operation_row.addWidget(self.ram_crc_button)
        operation_row.addWidget(self.ram_run_button)
        operation_row.addStretch(1)
        self.ram_action_host = self._layout_host(
            operation_row,
            "advancedRamActionRow",
            operation_card.body,
        )
        operation_card.add_widget(self.ram_action_host)

        current_target_note = QLabel(
            (
                "The selected CPU1 or CPU2 image is resolved from the currently "
                "connected target; the operation buttons are not target-specific."
            ),
            operation_card.body,
        )
        current_target_note.setObjectName("advancedRamCurrentTargetNotice")
        current_target_note.setWordWrap(True)
        set_ui_role(current_target_note, "helperText")
        operation_card.add_widget(current_target_note)
        layout.addWidget(operation_card)

        retention_note = QLabel(
            (
                "RUN_RAM / RAM_RUN source and tests remain retained. CPU2 runtime "
                "integration is deferred until the CPU1 GUI workflow is complete."
            ),
            body,
        )
        retention_note.setObjectName("advancedRamRetentionNotice")
        retention_note.setWordWrap(True)
        set_ui_role(retention_note, "helperText")
        layout.addWidget(retention_note)
        layout.addStretch(1)
        return scroll

    def _create_target_image_selector(
        self,
        *,
        target: str,
        image_label: str,
        object_prefix: str,
        semantic_icon: str,
        parent: QWidget,
    ) -> tuple[
        QWidget,
        QLineEdit,
        QToolButton,
        QWidget,
        QWidget,
        QLabel,
        QLabel,
        QLabel,
        QLabel,
    ]:
        panel = QWidget(parent)
        panel.setObjectName(f"{object_prefix}ImagePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        label = QLabel(f"{target} {image_label}", panel)
        label.setObjectName(f"{object_prefix}ImageLabel")
        set_ui_role(label, "fieldLabel")
        layout.addWidget(label)

        path = QLineEdit(panel)
        path.setObjectName(f"{object_prefix}ImageEdit")
        prepared = "prepared " if image_label == "Flash App Image" else ""
        path.setPlaceholderText(f"Select a {prepared}{target} {image_label}")
        path.setMinimumHeight(ADVANCED_FIELD_HEIGHT)

        browse = self._file_select_button(
            f"{object_prefix}BrowseButton",
            semantic_icon,
            tooltip=f"Select {target} {image_label}",
            parent=panel,
        )
        browse.setEnabled(False)
        path_host = self._editor_with_button(
            path,
            browse,
            f"{object_prefix}ImageField",
            panel,
        )
        path_host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(path_host)

        (
            summary_grid,
            target_value,
            entry_point_value,
            image_size_value,
            crc32_value,
        ) = self._create_image_summary_grid(
            object_prefix=object_prefix,
            target=f"{target} / TMS320F28377D",
            parent=panel,
        )
        layout.addWidget(summary_grid)
        return (
            panel,
            path,
            browse,
            path_host,
            summary_grid,
            target_value,
            entry_point_value,
            image_size_value,
            crc32_value,
        )

    @staticmethod
    def _set_image_summary_values(
        target_value: QLabel,
        entry_point_value: QLabel,
        image_size_value: QLabel,
        crc32_value: QLabel,
        *,
        target: str,
        entry_point: str,
        image_size: str,
        crc32: str,
    ) -> None:
        target_value.setText(target)
        entry_point_value.setText(entry_point)
        image_size_value.setText(image_size)
        crc32_value.setText(crc32)

    def _create_image_summary_grid(
        self,
        *,
        object_prefix: str,
        target: str,
        parent: QWidget,
    ) -> tuple[QWidget, QLabel, QLabel, QLabel, QLabel]:
        host = QWidget(parent)
        host.setObjectName(f"{object_prefix}ImageSummaryGrid")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(PAGE_BLOCK_SPACING)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        target_value = self._inline_summary_field(
            "Target",
            target,
            f"{object_prefix}TargetValue",
            host,
            label_width=ADVANCED_IMAGE_SUMMARY_LABEL_WIDTH,
            spacing=10,
        )
        entry_point_value = self._inline_summary_field(
            "Entry Point",
            "—",
            f"{object_prefix}EntryPointValue",
            host,
            label_width=ADVANCED_IMAGE_SUMMARY_LABEL_WIDTH,
            spacing=10,
        )
        image_size_value = self._inline_summary_field(
            "Image Size",
            "—",
            f"{object_prefix}ImageSizeValue",
            host,
            label_width=ADVANCED_IMAGE_SUMMARY_LABEL_WIDTH,
            spacing=10,
        )
        crc32_value = self._inline_summary_field(
            "CRC32",
            "—",
            f"{object_prefix}Crc32Value",
            host,
            label_width=ADVANCED_IMAGE_SUMMARY_LABEL_WIDTH,
            spacing=10,
        )
        grid.addWidget(target_value.parentWidget(), 0, 0)
        grid.addWidget(entry_point_value.parentWidget(), 0, 1)
        grid.addWidget(image_size_value.parentWidget(), 1, 0)
        grid.addWidget(crc32_value.parentWidget(), 1, 1)
        return (
            host,
            target_value,
            entry_point_value,
            image_size_value,
            crc32_value,
        )

    # Shared helpers ------------------------------------------------------
    def _tab_page(
        self,
        object_name: str,
    ) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        scroll = QScrollArea(self.tabs)
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(scroll)
        body.setObjectName(f"{object_name}Body")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(PAGE_BLOCK_SPACING)
        scroll.setWidget(body)
        return scroll, body, layout

    def _card(
        self,
        title: str,
        subtitle: str,
        object_name: str,
        parent: QWidget,
        *,
        icon: str | None = None,
    ) -> SectionCard:
        if icon is None:
            return SectionCard(
                title,
                subtitle=subtitle,
                object_name=object_name,
                parent=parent,
            )
        return SectionCard(
            title,
            subtitle=subtitle,
            semantic_icon=icon,
            icon_manager=self._icon_manager,
            object_name=object_name,
            parent=parent,
        )

    def _value_row(
        self,
        label: str,
        value: str,
        object_name: str,
        parent: QWidget,
    ) -> QWidget:
        row = QWidget(parent)
        row.setObjectName(object_name)
        row.setMinimumHeight(ADVANCED_FIELD_HEIGHT)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        label_widget = QLabel(label, row)
        label_widget.setFixedWidth(ADVANCED_FIELD_LABEL_WIDTH)
        label_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        set_ui_role(label_widget, "fieldLabel")
        layout.addWidget(label_widget)
        value_widget = QLabel(value, row)
        value_widget.setObjectName(f"{object_name}Value")
        set_ui_role(value_widget, "valueLabel")
        layout.addWidget(value_widget, 1)
        return row

    @staticmethod
    def _inline_summary_field(
        label: str,
        value: str,
        value_object_name: str,
        parent: QWidget,
        *,
        label_width: int | None = None,
        spacing: int = 6,
    ) -> QLabel:
        host = QWidget(parent)
        host.setObjectName(f"{value_object_name}Field")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        label_widget = QLabel(label, host)
        if label_width is not None:
            label_widget.setFixedWidth(label_width)
            label_widget.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        set_ui_role(label_widget, "fieldLabel")
        layout.addWidget(label_widget)
        value_widget = QLabel(value, host)
        value_widget.setObjectName(value_object_name)
        value_widget.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        value_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        set_ui_role(value_widget, "valueLabel")
        layout.addWidget(value_widget, 1)
        return value_widget

    def _field_row(
        self,
        label: str,
        editor: QWidget,
        object_name: str,
        parent: QWidget,
    ) -> QWidget:
        row = QWidget(parent)
        row.setObjectName(object_name)
        row.setMinimumHeight(ADVANCED_FIELD_HEIGHT)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        label_widget = QLabel(label, row)
        label_widget.setFixedWidth(ADVANCED_FIELD_LABEL_WIDTH)
        label_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        set_ui_role(label_widget, "fieldLabel")
        layout.addWidget(label_widget)
        layout.addWidget(editor, 1)
        return row

    @staticmethod
    def _editor_with_button(
        editor: QWidget,
        button: QToolButton,
        object_name: str,
        parent: QWidget,
    ) -> QWidget:
        container = QWidget(parent)
        container.setObjectName(object_name)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(editor, 1)
        layout.addWidget(button)
        return container

    def _file_select_button(
        self,
        object_name: str,
        semantic_icon: str,
        *,
        tooltip: str,
        parent: QWidget,
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(object_name)
        button.setText("")
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setIcon(
            self._icon_manager.icon(
                semantic_icon,
                size=max(18, ADVANCED_BUTTON_ICON_SIZE),
            )
        )
        button.setIconSize(QSize(max(18, ADVANCED_BUTTON_ICON_SIZE), max(18, ADVANCED_BUTTON_ICON_SIZE)))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setFixedSize(40, ADVANCED_BUTTON_HEIGHT)
        button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        set_ui_variant(button, "secondary")
        button.setProperty("filePickerButton", True)
        return button

    @staticmethod
    def _layout_host(
        layout: QHBoxLayout,
        object_name: str,
        parent: QWidget,
    ) -> QWidget:
        host = QWidget(parent)
        host.setObjectName(object_name)
        host.setLayout(layout)
        return host

    def _action_button(
        self,
        text: str,
        semantic_icon: str,
        object_name: str,
        parent: QWidget,
        *,
        variant: str = "secondary",
    ) -> QPushButton:
        button = QPushButton(text, parent)
        button.setObjectName(object_name)
        button.setIcon(
            self._icon_manager.icon(
                semantic_icon,
                size=ADVANCED_BUTTON_ICON_SIZE,
            )
        )
        button.setIconSize(QSize(ADVANCED_BUTTON_ICON_SIZE, ADVANCED_BUTTON_ICON_SIZE))
        button.setMinimumHeight(ADVANCED_BUTTON_HEIGHT)
        button.setEnabled(False)
        set_ui_variant(button, variant)
        return button

    def _header_tool_button(
        self,
        card: SectionCard,
        text: str,
        semantic_icon: str,
        object_name: str,
    ) -> QToolButton:
        button = QToolButton(card.header)
        button.setObjectName(object_name)
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIcon(
            self._icon_manager.icon(
                semantic_icon,
                size=ADVANCED_BUTTON_ICON_SIZE,
            )
        )
        button.setIconSize(QSize(ADVANCED_BUTTON_ICON_SIZE, ADVANCED_BUTTON_ICON_SIZE))
        set_ui_variant(button, "toolbar")
        card.header.add_action_widget(button)
        return button

    def _copy_result(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.result_output.toPlainText())


__all__ = [
    "ADVANCED_TAB_LABELS",
    "CPU1_FLASH_SECTOR_OPTIONS",
    "ERASE_SCOPE_LABELS",
    "AdvancedPage",
]
