"""Static Phase 11 Batch 7 Advanced page.

The page exposes approved diagnostics, Flash, metadata, execution, and RAM-image
layout contracts only.  It does not import or invoke operations, sessions,
transports, protocol clients, image preparation, DSP code, or hardware access.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QSize, Qt
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


class AdvancedPage(QWidget):
    """Approved static Advanced workspace; no target operation is executed."""

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
                "Review low-level CPU1 operations and recovery layouts. "
                "All target actions remain disabled until controller integration."
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

    # Diagnostics ---------------------------------------------------------
    def _create_diagnostics_tab(self) -> QScrollArea:
        scroll, body, layout = self._tab_page("advancedDiagnosticsTab")

        identity = self._card(
            "Device and Protocol",
            "Unknown until a future controller reads the connected target.",
            "advancedDiagnosticsIdentityCard",
            body,
        )
        for label, value, suffix in (
            ("Target", "CPU1", "Target"),
            ("Device", "TMS320F28377D", "Device"),
            ("Device ID", "—", "DeviceId"),
            ("CPU ID", "—", "CpuId"),
            ("Protocol version", "—", "ProtocolVersion"),
            ("Last error", "—", "LastError"),
        ):
            identity.add_widget(
                self._value_row(
                    label,
                    value,
                    f"advancedDiagnostics{suffix}Row",
                    identity.body,
                )
            )
        layout.addWidget(identity)

        action_card = self._card(
            "Read-only Diagnostics",
            "These controls will call status operations after controller integration.",
            "advancedDiagnosticsActionsCard",
            body,
        )
        action_row = QHBoxLayout()
        self.refresh_status_button = self._action_button(
            "Refresh Status",
            "advanced.diagnostics.refresh_status",
            "advancedRefreshStatusButton",
            action_card.body,
        )
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
            self.refresh_status_button,
            self.read_device_info_button,
            self.read_protocol_info_button,
            self.get_last_error_button,
        ):
            action_row.addWidget(button)
        action_row.addStretch(1)
        action_card.add_widget(self._layout_host(action_row, "advancedDiagnosticsActions", action_card.body))
        layout.addWidget(action_card)
        layout.addStretch(1)
        return scroll

    # Flash ---------------------------------------------------------------
    def _create_flash_tab(self) -> QScrollArea:
        scroll, body, layout = self._tab_page("advancedFlashTab")

        image_card = self._card(
            "Flash App Image",
            "Static path field only; no image is read or prepared in this batch.",
            "advancedFlashImageCard",
            body,
        )
        self.flash_image_edit = QLineEdit(image_card.body)
        self.flash_image_edit.setObjectName("advancedFlashImageEdit")
        self.flash_image_edit.setPlaceholderText("Select a prepared CPU1 Flash App image")
        self.flash_image_edit.setMinimumHeight(ADVANCED_FIELD_HEIGHT)
        self.flash_browse_button = QToolButton(image_card.body)
        self.flash_browse_button.setObjectName("advancedFlashBrowseButton")
        self.flash_browse_button.setIcon(
            self._icon_manager.icon(
                "advanced.flash.browse_image",
                size=ADVANCED_BUTTON_ICON_SIZE,
            )
        )
        self.flash_browse_button.setIconSize(
            QSize(ADVANCED_BUTTON_ICON_SIZE, ADVANCED_BUTTON_ICON_SIZE)
        )
        self.flash_browse_button.setText("Browse")
        self.flash_browse_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.flash_browse_button.setFixedHeight(ADVANCED_BUTTON_HEIGHT)
        self.flash_browse_button.setMinimumWidth(96)
        self.flash_browse_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        set_ui_variant(self.flash_browse_button, "toolbar")
        self.flash_browse_button.setToolTip("Browse is added during controller integration")
        self.flash_browse_button.setEnabled(False)
        image_card.add_widget(
            self._field_row(
                "App image",
                self._editor_with_button(
                    self.flash_image_edit,
                    self.flash_browse_button,
                    "advancedFlashImageField",
                    image_card.body,
                ),
                "advancedFlashImageRow",
                image_card.body,
            )
        )
        image_card.add_widget(
            self._value_row(
                "Target",
                "CPU1 / TMS320F28377D",
                "advancedFlashTargetRow",
                image_card.body,
            )
        )
        layout.addWidget(image_card)

        scope_card = self._card(
            "Erase Scope",
            "Select only the CPU1 application region required by the operation.",
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
        self.custom_sector_mask_edit = QLineEdit(scope_card.body)
        self.custom_sector_mask_edit.setObjectName("advancedCustomSectorMaskEdit")
        self.custom_sector_mask_edit.setPlaceholderText("Custom sector mask")
        self.custom_sector_mask_edit.setMinimumHeight(ADVANCED_FIELD_HEIGHT)
        self.custom_sector_mask_edit.setEnabled(False)
        scope_card.add_widget(
            self._field_row(
                "Custom mask",
                self.custom_sector_mask_edit,
                "advancedCustomSectorMaskRow",
                scope_card.body,
            )
        )
        self.erase_scope_combo.currentTextChanged.connect(
            lambda text: self.custom_sector_mask_edit.setEnabled(
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
        card = self._card(
            "Current-image Metadata",
            "Each append action is separate and must bind to the current IMAGE_VALID identity.",
            "advancedMetadataCard",
            body,
        )
        for label, value, suffix in (
            ("Image identity", "—", "ImageIdentity"),
            ("IMAGE_VALID", "Unknown", "ImageValid"),
            ("BOOT_ATTEMPT", "Unknown", "BootAttempt"),
            ("APP_CONFIRMED", "Unknown", "AppConfirmed"),
        ):
            card.add_widget(
                self._value_row(
                    label,
                    value,
                    f"advancedMetadata{suffix}Row",
                    card.body,
                )
            )

        self.write_image_valid_button = self._action_button(
            "Write IMAGE_VALID",
            "advanced.metadata.image_valid",
            "advancedWriteImageValidButton",
            card.body,
        )
        self.write_boot_attempt_button = self._action_button(
            "Write BOOT_ATTEMPT",
            "advanced.metadata.boot_attempt",
            "advancedWriteBootAttemptButton",
            card.body,
        )
        self.write_app_confirmed_button = self._action_button(
            "Write APP_CONFIRMED",
            "advanced.metadata.app_confirmed",
            "advancedWriteAppConfirmedButton",
            card.body,
        )
        row = QHBoxLayout()
        for button in (
            self.write_image_valid_button,
            self.write_boot_attempt_button,
            self.write_app_confirmed_button,
        ):
            row.addWidget(button)
        row.addStretch(1)
        card.add_widget(self._layout_host(row, "advancedMetadataActionRow", card.body))

        note = QLabel(
            "BOOT_ATTEMPT and APP_CONFIRMED cannot reuse records from an older image. "
            "APP_CONFIRMED additionally requires the matching IMAGE_VALID and an "
            "existing BOOT_ATTEMPT.",
            card.body,
        )
        note.setObjectName("advancedMetadataBindingNotice")
        note.setWordWrap(True)
        set_ui_role(note, "helperText")
        card.add_widget(note)
        layout.addWidget(card)
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
        cards = QWidget(body)
        cards.setObjectName("advancedRamCards")
        cards_layout = QGridLayout(cards)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setHorizontalSpacing(PAGE_BLOCK_SPACING)
        cards_layout.setVerticalSpacing(PAGE_BLOCK_SPACING)
        cards_layout.setColumnStretch(0, 1)
        cards_layout.setColumnStretch(1, 1)

        self.cpu1_ram_card = self._create_ram_card("cpu1", cards)
        self.cpu2_ram_card = self._create_ram_card("cpu2", cards)
        self.cpu2_ram_card.setEnabled(False)
        cards_layout.addWidget(self.cpu1_ram_card, 0, 0)
        cards_layout.addWidget(self.cpu2_ram_card, 0, 1)
        layout.addWidget(cards)

        note = QLabel(
            "RUN_RAM / RAM_RUN source and tests remain retained. CPU2 runtime "
            "integration is deferred until the CPU1 GUI workflow is complete.",
            body,
        )
        note.setObjectName("advancedRamRetentionNotice")
        note.setWordWrap(True)
        set_ui_role(note, "helperText")
        layout.addWidget(note)
        layout.addStretch(1)
        return scroll

    def _create_ram_card(self, target: str, parent: QWidget) -> SectionCard:
        label = target.upper()
        card = self._card(
            f"{label} RAM Image",
            "Load, CRC check, and run remain separate operations.",
            f"advanced{label.title()}RamCard",
            parent,
            icon=f"advanced.ram.{target}",
        )
        path = QLineEdit(card.body)
        path.setObjectName(f"advanced{label.title()}RamImageEdit")
        path.setPlaceholderText(f"Select a {label} RAM image")
        path.setMinimumHeight(ADVANCED_FIELD_HEIGHT)
        browse = QToolButton(card.body)
        browse.setObjectName(f"advanced{label.title()}RamBrowseButton")
        browse.setIcon(
            self._icon_manager.icon(
                "advanced.ram.browse_image",
                size=ADVANCED_BUTTON_ICON_SIZE,
            )
        )
        browse.setIconSize(QSize(ADVANCED_BUTTON_ICON_SIZE, ADVANCED_BUTTON_ICON_SIZE))
        browse.setText("Browse")
        browse.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        browse.setFixedHeight(ADVANCED_BUTTON_HEIGHT)
        browse.setMinimumWidth(96)
        browse.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        set_ui_variant(browse, "toolbar")
        browse.setEnabled(False)
        path_label = QLabel("RAM image", card.body)
        path_label.setObjectName(f"advanced{label.title()}RamImageLabel")
        set_ui_role(path_label, "fieldLabel")
        card.add_widget(path_label)

        path_host = self._editor_with_button(
            path,
            browse,
            f"advanced{label.title()}RamImageField",
            card.body,
        )
        path_host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        card.add_widget(path_host)
        load = self._action_button(
            "Load",
            "advanced.ram.load_image",
            f"advanced{label.title()}RamLoadButton",
            card.body,
        )
        crc = self._action_button(
            "Check CRC",
            "advanced.ram.check_crc",
            f"advanced{label.title()}RamCheckCrcButton",
            card.body,
        )
        run = self._action_button(
            "Run",
            "advanced.ram.run_image",
            f"advanced{label.title()}RamRunButton",
            card.body,
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(load)
        row.addWidget(crc)
        row.addWidget(run)
        row.addStretch(1)
        action_host = self._layout_host(
            row,
            f"advanced{label.title()}RamActionRow",
            card.body,
        )
        action_host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        card.add_widget(action_host)
        if target == "cpu1":
            self.cpu1_ram_image_edit = path
            self.cpu1_ram_browse_button = browse
            self.cpu1_ram_load_button = load
            self.cpu1_ram_crc_button = crc
            self.cpu1_ram_run_button = run
            self.cpu1_ram_path_host = path_host
            self.cpu1_ram_action_host = action_host
        else:
            self.cpu2_ram_image_edit = path
            self.cpu2_ram_browse_button = browse
            self.cpu2_ram_load_button = load
            self.cpu2_ram_crc_button = crc
            self.cpu2_ram_run_button = run
            self.cpu2_ram_path_host = path_host
            self.cpu2_ram_action_host = action_host
        return card

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


__all__ = ["ADVANCED_TAB_LABELS", "ERASE_SCOPE_LABELS", "AdvancedPage"]
