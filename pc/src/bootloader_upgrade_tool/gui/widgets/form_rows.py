"""Finite form-row helpers for the approved static GUI layouts."""

from __future__ import annotations

from PySide6.QtCore import Signal, QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import (
    INPUT_MINIMUM_HEIGHT,
    SETTINGS_BROWSE_BUTTON_SIZE,
    SETTINGS_FORM_LABEL_WIDTH,
    SETTINGS_FORM_ROW_MINIMUM_HEIGHT,
)
from ..ui_state import set_ui_role, set_ui_variant


class LabeledFieldRow(QWidget):
    """Fixed-width label plus one caller-supplied editor and optional helper text."""

    def __init__(
        self,
        label: str,
        editor: QWidget,
        *,
        helper_text: str = "",
        label_width: int = SETTINGS_FORM_LABEL_WIDTH,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.editor = editor
        self.setMinimumHeight(SETTINGS_FORM_ROW_MINIMUM_HEIGHT)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        self.label_widget = QLabel(label, row)
        self.label_widget.setFixedWidth(label_width)
        self.label_widget.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        set_ui_role(self.label_widget, "fieldLabel")
        row_layout.addWidget(self.label_widget)

        editor.setMinimumHeight(INPUT_MINIMUM_HEIGHT)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row_layout.addWidget(editor, 1)
        outer.addWidget(row)

        self.helper_label = QLabel(helper_text, self)
        self.helper_label.setWordWrap(True)
        self.helper_label.setContentsMargins(label_width + 8, 0, 0, 0)
        self.helper_label.setVisible(bool(helper_text))
        set_ui_role(self.helper_label, "helperText")
        outer.addWidget(self.helper_label)

    def set_helper_text(self, helper_text: str) -> None:
        self.helper_label.setText(helper_text)
        self.helper_label.setVisible(bool(helper_text))


class PathFieldRow(QWidget):
    """Path line edit plus semantic Browse tool button; no file dialog is opened."""

    browseRequested = Signal()

    def __init__(
        self,
        label: str,
        *,
        path: str = "",
        placeholder: str = "",
        semantic_icon: str = "program.image.browse",
        icon_manager: IconManager | None = None,
        label_width: int = SETTINGS_FORM_LABEL_WIDTH,
        edit_object_name: str | None = None,
        button_object_name: str | None = None,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        manager = icon_manager or IconManager()
        self.setMinimumHeight(SETTINGS_FORM_ROW_MINIMUM_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.label_widget = QLabel(label, self)
        self.label_widget.setFixedWidth(label_width)
        self.label_widget.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        set_ui_role(self.label_widget, "fieldLabel")
        layout.addWidget(self.label_widget)

        self.path_edit = QLineEdit(path, self)
        if edit_object_name:
            self.path_edit.setObjectName(edit_object_name)
        self.path_edit.setPlaceholderText(placeholder)
        self.path_edit.setMinimumHeight(INPUT_MINIMUM_HEIGHT)
        layout.addWidget(self.path_edit, 1)

        self.browse_button = QToolButton(self)
        if button_object_name:
            self.browse_button.setObjectName(button_object_name)
        self.browse_button.setText("Browse")
        self.browse_button.setToolTip("Browse")
        self.browse_button.setAccessibleName(f"Browse {label}")
        self.browse_button.setIcon(manager.icon(semantic_icon, size=16))
        self.browse_button.setIconSize(QSize(16, 16))
        self.browse_button.setFixedSize(*SETTINGS_BROWSE_BUTTON_SIZE)
        set_ui_variant(self.browse_button, "toolbar")
        self.browse_button.clicked.connect(self.browseRequested.emit)
        layout.addWidget(self.browse_button)


class ReadOnlyValueRow(QWidget):
    """Fixed label plus selectable read-only value text."""

    def __init__(
        self,
        label: str,
        value: str = "—",
        *,
        label_width: int = SETTINGS_FORM_LABEL_WIDTH,
        value_object_name: str | None = None,
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setMinimumHeight(SETTINGS_FORM_ROW_MINIMUM_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.label_widget = QLabel(label, self)
        self.label_widget.setFixedWidth(label_width)
        self.label_widget.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        set_ui_role(self.label_widget, "fieldLabel")
        layout.addWidget(self.label_widget)

        self.value_label = QLabel(value, self)
        if value_object_name:
            self.value_label.setObjectName(value_object_name)
        self.value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.value_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        set_ui_role(self.value_label, "valueLabel")
        layout.addWidget(self.value_label, 1)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
