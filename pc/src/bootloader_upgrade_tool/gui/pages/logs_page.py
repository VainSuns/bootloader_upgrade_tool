"""Static Phase 11 Batch 8 structured Logs page.

Logs are a local structured-history view and are intentionally separate from the
global real-time Console.  This module performs no file I/O and imports no
backend runtime layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import (
    LOGS_COLUMN_WIDTHS,
    LOGS_DETAILS_MINIMUM_WIDTH,
    LOGS_FILTER_BAR_HEIGHT,
    LOGS_FILTER_CONTROL_HEIGHT,
    LOGS_SPLITTER_HANDLE_WIDTH,
    LOGS_SPLITTER_INITIAL_SIZES,
    LOGS_TABLE_HEADER_HEIGHT,
    LOGS_TABLE_MINIMUM_WIDTH,
    LOGS_TABLE_ROW_HEIGHT,
    PAGE_BLOCK_SPACING,
    PAGE_MARGINS,
)
from ..ui_state import set_ui_role, set_ui_variant
from ..widgets.card import SectionCard
from ..widgets.input_controls import IndicatorComboBox
from ..widgets.page_header import PageHeader
from ..widgets.status_widgets import StatusBadge

LOG_LEVEL_CHOICES: Final = (
    "All",
    "Debug",
    "Info",
    "Warning",
    "Error",
    "Success",
    "Protocol",
)
LOG_TABLE_HEADERS: Final = ("Time", "Level", "Source", "Operation", "Message")

_PREVIEW_LOGS: Final = (
    {
        "time": "10:00:00.000",
        "level": "Info",
        "source": "GUI",
        "operation": "Layout Preview",
        "stage": "Static",
        "message": "[Preview] Structured Logs page initialized without reading a log file.",
    },
    {
        "time": "10:00:00.125",
        "level": "Protocol",
        "source": "Protocol",
        "operation": "SERVICE_ATTACH",
        "stage": "Not executed",
        "message": "[Preview] Descriptor address will come from map/symbol data during workflow integration.",
    },
    {
        "time": "10:00:00.250",
        "level": "Warning",
        "source": "Target",
        "operation": "CPU2",
        "stage": "Deferred",
        "message": "[Preview] CPU2 runtime integration remains disabled.",
    },
)


class LogsPage(QWidget):
    """Read-only structured history layout, separate from the global Console."""

    def __init__(
        self,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("logsPage")
        set_ui_role(self, "page")
        self._icon_manager = icon_manager or IconManager()
        self._records: list[dict[str, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(PAGE_BLOCK_SPACING)

        self.header = PageHeader(
            "Logs",
            description=(
                "Review structured operation history. This page is independent from the global Console."
            ),
            object_name="logsPageHeader",
            parent=self,
        )
        self.preview_badge = StatusBadge("Layout Preview", "warning", parent=self.header)
        self.header.add_action_widget(self.preview_badge)
        root.addWidget(self.header)

        self.filter_bar = self._create_filter_bar()
        root.addWidget(self.filter_bar)

        self.horizontal_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.horizontal_splitter.setObjectName("logsHorizontalSplitter")
        self.horizontal_splitter.setChildrenCollapsible(False)
        self.horizontal_splitter.setHandleWidth(LOGS_SPLITTER_HANDLE_WIDTH)
        self.table_card = self._create_table_card()
        self.details_card = self._create_details_card()
        self.horizontal_splitter.addWidget(self.table_card)
        self.horizontal_splitter.addWidget(self.details_card)
        self.horizontal_splitter.setStretchFactor(0, 70)
        self.horizontal_splitter.setStretchFactor(1, 30)
        self.horizontal_splitter.setSizes(list(LOGS_SPLITTER_INITIAL_SIZES))
        root.addWidget(self.horizontal_splitter, 1)

        self.level_combo.currentTextChanged.connect(self._apply_filters)
        self.source_combo.currentTextChanged.connect(self._apply_filters)
        self.search_edit.textChanged.connect(self._apply_filters)
        self.reset_filter_button.clicked.connect(self._reset_filters)
        self.clear_logs_button.clicked.connect(self.clear_logs)
        self.copy_detail_button.clicked.connect(self._copy_details)
        self.logs_table.itemSelectionChanged.connect(self._update_details_from_selection)

        self.set_records(_PREVIEW_LOGS, preview=True)

    def set_records(
        self,
        records: Iterable[Mapping[str, object]],
        *,
        preview: bool = False,
    ) -> None:
        normalized: list[dict[str, str]] = []
        for record in records:
            normalized.append(
                {
                    "time": str(record.get("time", "—")),
                    "level": str(record.get("level", "Info")),
                    "source": str(record.get("source", "GUI")),
                    "operation": str(record.get("operation", "—")),
                    "stage": str(record.get("stage", "—")),
                    "message": str(record.get("message", "")),
                }
            )
        self._records = normalized
        self.logs_table.setRowCount(len(normalized))
        for row, record in enumerate(normalized):
            for column, key in enumerate(("time", "level", "source", "operation", "message")):
                item = QTableWidgetItem(record[key])
                self.logs_table.setItem(row, column, item)
        self.preview_notice.setText(
            "Layout Preview Data — no log file was opened."
            if preview
            else "Controller-supplied structured log records."
        )
        self._refresh_source_choices()
        self._apply_filters()
        if normalized:
            self.logs_table.selectRow(0)
        else:
            self._clear_details()

    def clear_logs(self) -> None:
        """Clear only this page's local rows; the global Console is untouched."""

        self._records.clear()
        self.logs_table.setRowCount(0)
        self._clear_details()

    def _create_filter_bar(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("logsFilterBar")
        bar.setMinimumHeight(LOGS_FILTER_BAR_HEIGHT)
        set_ui_role(bar, "card")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)

        self.level_combo = IndicatorComboBox(parent=bar, icon_manager=self._icon_manager)
        self.level_combo.setObjectName("logsLevelCombo")
        self.level_combo.addItems(list(LOG_LEVEL_CHOICES))
        self.level_combo.setFixedHeight(LOGS_FILTER_CONTROL_HEIGHT)
        self.level_combo.setMinimumWidth(120)
        layout.addWidget(self._labeled_filter("Level", self.level_combo, bar))

        self.source_combo = IndicatorComboBox(parent=bar, icon_manager=self._icon_manager)
        self.source_combo.setObjectName("logsSourceCombo")
        self.source_combo.addItem("All")
        self.source_combo.setFixedHeight(LOGS_FILTER_CONTROL_HEIGHT)
        self.source_combo.setMinimumWidth(128)
        layout.addWidget(self._labeled_filter("Source", self.source_combo, bar))

        self.search_edit = QLineEdit(bar)
        self.search_edit.setObjectName("logsSearchEdit")
        self.search_edit.setPlaceholderText("Search operation, stage, or message")
        self.search_edit.setFixedHeight(LOGS_FILTER_CONTROL_HEIGHT)
        layout.addWidget(self.search_edit, 1)

        self.reset_filter_button = self._tool_button(
            "Reset Filter", "common.close", "logsResetFilterButton", bar, enabled=True
        )
        self.export_button = self._tool_button(
            "Export", "logs.export", "logsExportButton", bar, enabled=False
        )
        self.open_folder_button = self._tool_button(
            "Open Folder", "logs.open_folder", "logsOpenFolderButton", bar, enabled=False
        )
        self.clear_logs_button = self._tool_button(
            "Clear Logs", "logs.clear", "logsClearButton", bar, enabled=True
        )
        for button in (
            self.reset_filter_button,
            self.export_button,
            self.open_folder_button,
            self.clear_logs_button,
        ):
            layout.addWidget(button)
        return bar

    def _create_table_card(self) -> SectionCard:
        card = SectionCard(
            "Structured History",
            subtitle="Read-only history table; Stage is shown in the details pane.",
            semantic_icon="logs.page",
            icon_manager=self._icon_manager,
            object_name="logsTableCard",
            parent=self.horizontal_splitter,
        )
        card.setMinimumWidth(LOGS_TABLE_MINIMUM_WIDTH)
        self.preview_notice = QLabel("Layout Preview Data — no log file was opened.", card.body)
        self.preview_notice.setObjectName("logsPreviewNotice")
        set_ui_role(self.preview_notice, "helperText")
        card.add_widget(self.preview_notice)

        self.logs_table = QTableWidget(0, len(LOG_TABLE_HEADERS), card.body)
        self.logs_table.setObjectName("logsTable")
        self.logs_table.setHorizontalHeaderLabels(list(LOG_TABLE_HEADERS))
        self.logs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.logs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.logs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.logs_table.setAlternatingRowColors(True)
        self.logs_table.verticalHeader().setVisible(False)
        self.logs_table.verticalHeader().setDefaultSectionSize(LOGS_TABLE_ROW_HEIGHT)
        self.logs_table.horizontalHeader().setFixedHeight(LOGS_TABLE_HEADER_HEIGHT)
        self.logs_table.setColumnWidth(0, LOGS_COLUMN_WIDTHS["time"])
        self.logs_table.setColumnWidth(1, LOGS_COLUMN_WIDTHS["level"])
        self.logs_table.setColumnWidth(2, LOGS_COLUMN_WIDTHS["source"])
        self.logs_table.setColumnWidth(3, LOGS_COLUMN_WIDTHS["operation"])
        self.logs_table.horizontalHeader().setStretchLastSection(True)
        card.add_widget(self.logs_table, 1)
        return card

    def _create_details_card(self) -> SectionCard:
        card = SectionCard(
            "Log Details",
            subtitle="Selection details; not the global Console output.",
            semantic_icon="logs.open_external",
            icon_manager=self._icon_manager,
            object_name="logDetailsCard",
            parent=self.horizontal_splitter,
        )
        card.setMinimumWidth(LOGS_DETAILS_MINIMUM_WIDTH)
        self.copy_detail_button = self._tool_button(
            "Copy", "logs.copy_detail", "logsCopyDetailButton", card.header, enabled=True
        )
        card.header.add_action_widget(self.copy_detail_button)

        metadata = QWidget(card.body)
        metadata.setObjectName("logsDetailsMetadata")
        grid = QGridLayout(metadata)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.detail_values: dict[str, QLabel] = {}
        for row, (key, title) in enumerate(
            (
                ("time", "Time"),
                ("level", "Level"),
                ("source", "Source"),
                ("operation", "Operation"),
                ("stage", "Stage"),
            )
        ):
            label = QLabel(title, metadata)
            set_ui_role(label, "fieldLabel")
            grid.addWidget(label, row, 0)
            value = QLabel("—", metadata)
            value.setObjectName(f"logsDetail{key.title()}Value")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            set_ui_role(value, "valueLabel")
            grid.addWidget(value, row, 1)
            self.detail_values[key] = value
        grid.setColumnStretch(1, 1)
        card.add_widget(metadata)

        message_label = QLabel("Message", card.body)
        set_ui_role(message_label, "fieldLabel")
        card.add_widget(message_label)
        self.detail_message = QPlainTextEdit(card.body)
        self.detail_message.setObjectName("logsDetailMessage")
        self.detail_message.setReadOnly(True)
        self.detail_message.setUndoRedoEnabled(False)
        self.detail_message.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        card.add_widget(self.detail_message, 1)
        return card

    def _apply_filters(self, _value: str = "") -> None:
        level = self.level_combo.currentText().lower()
        source = self.source_combo.currentText().lower()
        search = self.search_edit.text().strip().lower()
        for row, record in enumerate(self._records):
            level_match = level == "all" or record["level"].lower() == level
            source_match = source == "all" or record["source"].lower() == source
            haystack = " ".join(record.values()).lower()
            search_match = not search or search in haystack
            self.logs_table.setRowHidden(row, not (level_match and source_match and search_match))

    def _reset_filters(self) -> None:
        self.level_combo.setCurrentIndex(0)
        self.source_combo.setCurrentIndex(0)
        self.search_edit.clear()
        self._apply_filters()

    def _refresh_source_choices(self) -> None:
        current = self.source_combo.currentText() or "All"
        sources = sorted({record["source"] for record in self._records})
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("All")
        self.source_combo.addItems(sources)
        index = self.source_combo.findText(current)
        self.source_combo.setCurrentIndex(max(0, index))
        self.source_combo.blockSignals(False)

    def _update_details_from_selection(self) -> None:
        selected = self.logs_table.selectionModel().selectedRows()
        if not selected:
            self._clear_details()
            return
        row = selected[0].row()
        if not 0 <= row < len(self._records):
            self._clear_details()
            return
        record = self._records[row]
        for key, label in self.detail_values.items():
            label.setText(record[key])
        self.detail_message.setPlainText(record["message"])

    def _copy_details(self) -> None:
        text = "\n".join(
            [f"{key.title()}: {label.text()}" for key, label in self.detail_values.items()]
            + [f"Message: {self.detail_message.toPlainText()}"]
        )
        QApplication.clipboard().setText(text)

    def _clear_details(self) -> None:
        for label in self.detail_values.values():
            label.setText("—")
        self.detail_message.clear()

    def _labeled_filter(self, text: str, editor: QWidget, parent: QWidget) -> QWidget:
        host = QWidget(parent)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(text, host)
        set_ui_role(label, "fieldLabel")
        layout.addWidget(label)
        editor.setParent(host)
        layout.addWidget(editor)
        return host

    def _tool_button(
        self,
        text: str,
        semantic_icon: str,
        object_name: str,
        parent: QWidget,
        *,
        enabled: bool,
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(object_name)
        button.setText(text)
        button.setIcon(self._icon_manager.icon(semantic_icon, size=16))
        button.setIconSize(QSize(16, 16))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setFixedHeight(LOGS_FILTER_CONTROL_HEIGHT)
        button.setMinimumWidth(82)
        button.setEnabled(enabled)
        set_ui_variant(button, "toolbar")
        return button


__all__ = ["LOG_LEVEL_CHOICES", "LOG_TABLE_HEADERS", "LogsPage"]
