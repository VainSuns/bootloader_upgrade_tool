"""Static Settings Ribbon page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QWidget

from ...icon_manager import IconManager
from ...navigation import PageId
from .ribbon_shell import (
    RibbonButtonSpec,
    RibbonGroup,
    create_ribbon_button,
    create_ribbon_page,
)


class SettingsRibbon(QWidget):
    pageRequested = Signal(object)
    saveGlobalRequested = Signal()
    reloadGlobalRequested = Signal()

    def __init__(
        self,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsRibbonPage")
        self._icon_manager = icon_manager or IconManager()

        page = create_ribbon_page("settingsRibbonContent", self)
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(page, 0, 0)
        row = page.layout()

        group = RibbonGroup(
            "Global", object_name="settingsGlobalRibbonGroup", parent=page
        )
        self.open_settings_button = create_ribbon_button(
            RibbonButtonSpec(
                "Open\nSettings",
                "openSettingsButton",
                "ribbon.settings.open",
            ),
            icon_manager=self._icon_manager,
            parent=group,
        )
        self.save_global_button = create_ribbon_button(
            RibbonButtonSpec(
                "Save\nGlobal",
                "saveGlobalSettingsButton",
                "ribbon.settings.save_global",
                enabled=False,
                tooltip="Persistence is deferred until runtime integration.",
            ),
            icon_manager=self._icon_manager,
            parent=group,
        )
        self.reload_global_button = create_ribbon_button(
            RibbonButtonSpec(
                "Reload\nGlobal",
                "reloadGlobalSettingsButton",
                "ribbon.settings.reload_global",
                enabled=False,
                tooltip="Persistence is deferred until runtime integration.",
            ),
            icon_manager=self._icon_manager,
            parent=group,
        )
        for button in (
            self.open_settings_button,
            self.save_global_button,
            self.reload_global_button,
        ):
            group.add_widget(button)
        row.addWidget(group)
        row.addStretch(1)

        self.open_settings_button.clicked.connect(
            lambda _checked=False: self.pageRequested.emit(PageId.SETTINGS)
        )
        self.save_global_button.clicked.connect(lambda _checked=False: self.saveGlobalRequested.emit())
        self.reload_global_button.clicked.connect(lambda _checked=False: self.reloadGlobalRequested.emit())
