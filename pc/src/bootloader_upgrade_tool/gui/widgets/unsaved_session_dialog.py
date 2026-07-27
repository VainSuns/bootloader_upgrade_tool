"""Application-owned confirmation dialog for an unsaved Session."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QWidget

from ..layout_metrics import (
    UNSAVED_SESSION_CARD_MAXIMUM_WIDTH,
    UNSAVED_SESSION_CARD_MINIMUM_WIDTH,
)
from ..ui_state import set_ui_variant
from .embedded_modal import EmbeddedModalDialog


class UnsavedSessionChoice(Enum):
    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


class UnsavedSessionDialog(EmbeddedModalDialog):
    """Ask whether current Session changes should be saved before continuing."""

    def __init__(
        self,
        display_name: str,
        *,
        session_path: str | Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        normalized_name = display_name.strip() or "Untitled"
        super().__init__(
            "Unsaved Session",
            icon_name="common.warning",
            icon_tone="warning",
            card_minimum_width=UNSAVED_SESSION_CARD_MINIMUM_WIDTH,
            card_maximum_width=UNSAVED_SESSION_CARD_MAXIMUM_WIDTH,
            parent=parent,
        )
        self.setProperty("modalKind", "unsavedSession")
        self.card.setProperty("modalKind", "unsavedSession")
        self._decision = UnsavedSessionChoice.CANCEL

        self.prompt_label = QLabel("Save changes before continuing?", self.content_frame)
        self.prompt_label.setObjectName("unsavedSessionPromptLabel")
        self.prompt_label.setWordWrap(True)
        self.content_layout.addWidget(self.prompt_label)

        self.description_label = QLabel(
            "The current Session contains changes that have not been saved.",
            self.content_frame,
        )
        self.description_label.setObjectName("unsavedSessionDescriptionLabel")
        self.description_label.setWordWrap(True)
        self.content_layout.addWidget(self.description_label)

        self.info_frame = QFrame(self.content_frame)
        self.info_frame.setObjectName("unsavedSessionInfoFrame")
        self.info_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        info_layout = QGridLayout(self.info_frame)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setHorizontalSpacing(16)
        info_layout.setVerticalSpacing(8)
        info_layout.setColumnStretch(1, 1)

        session_label = QLabel("Session", self.info_frame)
        session_label.setObjectName("unsavedSessionFieldLabel")
        info_layout.addWidget(session_label, 0, 0)
        self.session_value_label = QLabel(normalized_name, self.info_frame)
        self.session_value_label.setObjectName("unsavedSessionValueLabel")
        self.session_value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        info_layout.addWidget(self.session_value_label, 0, 1)

        location_label = QLabel("Location", self.info_frame)
        location_label.setObjectName("unsavedSessionFieldLabel")
        info_layout.addWidget(location_label, 1, 0)
        path_text = str(Path(session_path)) if session_path else "Not saved yet"
        self.location_value_label = QLabel(path_text, self.info_frame)
        self.location_value_label.setObjectName("unsavedSessionLocationLabel")
        self.location_value_label.setWordWrap(True)
        self.location_value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.location_value_label.setToolTip(path_text)
        info_layout.addWidget(self.location_value_label, 1, 1)
        self.content_layout.addWidget(self.info_frame)

        self.warning_frame = QFrame(self.content_frame)
        self.warning_frame.setObjectName("unsavedSessionWarningFrame")
        self.warning_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        warning_layout = QGridLayout(self.warning_frame)
        warning_layout.setContentsMargins(12, 10, 12, 10)
        self.warning_label = QLabel(
            "Unsaved changes will be lost if you discard them.",
            self.warning_frame,
        )
        self.warning_label.setObjectName("unsavedSessionWarningLabel")
        self.warning_label.setWordWrap(True)
        warning_layout.addWidget(self.warning_label, 0, 0)
        self.content_layout.addWidget(self.warning_frame)

        self.footer_layout.addStretch(1)
        self.cancel_button = QPushButton("Cancel", self.footer)
        self.cancel_button.setObjectName("unsavedSessionCancelButton")
        set_ui_variant(self.cancel_button, "secondary")
        self.cancel_button.clicked.connect(self.reject)
        self.footer_layout.addWidget(self.cancel_button)

        self.discard_button = QPushButton("Discard", self.footer)
        self.discard_button.setObjectName("unsavedSessionDiscardButton")
        set_ui_variant(self.discard_button, "dangerGhost")
        self.discard_button.clicked.connect(self._discard)
        self.footer_layout.addWidget(self.discard_button)

        self.save_button = QPushButton("Save", self.footer)
        self.save_button.setObjectName("unsavedSessionSaveButton")
        set_ui_variant(self.save_button, "primary")
        self.save_button.setDefault(True)
        self.save_button.setAutoDefault(True)
        self.save_button.clicked.connect(self._save)
        self.footer_layout.addWidget(self.save_button)

    @property
    def decision(self) -> UnsavedSessionChoice:
        return self._decision

    def _save(self) -> None:
        self._decision = UnsavedSessionChoice.SAVE
        self.accept()

    def _discard(self) -> None:
        self._decision = UnsavedSessionChoice.DISCARD
        self.accept()

    def reject(self) -> None:
        self._decision = UnsavedSessionChoice.CANCEL
        super().reject()


__all__ = ["UnsavedSessionChoice", "UnsavedSessionDialog"]
