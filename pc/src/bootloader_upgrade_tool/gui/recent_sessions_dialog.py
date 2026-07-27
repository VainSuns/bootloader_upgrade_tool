"""Application-owned Recent Sessions picker with missing-file visibility."""

from __future__ import annotations

from datetime import timezone
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .layout_metrics import (
    RECENT_SESSION_ROW_HEIGHT,
    RECENT_SESSIONS_CARD_MAXIMUM_HEIGHT,
    RECENT_SESSIONS_CARD_MAXIMUM_WIDTH,
    RECENT_SESSIONS_CARD_MINIMUM_HEIGHT,
    RECENT_SESSIONS_CARD_MINIMUM_WIDTH,
)
from .persistence_models import RecentSessionEntry
from .ui_state import set_ui_state, set_ui_variant
from .widgets.embedded_modal import EmbeddedModalDialog

_PATH_ROLE = int(Qt.ItemDataRole.UserRole)
_AVAILABLE_ROLE = _PATH_ROLE + 1


class _RecentSessionRow(QFrame):
    def __init__(
        self,
        entry: RecentSessionEntry,
        *,
        available: bool,
        icon_manager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("recentSessionRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QGridLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(3)
        layout.setColumnStretch(1, 1)

        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("recentSessionFileIcon")
        self.icon_label.setFixedSize(28, 28)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setPixmap(
            icon_manager.icon(
                "program.image.card",
                tone="neutral" if available else "warning",
                size=22,
            ).pixmap(22, 22)
        )
        layout.addWidget(self.icon_label, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)

        name = Path(entry.path).name or entry.path
        self.name_label = QLabel(name, self)
        self.name_label.setObjectName("recentSessionNameLabel")
        self.name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.name_label, 0, 1)

        self.status_label = QLabel("Available" if available else "Missing", self)
        self.status_label.setObjectName("recentSessionStatusBadge")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_ui_state(self.status_label, "success" if available else "warning")
        layout.addWidget(self.status_label, 0, 2, Qt.AlignmentFlag.AlignRight)

        self.path_label = QLabel(entry.path, self)
        self.path_label.setObjectName("recentSessionPathLabel")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.path_label.setToolTip(entry.path)
        self.path_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        layout.addWidget(self.path_label, 1, 1, 1, 2)

        saved = entry.last_saved_at_utc.astimezone(timezone.utc)
        self.saved_label = QLabel(
            f"Last saved: {saved:%Y-%m-%d %H:%M:%S} UTC",
            self,
        )
        self.saved_label.setObjectName("recentSessionSavedLabel")
        layout.addWidget(self.saved_label, 2, 1, 1, 2)


class RecentSessionsDialog(EmbeddedModalDialog):
    openRequested = Signal(str)
    removeRequested = Signal(str)

    def __init__(
        self,
        entries: tuple[RecentSessionEntry, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Recent Sessions",
            icon_name="ribbon.session.recent",
            icon_tone="primary",
            card_minimum_width=RECENT_SESSIONS_CARD_MINIMUM_WIDTH,
            card_maximum_width=RECENT_SESSIONS_CARD_MAXIMUM_WIDTH,
            card_minimum_height=RECENT_SESSIONS_CARD_MINIMUM_HEIGHT,
            card_maximum_height=RECENT_SESSIONS_CARD_MAXIMUM_HEIGHT,
            parent=parent,
        )
        self.setObjectName("embeddedModalOverlay")
        self.setProperty("modalKind", "recentSessions")
        self.card.setProperty("modalKind", "recentSessions")

        self.description_label = QLabel(
            "Open a recently saved Session. Missing files remain visible so they can "
            "be removed from the list.",
            self.content_frame,
        )
        self.description_label.setObjectName("recentSessionsDescriptionLabel")
        self.description_label.setWordWrap(True)
        self.content_layout.addWidget(self.description_label)

        self.content_stack = QStackedWidget(self.content_frame)
        self.content_stack.setObjectName("recentSessionsContentStack")
        self.content_layout.addWidget(self.content_stack, 1)

        self.list = QListWidget(self.content_stack)
        self.list.setObjectName("recentSessionsList")
        self.list.setSelectionBehavior(QListWidget.SelectionBehavior.SelectRows)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSpacing(4)
        self.content_stack.addWidget(self.list)

        self.empty_widget = QWidget(self.content_stack)
        self.empty_widget.setObjectName("recentSessionsEmptyState")
        self.empty_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setContentsMargins(24, 36, 24, 36)
        empty_layout.setSpacing(8)
        empty_layout.addStretch(1)
        self.empty_icon = QLabel(self.empty_widget)
        self.empty_icon.setObjectName("recentSessionsEmptyIcon")
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_icon.setPixmap(
            self._icon_manager.icon(
                "ribbon.session.recent",
                tone="disabled",
                size=36,
            ).pixmap(36, 36)
        )
        empty_layout.addWidget(self.empty_icon)
        self.empty_title = QLabel("No recent sessions", self.empty_widget)
        self.empty_title.setObjectName("recentSessionsEmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_message = QLabel(
            "Sessions opened or saved by this application will appear here.",
            self.empty_widget,
        )
        self.empty_message.setObjectName("recentSessionsEmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_message.setWordWrap(True)
        empty_layout.addWidget(self.empty_message)
        empty_layout.addStretch(1)
        self.content_stack.addWidget(self.empty_widget)

        self.remove_button = QPushButton("Remove from list", self.footer)
        self.remove_button.setObjectName("recentSessionsRemoveButton")
        set_ui_variant(self.remove_button, "dangerGhost")
        self.footer_layout.addWidget(self.remove_button)
        self.footer_layout.addStretch(1)

        self.close_list_button = QPushButton("Close", self.footer)
        self.close_list_button.setObjectName("recentSessionsCloseButton")
        set_ui_variant(self.close_list_button, "secondary")
        self.close_list_button.clicked.connect(self.reject)
        self.footer_layout.addWidget(self.close_list_button)

        self.open_button = QPushButton("Open", self.footer)
        self.open_button.setObjectName("recentSessionsOpenButton")
        set_ui_variant(self.open_button, "primary")
        self.open_button.setDefault(True)
        self.open_button.setAutoDefault(True)
        self.footer_layout.addWidget(self.open_button)

        self.list.itemSelectionChanged.connect(self._update_actions)
        self.list.itemDoubleClicked.connect(lambda _item: self._emit_open())
        self.open_button.clicked.connect(self._emit_open)
        self.remove_button.clicked.connect(self._emit_remove)
        self.set_entries(entries)

    def set_entries(self, entries: tuple[RecentSessionEntry, ...]) -> None:
        selected = self._selected()
        selected_path = selected[0] if selected else None
        self.list.clear()
        selected_item = None
        for entry in entries:
            available = Path(entry.path).is_file()
            item = QListWidgetItem(self.list)
            item.setData(_PATH_ROLE, entry.path)
            item.setData(_AVAILABLE_ROLE, available)
            item.setSizeHint(QSize(0, RECENT_SESSION_ROW_HEIGHT))
            row = _RecentSessionRow(
                entry,
                available=available,
                icon_manager=self._icon_manager,
                parent=self.list,
            )
            self.list.setItemWidget(item, row)
            if entry.path == selected_path:
                selected_item = item

        has_entries = self.list.count() > 0
        self.content_stack.setCurrentWidget(self.list if has_entries else self.empty_widget)
        if selected_item is not None:
            self.list.setCurrentItem(selected_item)
        else:
            self.list.clearSelection()
            self.list.setCurrentRow(-1)
        self._update_actions()

    def _selected(self) -> tuple[str, bool] | None:
        item = self.list.currentItem()
        if item is None or not item.isSelected():
            return None
        path = item.data(_PATH_ROLE)
        if not isinstance(path, str):
            return None
        return path, bool(item.data(_AVAILABLE_ROLE))

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
