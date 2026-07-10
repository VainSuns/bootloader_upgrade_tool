"""Reusable local-only Flash-sector selection controls.

These widgets edit a local sector selection only. They do not import operations,
open a transport, or execute an erase request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..ui_state import set_ui_role, set_ui_variant


@dataclass(frozen=True, slots=True)
class FlashSectorOption:
    """One selectable Flash sector shown by the local editor."""

    sector_id: str
    start_address: int
    end_address: int
    bit_index: int
    protected: bool = False

    @property
    def display_text(self) -> str:
        suffix = " — Protected" if self.protected else ""
        return (
            f"Sector {self.sector_id} "
            f"(0x{self.start_address:06X} - 0x{self.end_address:06X}){suffix}"
        )


class SectorSelectionDialog(QDialog):
    """Modal, dynamically generated sector checklist."""

    def __init__(
        self,
        sectors: Sequence[FlashSectorOption],
        *,
        selected_sector_ids: Iterable[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not sectors:
            raise ValueError("sectors must not be empty")

        self.setObjectName("sectorSelectionDialog")
        self.setWindowTitle("Select Flash Sectors")
        self.resize(520, 520)
        self._sectors = tuple(sectors)
        selected = set(selected_sector_ids)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Custom Sector Selection", self)
        title.setObjectName("sectorSelectionTitle")
        set_ui_role(title, "sectionTitle")
        root.addWidget(title)

        notice = QLabel(
            "Select the application sectors included in the custom erase mask. "
            "Protected sectors cannot be selected.",
            self,
        )
        notice.setObjectName("sectorSelectionNotice")
        notice.setWordWrap(True)
        set_ui_role(notice, "helperText")
        root.addWidget(notice)

        scroll = QScrollArea(self)
        scroll.setObjectName("sectorSelectionScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll, 1)

        body = QWidget(scroll)
        body.setObjectName("sectorSelectionBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.setSpacing(6)
        scroll.setWidget(body)

        self.checkboxes: dict[str, QCheckBox] = {}
        for sector in self._sectors:
            checkbox = QCheckBox(sector.display_text, body)
            checkbox.setObjectName(f"sectorSelection{sector.sector_id}CheckBox")
            checkbox.setChecked(
                sector.sector_id in selected and not sector.protected
            )
            checkbox.setEnabled(not sector.protected)
            self.checkboxes[sector.sector_id] = checkbox
            body_layout.addWidget(checkbox)
        body_layout.addStretch(1)

        selection_actions = QHBoxLayout()
        selection_actions.setContentsMargins(0, 0, 0, 0)
        selection_actions.setSpacing(8)
        self.select_all_button = QPushButton("Select All", self)
        self.select_all_button.setObjectName("sectorSelectionSelectAllButton")
        set_ui_variant(self.select_all_button, "secondary")
        self.clear_button = QPushButton("Clear", self)
        self.clear_button.setObjectName("sectorSelectionClearButton")
        set_ui_variant(self.clear_button, "secondary")
        selection_actions.addWidget(self.select_all_button)
        selection_actions.addWidget(self.clear_button)
        selection_actions.addStretch(1)
        root.addLayout(selection_actions)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.button_box.setObjectName("sectorSelectionButtonBox")
        root.addWidget(self.button_box)

        self.select_all_button.clicked.connect(self._select_all)
        self.clear_button.clicked.connect(self._clear)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    @property
    def sectors(self) -> tuple[FlashSectorOption, ...]:
        return self._sectors

    def selected_sector_ids(self) -> tuple[str, ...]:
        return tuple(
            sector.sector_id
            for sector in self._sectors
            if not sector.protected
            and self.checkboxes[sector.sector_id].isChecked()
        )

    def selected_mask(self) -> int:
        mask = 0
        selected = set(self.selected_sector_ids())
        for sector in self._sectors:
            if sector.sector_id in selected:
                mask |= 1 << sector.bit_index
        return mask

    def _select_all(self) -> None:
        for sector in self._sectors:
            if not sector.protected:
                self.checkboxes[sector.sector_id].setChecked(True)

    def _clear(self) -> None:
        for sector in self._sectors:
            if not sector.protected:
                self.checkboxes[sector.sector_id].setChecked(False)


class SectorMaskSelector(QWidget):
    """Read-only mask summary with a local modal editor."""

    selectionChanged = Signal(object, int)

    def __init__(
        self,
        sectors: Sequence[FlashSectorOption],
        *,
        selected_sector_ids: Iterable[str] = (),
        object_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not sectors:
            raise ValueError("sectors must not be empty")
        if object_name:
            self.setObjectName(object_name)
        self._sectors = tuple(sectors)
        self._selected_sector_ids: tuple[str, ...] = ()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.summary_edit = QLineEdit(self)
        self.summary_edit.setObjectName(f"{object_name}SummaryEdit")
        self.summary_edit.setReadOnly(True)
        self.summary_edit.setPlaceholderText("No sectors selected")
        self.summary_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(self.summary_edit, 1)

        self.edit_button = QPushButton("Edit…", self)
        self.edit_button.setObjectName(f"{object_name}EditButton")
        self.edit_button.setToolTip("Edit custom Flash-sector selection")
        self.edit_button.setAccessibleName("Edit custom Flash-sector selection")
        self.edit_button.setMinimumWidth(72)
        set_ui_variant(self.edit_button, "secondary")
        layout.addWidget(self.edit_button)

        self.edit_button.clicked.connect(self.open_editor)
        self.set_selected_sector_ids(selected_sector_ids, emit=False)

    @property
    def sectors(self) -> tuple[FlashSectorOption, ...]:
        return self._sectors

    def selected_sector_ids(self) -> tuple[str, ...]:
        return self._selected_sector_ids

    def selected_mask(self) -> int:
        selected = set(self._selected_sector_ids)
        mask = 0
        for sector in self._sectors:
            if sector.sector_id in selected:
                mask |= 1 << sector.bit_index
        return mask

    def set_selected_sector_ids(
        self,
        sector_ids: Iterable[str],
        *,
        emit: bool = True,
    ) -> None:
        requested = set(sector_ids)
        ordered = tuple(
            sector.sector_id
            for sector in self._sectors
            if sector.sector_id in requested and not sector.protected
        )
        changed = ordered != self._selected_sector_ids
        self._selected_sector_ids = ordered
        self._refresh_summary()
        if emit and changed:
            self.selectionChanged.emit(ordered, self.selected_mask())

    def open_editor(self) -> None:
        dialog = SectorSelectionDialog(
            self._sectors,
            selected_sector_ids=self._selected_sector_ids,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_selected_sector_ids(dialog.selected_sector_ids())

    def _refresh_summary(self) -> None:
        if not self._selected_sector_ids:
            self.summary_edit.clear()
            self.summary_edit.setPlaceholderText("No sectors selected")
            return
        sector_text = ", ".join(self._selected_sector_ids)
        self.summary_edit.setText(
            f"{sector_text}  |  mask 0x{self.selected_mask():08X}"
        )


__all__ = [
    "FlashSectorOption",
    "SectorMaskSelector",
    "SectorSelectionDialog",
]
