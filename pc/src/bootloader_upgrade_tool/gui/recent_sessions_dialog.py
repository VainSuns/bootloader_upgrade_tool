"""Recent Session picker that keeps missing files visible."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .persistence_models import RecentSessionEntry


class RecentSessionsDialog(QDialog):
    openRequested = Signal(str)
    removeRequested = Signal(str)

    def __init__(
        self,
        entries: tuple[RecentSessionEntry, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("recentSessionsDialog")
        self.setWindowTitle("Recent Sessions")
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3, self)
        self.table.setObjectName("recentSessionsTable")
        self.table.setHorizontalHeaderLabels(("Path", "Last saved (UTC)", "Status"))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.open_button = QPushButton("Open", self)
        self.open_button.setObjectName("recentSessionsOpenButton")
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.setObjectName("recentSessionsRemoveButton")
        actions.addWidget(self.open_button)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close_buttons.setObjectName("recentSessionsCloseButtons")
        actions.addWidget(close_buttons)
        layout.addLayout(actions)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.itemDoubleClicked.connect(lambda _item: self._emit_open())
        self.open_button.clicked.connect(self._emit_open)
        self.remove_button.clicked.connect(self._emit_remove)
        close_buttons.rejected.connect(self.close)
        self.set_entries(entries)

    def set_entries(self, entries: tuple[RecentSessionEntry, ...]) -> None:
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            available = Path(entry.path).is_file()
            path_item = QTableWidgetItem(entry.path)
            path_item.setData(256, entry.path)
            self.table.setItem(row, 0, path_item)
            self.table.setItem(row, 1, QTableWidgetItem(entry.last_saved_at_utc.isoformat()))
            self.table.setItem(row, 2, QTableWidgetItem("Available" if available else "Missing"))
        self._update_actions()

    def _selected(self) -> tuple[str, bool] | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        path = self.table.item(row, 0).text()
        return path, self.table.item(row, 2).text() == "Available"

    def _update_actions(self) -> None:
        selected = self._selected()
        self.open_button.setEnabled(bool(selected and selected[1]))
        self.remove_button.setEnabled(selected is not None)

    def _emit_open(self) -> None:
        selected = self._selected()
        if selected and selected[1]:
            self.openRequested.emit(selected[0])

    def _emit_remove(self) -> None:
        selected = self._selected()
        if selected:
            self.removeRequested.emit(selected[0])


__all__ = ["RecentSessionsDialog"]
