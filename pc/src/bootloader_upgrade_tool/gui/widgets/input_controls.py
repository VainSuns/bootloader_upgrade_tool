"""Input widgets with project-owned, always-visible direction indicators.

Qt style sheets may suppress Fusion's native combo/spin arrows after styling
subcontrols.  These wrappers render semantic Tabler indicators as transparent
child overlays while leaving the native popup and step hit areas intact.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QLabel, QSpinBox, QWidget

from ..icon_manager import IconManager

_INDICATOR_ICON_SIZE = 12
_COMBO_INDICATOR_WIDTH = 24
_SPIN_INDICATOR_WIDTH = 22


class IndicatorComboBox(QComboBox):
    """QComboBox with a semantic down/up chevron overlay."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        icon_manager: IconManager | None = None,
        indicator_width: int = _COMBO_INDICATOR_WIDTH,
    ) -> None:
        super().__init__(parent)
        self._icon_manager = icon_manager or IconManager()
        self._indicator_width = max(18, int(indicator_width))
        self._popup_open = False

        self._indicator = QLabel(self)
        self._indicator.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._indicator.setAccessibleName("Combo box direction indicator")
        self._refresh_indicator()

    def showPopup(self) -> None:
        self._popup_open = True
        self._refresh_indicator()
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self._popup_open = False
        self._refresh_indicator()

    def resizeEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        super().resizeEvent(event)
        self._indicator.setGeometry(
            max(0, self.width() - self._indicator_width),
            0,
            self._indicator_width,
            self.height(),
        )
        self._indicator.raise_()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if hasattr(self, "_indicator") and event.type() in {
            QEvent.Type.EnabledChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        }:
            self._refresh_indicator()

    def _refresh_indicator(self) -> None:
        semantic = "common.expand_up" if self._popup_open else "common.expand_down"
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        icon = self._icon_manager.icon(semantic, size=_INDICATOR_ICON_SIZE)
        self._indicator.setPixmap(
            icon.pixmap(
                QSize(_INDICATOR_ICON_SIZE, _INDICATOR_ICON_SIZE),
                mode,
                QIcon.State.Off,
            )
        )


class IndicatorSpinBox(QSpinBox):
    """QSpinBox with semantic up/down chevron overlays."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        icon_manager: IconManager | None = None,
        indicator_width: int = _SPIN_INDICATOR_WIDTH,
    ) -> None:
        super().__init__(parent)
        self._icon_manager = icon_manager or IconManager()
        self._indicator_width = max(18, int(indicator_width))

        self._up_indicator = self._create_indicator("Increase value")
        self._down_indicator = self._create_indicator("Decrease value")
        self._refresh_indicators()

    def resizeEvent(self, event) -> None:  # noqa: ANN001 - Qt override
        super().resizeEvent(event)
        x = max(0, self.width() - self._indicator_width)
        top_height = max(1, self.height() // 2)
        bottom_height = max(1, self.height() - top_height)
        self._up_indicator.setGeometry(x, 0, self._indicator_width, top_height)
        self._down_indicator.setGeometry(
            x,
            top_height,
            self._indicator_width,
            bottom_height,
        )
        self._up_indicator.raise_()
        self._down_indicator.raise_()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if hasattr(self, "_up_indicator") and event.type() in {
            QEvent.Type.EnabledChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        }:
            self._refresh_indicators()

    def _create_indicator(self, accessible_name: str) -> QLabel:
        label = QLabel(self)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAccessibleName(accessible_name)
        return label

    def _refresh_indicators(self) -> None:
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        for label, semantic in (
            (self._up_indicator, "common.expand_up"),
            (self._down_indicator, "common.expand_down"),
        ):
            icon = self._icon_manager.icon(semantic, size=_INDICATOR_ICON_SIZE)
            label.setPixmap(
                icon.pixmap(
                    QSize(_INDICATOR_ICON_SIZE, _INDICATOR_ICON_SIZE),
                    mode,
                    QIcon.State.Off,
                )
            )


__all__ = ["IndicatorComboBox", "IndicatorSpinBox"]
