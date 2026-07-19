"""Pure PySide6 read-only Memory pages for Backend-owned snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    MEMORY_ADDRESS_COLUMN_WIDTH,
    MEMORY_ADDRESS_WIDTH,
    MEMORY_DETAILS_MINIMUM_WIDTH,
    MEMORY_DISPLAY_FORMAT_WIDTH,
    MEMORY_FIELD_HEIGHT,
    MEMORY_SEARCH_MINIMUM_WIDTH,
    MEMORY_SPLITTER_HANDLE_WIDTH,
    MEMORY_SPLITTER_INITIAL_SIZES,
    MEMORY_TABLE_HEADER_HEIGHT,
    MEMORY_TABLE_MINIMUM_WIDTH,
    MEMORY_TABLE_ROW_HEIGHT,
    MEMORY_WORD_COLUMNS,
    MEMORY_WORD_COLUMN_MINIMUM_WIDTH,
    MEMORY_WORD_COUNT_WIDTH,
    PAGE_BLOCK_SPACING,
    PAGE_MARGINS,
)
from ..ui_state import set_ui_role, set_ui_state, set_ui_variant
from ..widgets.card import SectionCard
from ..widgets.input_controls import IndicatorComboBox, IndicatorSpinBox
from ..widgets.page_header import TargetPageHeader

_TARGETS: Final = frozenset({"cpu1", "cpu2"})
MEMORY_DISPLAY_FORMATS: Final = ("Hex16", "Unsigned", "Signed", "ASCII")
MEMORY_TABLE_HEADERS: Final = ("Address",) + tuple(
    f"+{offset:X}" for offset in range(MEMORY_WORD_COLUMNS)
)
_MEMORY_CONTROL_LABEL_WIDTH: Final = 92
_UNKNOWN_WORD: Final = "????"

class MemoryTargetPage(QWidget):
    """Shared read-only Memory layout for CPU1 and deferred CPU2."""

    refreshRequested = Signal(str)
    exportRequested = Signal(str)
    clearRequested = Signal(str)

    def __init__(
        self,
        target: str,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        normalized = target.strip().lower()
        if normalized not in _TARGETS:
            raise ValueError("target must be 'cpu1' or 'cpu2'")

        super().__init__(parent)
        self.target = normalized
        self.target_label = normalized.upper()
        self.object_prefix = f"memory{self.target_label.title()}"
        self._interactions_enabled = normalized == "cpu1"
        self._icon_manager = icon_manager or IconManager()

        self.setObjectName(f"{self.object_prefix}Page")
        set_ui_role(self, "page")

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(PAGE_BLOCK_SPACING)

        self.header = TargetPageHeader(
            f"{self.target_label} Memory",
            target_text=self.target_label,
            target_state="neutral" if self._interactions_enabled else "unavailable",
            description=(
                "Review retained read-only 16-bit memory words. Generic target Memory Read "
                "is not supported in this phase."
            ),
            preview=False,
            object_name=f"{self.objectName()}Header",
            parent=self,
        )
        root.addWidget(self.header)

        self.control_card = self._create_control_card()
        root.addWidget(self.control_card)

        self.horizontal_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.horizontal_splitter.setObjectName(f"{self.object_prefix}HorizontalSplitter")
        self.horizontal_splitter.setChildrenCollapsible(False)
        self.horizontal_splitter.setHandleWidth(MEMORY_SPLITTER_HANDLE_WIDTH)

        self.table_card = self._create_table_card()
        self.details_card = self._create_details_card()
        self.horizontal_splitter.addWidget(self.table_card)
        self.horizontal_splitter.addWidget(self.details_card)
        self.horizontal_splitter.setStretchFactor(0, 90)
        self.horizontal_splitter.setStretchFactor(1, 10)
        self.horizontal_splitter.setSizes(list(MEMORY_SPLITTER_INITIAL_SIZES))
        root.addWidget(self.horizontal_splitter, 1)

        self.memory_table.itemSelectionChanged.connect(self._update_details_from_selection)
        self.search_edit.textChanged.connect(self._apply_local_search)
        self.copy_detail_button.clicked.connect(self._copy_details)
        self.clear_button.clicked.connect(lambda: self.clearRequested.emit(self.target))
        self.set_interactions_enabled(self._interactions_enabled)
        self.set_memory_freshness("Empty", state="unknown")
        self.set_clear_enabled(False)

    @property
    def interactions_enabled(self) -> bool:
        return self._interactions_enabled

    def set_interactions_enabled(self, enabled: bool) -> None:
        self._interactions_enabled = bool(enabled and self.target == "cpu1")
        self.start_address_edit.setEnabled(False)
        self.word_count_spin.setEnabled(False)
        self.display_format_combo.setEnabled(False)
        self.search_edit.setEnabled(True)
        self.refresh_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def set_memory_freshness(
        self,
        text: str,
        *,
        state: str,
        tooltip: str = "",
    ) -> None:
        self.freshness_value.setText(text)
        self.freshness_value.setToolTip(tooltip)
        set_ui_state(self.freshness_value, state)

    def set_clear_enabled(self, enabled: bool) -> None:
        self.clear_button.setEnabled(bool(enabled))

    def set_memory_rows(
        self,
        rows: Iterable[tuple[int, Sequence[int]]],
        *,
        preview: bool = False,
    ) -> None:
        """Replace table rows without performing a target operation."""

        normalized: list[tuple[int, tuple[int, ...]]] = []
        for address, words in rows:
            values = tuple(int(word) & 0xFFFF for word in words)
            if len(values) > MEMORY_WORD_COLUMNS:
                raise ValueError(
                    f"each memory row may contain at most {MEMORY_WORD_COLUMNS} words"
                )
            normalized.append((int(address), values))

        self.memory_table.setRowCount(len(normalized))
        for row_index, (address, words) in enumerate(normalized):
            self.memory_table.setItem(row_index, 0, QTableWidgetItem(f"0x{address:06X}"))
            for offset in range(MEMORY_WORD_COLUMNS):
                rendered = f"{words[offset]:04X}" if offset < len(words) else _UNKNOWN_WORD
                item = QTableWidgetItem(rendered)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.memory_table.setItem(row_index, offset + 1, item)
        if not normalized:
            self.preview_notice.setText("No retained Memory data.")
            self._clear_details()
        elif preview:
            self.preview_notice.setText(
                "Layout Preview Data — no target memory was read; unread words show ????."
            )
        elif any(len(words) < MEMORY_WORD_COLUMNS for _, words in normalized):
            self.preview_notice.setText(
                "No value is available for unread words; they are shown as ????."
            )
        else:
            self.preview_notice.setText("Controller-supplied read-only data.")
        if normalized:
            self.memory_table.selectRow(0)

    def _create_control_card(self) -> SectionCard:
        card = SectionCard(
            "Read Controls",
            subtitle="Address and count are future read parameters; Search filters loaded local rows.",
            semantic_icon="memory.address",
            icon_manager=self._icon_manager,
            object_name=f"{self.object_prefix}ControlCard",
            parent=self,
        )
        row = QFrame(card.body)
        row.setObjectName(f"{self.object_prefix}ControlRow")
        layout = QGridLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        self.start_address_edit = QLineEdit("0x000000", row)
        self.start_address_edit.setObjectName(f"{self.object_prefix}StartAddressEdit")
        self.start_address_edit.setFixedWidth(MEMORY_ADDRESS_WIDTH)
        self.start_address_edit.setFixedHeight(MEMORY_FIELD_HEIGHT)
        layout.addWidget(
            self._labeled_control("Start Address", self.start_address_edit, row), 0, 0
        )

        self.word_count_spin = IndicatorSpinBox(parent=row, icon_manager=self._icon_manager)
        self.word_count_spin.setObjectName(f"{self.object_prefix}WordCountSpin")
        self.word_count_spin.setRange(1, 4096)
        self.word_count_spin.setValue(256)
        self.word_count_spin.setFixedWidth(MEMORY_WORD_COUNT_WIDTH)
        self.word_count_spin.setFixedHeight(MEMORY_FIELD_HEIGHT)
        layout.addWidget(self._labeled_control("Word Count", self.word_count_spin, row), 0, 1)

        self.display_format_combo = IndicatorComboBox(parent=row, icon_manager=self._icon_manager)
        self.display_format_combo.setObjectName(f"{self.object_prefix}DisplayFormatCombo")
        self.display_format_combo.addItems(list(MEMORY_DISPLAY_FORMATS))
        self.display_format_combo.setFixedWidth(MEMORY_DISPLAY_FORMAT_WIDTH)
        self.display_format_combo.setFixedHeight(MEMORY_FIELD_HEIGHT)
        layout.addWidget(
            self._labeled_control("Display Format", self.display_format_combo, row),
            0,
            2,
        )

        self.refresh_button = self._tool_button(
            "Refresh", "memory.refresh", f"{self.object_prefix}RefreshButton", row
        )
        self.export_button = self._tool_button(
            "Export", "memory.export", f"{self.object_prefix}ExportButton", row
        )
        layout.addWidget(self.refresh_button, 0, 3)
        layout.addWidget(self.export_button, 0, 4)
        layout.setColumnStretch(5, 1)

        self.search_edit = QLineEdit(row)
        self.search_edit.setObjectName(f"{self.object_prefix}SearchEdit")
        self.search_edit.setPlaceholderText("Search currently loaded local rows")
        self.search_edit.setMinimumWidth(MEMORY_SEARCH_MINIMUM_WIDTH)
        self.search_edit.setFixedHeight(MEMORY_FIELD_HEIGHT)
        self.search_control = self._labeled_control("Search", self.search_edit, row)
        self.search_control.setObjectName(f"{self.object_prefix}SearchControl")
        layout.addWidget(self.search_control, 1, 0, 1, 6)

        card.add_widget(row)
        return card

    def _create_table_card(self) -> SectionCard:
        card = SectionCard(
            "Memory Words",
            subtitle="Sixteen 16-bit words per row; unread words display ????.",
            semantic_icon="memory.page",
            icon_manager=self._icon_manager,
            object_name=f"{self.object_prefix}TableCard",
            parent=self.horizontal_splitter,
        )
        card.setMinimumWidth(MEMORY_TABLE_MINIMUM_WIDTH)
        status_row = QWidget(card.body)
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        freshness_label = QLabel("Freshness", status_row)
        set_ui_role(freshness_label, "fieldLabel")
        status_layout.addWidget(freshness_label)
        self.freshness_value = QLabel("Empty", status_row)
        self.freshness_value.setObjectName(f"{self.object_prefix}FreshnessValue")
        set_ui_role(self.freshness_value, "statusBadge")
        status_layout.addWidget(self.freshness_value)
        status_layout.addStretch(1)
        self.clear_button = self._tool_button(
            "Clear", "console.clear", f"{self.object_prefix}ClearButton", status_row
        )
        status_layout.addWidget(self.clear_button)
        card.add_widget(status_row)

        self.preview_notice = QLabel("No retained Memory data.", card.body)
        self.preview_notice.setObjectName(f"{self.object_prefix}PreviewNotice")
        set_ui_role(self.preview_notice, "helperText")
        card.add_widget(self.preview_notice)

        self.memory_table = QTableWidget(0, len(MEMORY_TABLE_HEADERS), card.body)
        self.memory_table.setObjectName(f"{self.object_prefix}Table")
        self.memory_table.setHorizontalHeaderLabels(list(MEMORY_TABLE_HEADERS))
        self.memory_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.memory_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.memory_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.memory_table.setAlternatingRowColors(True)
        self.memory_table.setSortingEnabled(False)
        self.memory_table.verticalHeader().setVisible(False)
        self.memory_table.verticalHeader().setDefaultSectionSize(MEMORY_TABLE_ROW_HEIGHT)
        self.memory_table.horizontalHeader().setFixedHeight(MEMORY_TABLE_HEADER_HEIGHT)
        self.memory_table.setColumnWidth(0, MEMORY_ADDRESS_COLUMN_WIDTH)
        for column in range(1, len(MEMORY_TABLE_HEADERS)):
            self.memory_table.setColumnWidth(column, MEMORY_WORD_COLUMN_MINIMUM_WIDTH)
        card.add_widget(self.memory_table, 1)
        return card

    def _create_details_card(self) -> SectionCard:
        card = SectionCard(
            "Selected Word",
            semantic_icon="memory.address",
            icon_manager=self._icon_manager,
            object_name=f"{self.object_prefix}DetailsCard",
            parent=self.horizontal_splitter,
        )
        card.setMinimumWidth(MEMORY_DETAILS_MINIMUM_WIDTH)
        self.copy_detail_button = self._tool_button(
            "Copy", "memory.copy", f"{self.object_prefix}CopyDetailButton", card.header
        )
        card.header.add_action_widget(self.copy_detail_button)

        self.detail_values: dict[str, QLabel] = {}
        for key, label in (
            ("address", "Address"),
            ("offset", "Offset"),
            ("hex16", "Hex16"),
            ("unsigned", "Unsigned"),
            ("signed", "Signed"),
            ("ascii", "ASCII"),
        ):
            card.add_widget(self._detail_row(key, label, card.body))
        card.body_layout.addStretch(1)
        return card

    def _update_details_from_selection(self) -> None:
        selected = self.memory_table.selectedItems()
        if not selected:
            self._clear_details()
            return
        item = selected[0]
        row = item.row()
        column = item.column()
        if column == 0:
            column = 1
        address_item = self.memory_table.item(row, 0)
        value_item = self.memory_table.item(row, column)
        if address_item is None or value_item is None:
            self._clear_details()
            return
        base_address = int(address_item.text(), 16)
        offset = column - 1
        rendered_word = value_item.text().strip().upper()
        if rendered_word == _UNKNOWN_WORD:
            values = {
                "address": f"0x{base_address + offset:06X}",
                "offset": f"+{offset:X}",
                "hex16": _UNKNOWN_WORD,
                "unsigned": _UNKNOWN_WORD,
                "signed": _UNKNOWN_WORD,
                "ascii": _UNKNOWN_WORD,
            }
        else:
            value = int(rendered_word, 16) & 0xFFFF
            signed = value if value < 0x8000 else value - 0x10000
            low_byte = value & 0xFF
            ascii_text = chr(low_byte) if 32 <= low_byte <= 126 else "."
            values = {
                "address": f"0x{base_address + offset:06X}",
                "offset": f"+{offset:X}",
                "hex16": f"0x{value:04X}",
                "unsigned": str(value),
                "signed": str(signed),
                "ascii": ascii_text,
            }
        for key, text in values.items():
            self.detail_values[key].setText(text)

    def _apply_local_search(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.memory_table.rowCount()):
            haystack = " ".join(
                self.memory_table.item(row, column).text()
                for column in range(self.memory_table.columnCount())
                if self.memory_table.item(row, column) is not None
            ).lower()
            self.memory_table.setRowHidden(row, bool(needle and needle not in haystack))

    def _copy_details(self) -> None:
        lines = [f"{key}: {label.text()}" for key, label in self.detail_values.items()]
        QApplication.clipboard().setText("\n".join(lines))

    def _clear_details(self) -> None:
        for label in self.detail_values.values():
            label.setText(_UNKNOWN_WORD)

    def _detail_row(self, key: str, label_text: str, parent: QWidget) -> QWidget:
        row = QWidget(parent)
        row.setObjectName(f"{self.object_prefix}{key.title()}DetailRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(label_text, row)
        label.setFixedWidth(64)
        set_ui_role(label, "fieldLabel")
        layout.addWidget(label)
        value = QLabel(_UNKNOWN_WORD, row)
        value.setObjectName(f"{self.object_prefix}{key.title()}DetailValue")
        set_ui_role(value, "valueLabel")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(value, 1)
        self.detail_values[key] = value
        return row

    def _labeled_control(self, text: str, editor: QWidget, parent: QWidget) -> QWidget:
        host = QWidget(parent)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(text, host)
        label.setFixedWidth(_MEMORY_CONTROL_LABEL_WIDTH)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        set_ui_role(label, "fieldLabel")
        layout.addWidget(label)
        editor.setParent(host)
        layout.addWidget(editor, 1)
        return host

    def _tool_button(
        self,
        text: str,
        semantic_icon: str,
        object_name: str,
        parent: QWidget,
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(object_name)
        button.setText(text)
        button.setIcon(self._icon_manager.icon(semantic_icon, size=16))
        button.setIconSize(QSize(16, 16))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setFixedHeight(MEMORY_FIELD_HEIGHT)
        button.setMinimumWidth(84)
        set_ui_variant(button, "toolbar")
        return button


__all__ = ["MEMORY_DISPLAY_FORMATS", "MEMORY_TABLE_HEADERS", "MemoryTargetPage"]
