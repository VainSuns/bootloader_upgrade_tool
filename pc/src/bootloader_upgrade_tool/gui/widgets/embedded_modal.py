"""Portable application-owned modal overlay for Session presentation dialogs.

The overlay intentionally does not use ``WA_TranslucentBackground``. Some
Windows graphics stacks fail to composite translucent frameless top-level
widgets consistently, leaving only child controls visible over the main window.
This implementation snapshots the parent client area and paints the snapshot,
scrim, shadow, and solid card itself on an opaque dialog surface.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPaintEvent, QPainter, QPainterPath, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..icon_manager import IconManager
from ..layout_metrics import (
    EMBEDDED_MODAL_CARD_CONTENT_MARGINS,
    EMBEDDED_MODAL_CLOSE_BUTTON_SIZE,
    EMBEDDED_MODAL_OVERLAY_MARGIN,
    EMBEDDED_MODAL_SECTION_SPACING,
    EMBEDDED_MODAL_TITLE_ICON_SIZE,
)
from ..theme_tokens import THEME_TOKENS

_CARD_RADIUS = 8.0
_RGBA_PATTERN = re.compile(
    r"rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)"
)


def _theme_color(name: str) -> QColor:
    value = THEME_TOKENS[name]
    color = QColor(value)
    if color.isValid():
        return color

    match = _RGBA_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid GUI color token {name}: {value!r}")
    channels = tuple(max(0, min(255, int(item))) for item in match.groups())
    return QColor(*channels)


class _EmbeddedModalCard(QFrame):
    """Solid card whose core surface never depends on platform QSS compositing."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("embeddedModalCard")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)
            painter.fillPath(path, _theme_color("SURFACE"))
            painter.setPen(_theme_color("BORDER_STRONG"))
            painter.drawPath(path)
        finally:
            painter.end()


class EmbeddedModalDialog(QDialog):
    """Frameless, opaque modal overlay constrained to the parent client area."""

    def __init__(
        self,
        title: str,
        *,
        icon_name: str,
        icon_tone: str = "neutral",
        card_minimum_width: int,
        card_maximum_width: int,
        card_minimum_height: int = 0,
        card_maximum_height: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not title.strip():
            raise ValueError("title must not be empty")
        if card_minimum_width <= 0 or card_maximum_width < card_minimum_width:
            raise ValueError("invalid embedded modal card width range")
        if card_minimum_height < 0:
            raise ValueError("card_minimum_height must not be negative")
        if card_maximum_height is not None and card_maximum_height < card_minimum_height:
            raise ValueError("card_maximum_height must not be smaller than the minimum")

        self._overlay_host = self._resolve_overlay_host(parent)
        self._watched_widgets: list[QWidget] = []
        self._icon_manager = getattr(parent, "icon_manager", None) or IconManager()
        self._card_minimum_width = card_minimum_width
        self._card_maximum_width = card_maximum_width
        self._card_minimum_height = card_minimum_height
        self._card_maximum_height = card_maximum_height
        self._background_snapshot = QPixmap()

        self.setObjectName("embeddedModalOverlay")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setSizeGripEnabled(False)

        self._build_shell(title, icon_name, icon_tone)
        self._install_geometry_watchers(parent)
        self._sync_overlay_geometry()
        self._refresh_background_snapshot()

    def _build_shell(self, title: str, icon_name: str, icon_tone: str) -> None:
        overlay_layout = QVBoxLayout(self)
        overlay_layout.setContentsMargins(
            EMBEDDED_MODAL_OVERLAY_MARGIN,
            EMBEDDED_MODAL_OVERLAY_MARGIN,
            EMBEDDED_MODAL_OVERLAY_MARGIN,
            EMBEDDED_MODAL_OVERLAY_MARGIN,
        )
        overlay_layout.setSpacing(0)

        self.card = _EmbeddedModalCard(self)
        self.card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        if self._card_minimum_height:
            self.card.setMinimumHeight(self._card_minimum_height)
        overlay_layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)

        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(*EMBEDDED_MODAL_CARD_CONTENT_MARGINS)
        self.card_layout.setSpacing(EMBEDDED_MODAL_SECTION_SPACING)

        self.header = QFrame(self.card)
        self.header.setObjectName("embeddedModalHeader")
        self.header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_icon = QLabel(self.header)
        self.title_icon.setObjectName("embeddedModalTitleIcon")
        self.title_icon.setFixedSize(*EMBEDDED_MODAL_CLOSE_BUTTON_SIZE)
        self.title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_icon.setPixmap(
            self._icon_manager.icon(
                icon_name,
                tone=icon_tone,
                size=EMBEDDED_MODAL_TITLE_ICON_SIZE,
            ).pixmap(EMBEDDED_MODAL_TITLE_ICON_SIZE, EMBEDDED_MODAL_TITLE_ICON_SIZE)
        )
        header_layout.addWidget(self.title_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel(title, self.header)
        self.title_label.setObjectName("embeddedModalTitleLabel")
        self.title_label.setWordWrap(True)
        self.title_label.setMinimumHeight(EMBEDDED_MODAL_CLOSE_BUTTON_SIZE[1])
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        header_layout.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)

        self.close_button = QToolButton(self.header)
        self.close_button.setObjectName("embeddedModalCloseButton")
        self.close_button.setAccessibleName("Close dialog")
        self.close_button.setToolTip("Close")
        self.close_button.setIcon(self._icon_manager.icon("common.close", size=16))
        self.close_button.setIconSize(QSize(16, 16))
        self.close_button.setFixedSize(*EMBEDDED_MODAL_CLOSE_BUTTON_SIZE)
        self.close_button.clicked.connect(self.reject)
        header_layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.card_layout.addWidget(self.header)

        self.content_frame = QFrame(self.card)
        self.content_frame.setObjectName("embeddedModalContent")
        self.content_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.content_layout = QVBoxLayout(self.content_frame)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.card_layout.addWidget(self.content_frame, 1)

        self.footer = QFrame(self.card)
        self.footer.setObjectName("embeddedModalFooter")
        self.footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(0, 14, 0, 0)
        self.footer_layout.setSpacing(8)
        self.card_layout.addWidget(self.footer)

    def _install_geometry_watchers(self, parent: QWidget | None) -> None:
        candidates: list[QWidget] = []
        if self._overlay_host is not None:
            candidates.append(self._overlay_host)
        if parent is not None and parent.window() is not None:
            candidates.append(parent.window())
        for widget in candidates:
            if widget not in self._watched_widgets:
                widget.installEventFilter(self)
                self._watched_widgets.append(widget)

    @staticmethod
    def _resolve_overlay_host(parent: QWidget | None) -> QWidget | None:
        if parent is None:
            return None
        central_widget = getattr(parent, "centralWidget", None)
        if callable(central_widget):
            resolved = central_widget()
            if isinstance(resolved, QWidget):
                return resolved
        return parent

    def _refresh_background_snapshot(self) -> None:
        host = self._overlay_host
        if host is None:
            self._background_snapshot = QPixmap()
            self.update()
            return
        try:
            snapshot = host.grab()
        except RuntimeError:
            snapshot = QPixmap()
        self._background_snapshot = snapshot
        self.update()

    def _sync_overlay_geometry(self) -> None:
        host = self._overlay_host
        if host is None:
            fallback_width = self._card_minimum_width + 2 * EMBEDDED_MODAL_OVERLAY_MARGIN
            fallback_height = max(
                360,
                self._card_minimum_height + 2 * EMBEDDED_MODAL_OVERLAY_MARGIN,
            )
            if self.width() <= 0 or self.height() <= 0:
                self.resize(fallback_width, fallback_height)
            available_size = self.size()
        else:
            available_size = host.size()
            if available_size.width() <= 0 or available_size.height() <= 0:
                available_size = host.sizeHint().expandedTo(QSize(640, 480))
            global_top_left = host.mapToGlobal(QPoint(0, 0))
            self.setGeometry(
                global_top_left.x(),
                global_top_left.y(),
                available_size.width(),
                available_size.height(),
            )

        available_width = max(
            320,
            available_size.width() - 2 * EMBEDDED_MODAL_OVERLAY_MARGIN,
        )
        card_width = min(self._card_maximum_width, available_width)
        if available_width >= self._card_minimum_width:
            card_width = max(self._card_minimum_width, card_width)
        self.card.setFixedWidth(card_width)

        host_height_limit = max(
            240,
            available_size.height() - 2 * EMBEDDED_MODAL_OVERLAY_MARGIN,
        )
        maximum_height = host_height_limit
        if self._card_maximum_height is not None:
            maximum_height = min(maximum_height, self._card_maximum_height)
        self.card.setMaximumHeight(maximum_height)

    def _remove_geometry_watchers(self) -> None:
        watched_widgets = tuple(getattr(self, "_watched_widgets", ()))
        watched_list = getattr(self, "_watched_widgets", None)
        if isinstance(watched_list, list):
            watched_list.clear()
        for widget in watched_widgets:
            try:
                widget.removeEventFilter(self)
            except RuntimeError:
                pass

    def _schedule_geometry_sync(self) -> None:
        try:
            self._sync_overlay_geometry()
            self._refresh_background_snapshot()
        except RuntimeError:
            return

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        watched_widgets = getattr(self, "_watched_widgets", ())
        try:
            event_type = event.type()
        except RuntimeError:
            return False

        if watched in watched_widgets and event_type in {
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
        }:
            QTimer.singleShot(0, self._schedule_geometry_sync)

        try:
            return super().eventFilter(watched, event)
        except RuntimeError:
            return False

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.fillRect(self.rect(), _theme_color("WINDOW_BG"))

            snapshot = self._background_snapshot
            if not snapshot.isNull():
                device_ratio = max(1.0, float(snapshot.devicePixelRatio()))
                source = QRectF(
                    0.0,
                    0.0,
                    snapshot.width() / device_ratio,
                    snapshot.height() / device_ratio,
                )
                painter.drawPixmap(QRectF(self.rect()), snapshot, source)

            painter.fillRect(self.rect(), _theme_color("MODAL_SCRIM"))

            card_rect = QRectF(self.card.geometry())
            if card_rect.width() > 0 and card_rect.height() > 0:
                shadow_base = _theme_color("TEXT_PRIMARY")
                for expansion, y_offset, alpha in (
                    (8.0, 8.0, 18),
                    (4.0, 6.0, 26),
                    (1.5, 4.0, 34),
                ):
                    shadow = QColor(shadow_base)
                    shadow.setAlpha(alpha)
                    rect = card_rect.adjusted(
                        -expansion,
                        -expansion,
                        expansion,
                        expansion,
                    )
                    rect.translate(0.0, y_offset)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(shadow)
                    painter.drawRoundedRect(
                        rect,
                        _CARD_RADIUS + expansion,
                        _CARD_RADIUS + expansion,
                    )
        finally:
            painter.end()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        self._sync_overlay_geometry()
        self._refresh_background_snapshot()
        super().showEvent(event)
        self.raise_()

    def done(self, result: int) -> None:
        self._remove_geometry_watchers()
        super().done(result)


__all__ = ["EmbeddedModalDialog"]
