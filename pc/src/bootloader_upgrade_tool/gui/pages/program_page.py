"""Shared static Program page used for CPU1 and CPU2 layout review.

This View module owns only presentation and local intent signals. It does not
read images, create sessions, invoke operations, access transports, touch Flash
or metadata, run/reset a target, or implement CPU2 backend behavior.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import (
    PAGE_BLOCK_SPACING,
    PAGE_MARGINS,
    PROGRAM_CONTENT_MAXIMUM_WIDTH,
    PROGRAM_IMAGE_CARD_MINIMUM_HEIGHT,
    PROGRAM_IMAGE_ROW_HEIGHT,
    PROGRAM_OPTIONS_CARD_MINIMUM_HEIGHT,
    PROGRAM_RESULT_CARD_MINIMUM_HEIGHT,
    PROGRAM_SPLITTER_HANDLE_WIDTH,
    PROGRAM_SPLITTER_INITIAL_SIZES,
    PROGRAM_STATE_MAXIMUM_WIDTH,
    PROGRAM_STATE_MINIMUM_WIDTH,
    PROGRAM_STATUS_CARD_MINIMUM_HEIGHT,
    PROGRAM_STATUS_ROW_HEIGHT,
    PROGRAM_WORKFLOW_MAXIMUM_WIDTH,
    PROGRAM_WORKFLOW_MINIMUM_WIDTH,
)
from ..ui_state import set_ui_role, set_ui_variant
from ..widgets.card import SectionCard
from ..widgets.form_rows import PathFieldRow
from ..widgets.page_header import TargetPageHeader
from ..widgets.status_widgets import StateIconLabel, StatusBadge

_TARGETS: Final = frozenset({"cpu1", "cpu2"})
_IMAGE_LABEL_WIDTH: Final = 112
_IMAGE_GRID_LABEL_WIDTH: Final = 88
_STATUS_LABEL_WIDTH: Final = 172

PROGRAM_STATUS_DEFINITIONS: Final = (
    ("metadata_valid", "Metadata Valid"),
    ("entry_point_valid", "Entry Point Valid"),
    ("image_valid", "IMAGE_VALID"),
    ("flash_app_crc32", "Flash App CRC32"),
    ("boot_attempt", "BOOT_ATTEMPT"),
    ("loaded_image_matches", "Loaded Image Matches"),
    ("app_confirmed", "APP_CONFIRMED"),
    ("confirmed_bootable", "Confirmed Bootable"),
)


class _ProgramInfoField(QWidget):
    def __init__(
        self,
        label: str,
        value: str = "—",
        *,
        prefix: str,
        suffix: str,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(f"{prefix}{suffix}Field")
        self.setFixedHeight(PROGRAM_IMAGE_ROW_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.label_widget = _field_label(label, _IMAGE_GRID_LABEL_WIDTH, self)
        layout.addWidget(self.label_widget)
        self.value_label = QLabel(value, self)
        self.value_label.setObjectName(f"{prefix}{suffix}Value")
        set_ui_role(self.value_label, "valueLabel")
        layout.addWidget(self.value_label, 1)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class _ProgramBadgeField(QWidget):
    def __init__(
        self,
        label: str,
        value: str,
        state: str,
        *,
        prefix: str,
        suffix: str,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(f"{prefix}{suffix}Field")
        self.setFixedHeight(PROGRAM_IMAGE_ROW_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.label_widget = _field_label(label, _IMAGE_GRID_LABEL_WIDTH, self)
        layout.addWidget(self.label_widget)
        self.badge = StatusBadge(
            value,
            state,
            object_name=f"{prefix}{suffix}Value",
            parent=self,
        )
        layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)

    def set_status(self, value: str, state: str) -> None:
        self.badge.set_status(value, state)


class _ProgramStatusRow(QWidget):
    def __init__(
        self,
        label: str,
        *,
        icon_manager: IconManager,
        object_name: str,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFixedHeight(PROGRAM_STATUS_ROW_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.label_widget = _field_label(label, _STATUS_LABEL_WIDTH, self, align_right=False)
        layout.addWidget(self.label_widget)
        self.state_widget = StateIconLabel(
            "Unknown",
            "unknown",
            icon_manager=icon_manager,
            object_name=f"{object_name}State",
            parent=self,
        )
        layout.addWidget(self.state_widget, 1)

    def set_status(self, text: str, state: str) -> None:
        self.state_widget.set_state(state, text=text)


class ProgramTargetPage(QWidget):
    """Shared CPU1/CPU2 Program page with no backend dependencies."""

    browseRequested = Signal(str)
    prepareRequested = Signal(str)

    def __init__(
        self,
        target: str,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        normalized = target.strip().lower()
        if normalized not in _TARGETS:
            raise ValueError("target must be 'cpu1' or 'cpu2'")

        self.target = normalized
        self.target_label = normalized.upper()
        self.object_prefix = f"program{self.target_label.title()}"
        self.setObjectName(f"{self.object_prefix}Page")
        set_ui_role(self, "page")
        self._icon_manager = icon_manager or IconManager()
        self._interactions_enabled = normalized == "cpu1"

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(PAGE_BLOCK_SPACING)
        description = (
            f"Review the {self.target_label} application image, options, results, "
            "and confirmed-bootable state."
        )
        if normalized == "cpu2":
            description += " CPU2 workflow controls are disabled in Phase 11.1."
        self.header = TargetPageHeader(
            f"{self.target_label} Program",
            target_text=self.target_label,
            target_state="neutral" if normalized == "cpu1" else "unavailable",
            description=description,
            preview=True,
            object_name=f"{self.objectName()}Header",
            parent=self,
        )
        root.addWidget(self.header)

        self.body_scroll_area = QScrollArea(self)
        self.body_scroll_area.setObjectName(f"{self.object_prefix}BodyScrollArea")
        self.body_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll_area.setWidgetResizable(True)
        self.body_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.body_scroll_area.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        root.addWidget(self.body_scroll_area, 1)

        self.content_container = QWidget(self.body_scroll_area)
        self.content_container.setObjectName(f"{self.object_prefix}ContentContainer")
        self.content_container.setMaximumWidth(PROGRAM_CONTENT_MAXIMUM_WIDTH)
        self.content_container.setMinimumWidth(
            PROGRAM_WORKFLOW_MINIMUM_WIDTH
            + PROGRAM_STATE_MINIMUM_WIDTH
            + PROGRAM_SPLITTER_HANDLE_WIDTH
        )
        self.content_container.setMinimumHeight(
            max(
                PROGRAM_IMAGE_CARD_MINIMUM_HEIGHT
                + PROGRAM_OPTIONS_CARD_MINIMUM_HEIGHT
                + PROGRAM_RESULT_CARD_MINIMUM_HEIGHT
                + (2 * PAGE_BLOCK_SPACING),
                PROGRAM_STATUS_CARD_MINIMUM_HEIGHT,
            )
        )
        content_layout = QVBoxLayout(self.content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.horizontal_splitter = QSplitter(Qt.Orientation.Horizontal, self.content_container)
        self.horizontal_splitter.setObjectName(f"{self.object_prefix}HorizontalSplitter")
        self.horizontal_splitter.setChildrenCollapsible(False)
        self.horizontal_splitter.setHandleWidth(PROGRAM_SPLITTER_HANDLE_WIDTH)
        content_layout.addWidget(self.horizontal_splitter)

        self.workflow_pane, workflow_layout = self._pane(
            "WorkflowPane",
            PROGRAM_WORKFLOW_MINIMUM_WIDTH,
            PROGRAM_WORKFLOW_MAXIMUM_WIDTH,
            right_margin=3,
        )
        self.state_pane, state_layout = self._pane(
            "StatePane",
            PROGRAM_STATE_MINIMUM_WIDTH,
            PROGRAM_STATE_MAXIMUM_WIDTH,
            left_margin=3,
        )
        self.horizontal_splitter.addWidget(self.workflow_pane)
        self.horizontal_splitter.addWidget(self.state_pane)
        self.horizontal_splitter.setStretchFactor(0, PROGRAM_SPLITTER_INITIAL_SIZES[0])
        self.horizontal_splitter.setStretchFactor(1, PROGRAM_SPLITTER_INITIAL_SIZES[1])
        self.horizontal_splitter.setSizes(list(PROGRAM_SPLITTER_INITIAL_SIZES))

        self.app_image_card = self._create_app_image_card()
        self.program_options_card = self._create_options_card()
        self.details_result_card = self._create_details_card()
        workflow_layout.addWidget(self.app_image_card)
        workflow_layout.addWidget(self.program_options_card)
        workflow_layout.addWidget(self.details_result_card, 1)

        self.status_summary_card = self._create_status_card()
        state_layout.addWidget(self.status_summary_card, 1)

        self.body_scroll_area.setWidget(self.content_container)
        self.set_interactions_enabled(self._interactions_enabled)

    @property
    def interactions_enabled(self) -> bool:
        return self._interactions_enabled

    def set_interactions_enabled(self, enabled: bool) -> None:
        self._interactions_enabled = bool(enabled)
        for widget in (
            self.image_path_row.path_edit,
            self.image_path_row.browse_button,
            self.force_load_checkbox,
            self.auto_run_checkbox,
            self.confirm_app_checkbox,
        ):
            widget.setEnabled(self._interactions_enabled)
        self._update_prepare_button()

    def set_image_summary(
        self,
        *,
        path: str = "",
        file_name: str = "—",
        entry_point: str = "—",
        image_size: str = "—",
        crc32: str = "—",
        parse_status: str = "Not parsed",
        parse_state: str = "unknown",
    ) -> None:
        self.image_path_row.path_edit.setText(path)
        # ``file_name`` remains in the public setter for future controller
        # compatibility, but the compact Program summary no longer renders it.
        _ = file_name
        for row, value in (
            (self.entry_point_row, entry_point),
            (self.image_size_row, image_size),
            (self.crc32_row, crc32),
        ):
            row.set_value(value)
        self.parse_status_row.set_status(parse_status, parse_state)

    def set_status(self, status_key: str, text: str, state: str) -> None:
        try:
            self.status_rows[status_key].set_status(text, state)
        except KeyError as exc:
            raise KeyError(f"unknown Program status key: {status_key!r}") from exc

    def set_details_text(self, text: str) -> None:
        self.details_edit.setPlainText(text)

    def append_details(self, text: str) -> None:
        self.details_edit.appendPlainText(text)

    def _pane(
        self,
        suffix: str,
        minimum: int,
        maximum: int,
        *,
        left_margin: int = 0,
        right_margin: int = 0,
    ) -> tuple[QWidget, QVBoxLayout]:
        pane = QWidget(self.horizontal_splitter)
        pane.setObjectName(f"{self.object_prefix}{suffix}")
        pane.setMinimumWidth(minimum)
        pane.setMaximumWidth(maximum)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(left_margin, 0, right_margin, 0)
        layout.setSpacing(PAGE_BLOCK_SPACING)
        return pane, layout

    def _create_app_image_card(self) -> SectionCard:
        card = SectionCard(
            "App Image",
            subtitle="Static preview; no image file is read in this phase.",
            semantic_icon="program.image.card",
            icon_manager=self._icon_manager,
            body_margins=(12, 8, 12, 8),
            body_spacing=4,
            object_name=f"{self.object_prefix}AppImageCard",
            parent=self.workflow_pane,
        )
        card.setFixedHeight(PROGRAM_IMAGE_CARD_MINIMUM_HEIGHT)
        card.body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.prepare_image_button = self._header_button(
            card,
            "Prepare",
            "program.image.prepare",
            "PrepareImageButton",
        )
        self.prepare_image_button.clicked.connect(
            lambda _checked=False: self.prepareRequested.emit(self.target)
        )

        self.image_path_row = PathFieldRow(
            "App path",
            placeholder="Select an application image",
            icon_manager=self._icon_manager,
            label_width=_IMAGE_LABEL_WIDTH,
            edit_object_name=f"{self.object_prefix}ImagePathEdit",
            button_object_name=f"{self.object_prefix}BrowseImageButton",
            object_name=f"{self.object_prefix}ImagePathRow",
            parent=card.body,
        )
        self.image_path_row.browseRequested.connect(
            lambda: self.browseRequested.emit(self.target)
        )
        self.image_path_row.path_edit.textChanged.connect(
            lambda _text: self._update_prepare_button()
        )
        self.image_path_row.setFixedHeight(PROGRAM_IMAGE_ROW_HEIGHT)
        card.add_widget(self.image_path_row)

        self.image_summary_grid = QWidget(card.body)
        self.image_summary_grid.setObjectName(f"{self.object_prefix}ImageSummaryGrid")
        grid = QGridLayout(self.image_summary_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.entry_point_row = self._grid_info_field(
            card.body, "Entry point", "EntryPoint"
        )
        self.image_size_row = self._grid_info_field(
            card.body, "Image size", "ImageSize"
        )
        self.crc32_row = self._grid_info_field(card.body, "CRC32", "Crc32")
        self.parse_status_row = self._grid_badge_field(
            card.body, "Parse status", "ParseStatus"
        )

        grid.addWidget(self.entry_point_row, 0, 0)
        grid.addWidget(self.image_size_row, 0, 1)
        grid.addWidget(self.crc32_row, 1, 0)
        grid.addWidget(self.parse_status_row, 1, 1)
        card.add_widget(self.image_summary_grid)
        return card

    def _grid_info_field(
        self,
        parent: QWidget,
        label: str,
        suffix: str,
        value: str = "—",
    ) -> _ProgramInfoField:
        return _ProgramInfoField(
            label,
            value,
            prefix=self.object_prefix,
            suffix=suffix,
            parent=parent,
        )

    def _grid_badge_field(
        self,
        parent: QWidget,
        label: str,
        suffix: str,
    ) -> _ProgramBadgeField:
        return _ProgramBadgeField(
            label,
            "Not parsed",
            "unknown",
            prefix=self.object_prefix,
            suffix=suffix,
            parent=parent,
        )

    def _create_options_card(self) -> SectionCard:
        card = SectionCard(
            "Options",
            semantic_icon="program.options.card",
            icon_manager=self._icon_manager,
            body_margins=(12, 10, 12, 10),
            object_name=f"{self.object_prefix}OptionsCard",
            parent=self.workflow_pane,
        )
        card.setMinimumHeight(PROGRAM_OPTIONS_CARD_MINIMUM_HEIGHT)
        host = QWidget(card.body)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        self.force_load_checkbox = self._option("Force Load", "ForceLoad", host)
        self.auto_run_checkbox = self._option("Auto Run after Load", "AutoRun", host)
        self.confirm_app_checkbox = self._option("Confirm App", "ConfirmApp", host)
        for checkbox in (
            self.force_load_checkbox,
            self.auto_run_checkbox,
            self.confirm_app_checkbox,
        ):
            layout.addWidget(checkbox)
        layout.addStretch(1)
        card.add_widget(host)
        return card

    def _option(self, text: str, suffix: str, parent: QWidget) -> QCheckBox:
        checkbox = QCheckBox(text, parent)
        checkbox.setObjectName(f"{self.object_prefix}{suffix}CheckBox")
        return checkbox

    def _create_status_card(self) -> SectionCard:
        card = SectionCard(
            "Status Summary",
            subtitle="Unknown until real status is supplied by a future controller.",
            semantic_icon="program.status.card",
            icon_manager=self._icon_manager,
            object_name=f"{self.object_prefix}StatusSummaryCard",
            parent=self.state_pane,
        )
        card.setMinimumHeight(PROGRAM_STATUS_CARD_MINIMUM_HEIGHT)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        card.body_layout.setSpacing(4)
        card.body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.status_rows: dict[str, _ProgramStatusRow] = {}
        for key, label in PROGRAM_STATUS_DEFINITIONS:
            row = _ProgramStatusRow(
                label,
                icon_manager=self._icon_manager,
                object_name=f"{self.object_prefix}Status{_camel_suffix(key)}",
                parent=card.body,
            )
            self.status_rows[key] = row
            card.add_widget(row)
        return card

    def _create_details_card(self) -> SectionCard:
        card = SectionCard(
            "Details / Result",
            subtitle="Read-only local output; not a hardware activity log.",
            semantic_icon="program.result.card",
            icon_manager=self._icon_manager,
            object_name=f"{self.object_prefix}DetailsResultCard",
            parent=self.workflow_pane,
        )
        card.setMinimumHeight(PROGRAM_RESULT_CARD_MINIMUM_HEIGHT)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.copy_details_button = self._header_button(
            card, "Copy", "console.copy", "CopyDetailsButton"
        )
        self.clear_details_button = self._header_button(
            card, "Clear", "console.clear", "ClearDetailsButton"
        )
        self.details_edit = QPlainTextEdit(card.body)
        self.details_edit.setObjectName(f"{self.object_prefix}DetailsOutput")
        self.details_edit.setReadOnly(True)
        self.details_edit.setUndoRedoEnabled(False)
        self.details_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.details_edit.setPlainText(
            "Static layout preview.\n"
            "No image has been selected and no target operation has been executed."
        )
        set_ui_role(self.details_edit, "codeText")
        card.add_widget(self.details_edit, 1)
        self.copy_details_button.clicked.connect(self._copy_details)
        self.clear_details_button.clicked.connect(self.details_edit.clear)
        return card

    def _header_button(
        self,
        card: SectionCard,
        text: str,
        icon: str,
        suffix: str,
    ) -> QToolButton:
        button = QToolButton(card.header)
        button.setObjectName(f"{self.object_prefix}{suffix}")
        button.setText(text)
        button.setToolTip(text)
        button.setAccessibleName(f"{text} {self.target_label}")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIcon(self._icon_manager.icon(icon, size=16))
        button.setIconSize(QSize(16, 16))
        set_ui_variant(button, "toolbar")
        card.header.add_action_widget(button)
        return button

    def _copy_details(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.details_edit.toPlainText())

    def _update_prepare_button(self) -> None:
        self.prepare_image_button.setEnabled(
            self._interactions_enabled
            and bool(self.image_path_row.path_edit.text().strip())
        )


def _field_label(
    text: str,
    width: int,
    parent: QWidget,
    *,
    align_right: bool = True,
) -> QLabel:
    label = QLabel(text, parent)
    label.setFixedWidth(width)
    if align_right:
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    set_ui_role(label, "fieldLabel")
    return label


def _camel_suffix(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


__all__ = ["PROGRAM_STATUS_DEFINITIONS", "ProgramTargetPage"]
