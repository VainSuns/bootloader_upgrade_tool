"""Approved Phase 11 Ribbon widgets."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ...icon_manager import IconManager
from .operate_ribbon import OperateRibbon
from .ribbon_shell import (
    DEFAULT_RIBBON_TAB,
    RIBBON_TAB_ORDER,
    RibbonButtonSpec,
    RibbonGroup,
    RibbonShell,
    RibbonTab,
    create_ribbon_button,
)
from .session_ribbon import SessionRibbon
from .settings_ribbon import SettingsRibbon
from .view_ribbon import ViewRibbon


def create_default_ribbon(
    *,
    icon_manager: IconManager | None = None,
    parent: QWidget | None = None,
) -> RibbonShell:
    """Create the frozen four-tab Ribbon without wiring runtime behavior."""

    manager = icon_manager or IconManager()
    shell = RibbonShell(parent)
    shell.add_tab(RibbonTab.SESSION, SessionRibbon(icon_manager=manager, parent=shell))
    shell.add_tab(RibbonTab.OPERATE, OperateRibbon(icon_manager=manager, parent=shell))
    shell.add_tab(RibbonTab.VIEW, ViewRibbon(icon_manager=manager, parent=shell))
    shell.add_tab(RibbonTab.SETTINGS, SettingsRibbon(icon_manager=manager, parent=shell))
    shell.set_current_tab(DEFAULT_RIBBON_TAB)
    return shell


__all__ = [
    "DEFAULT_RIBBON_TAB",
    "OperateRibbon",
    "RIBBON_TAB_ORDER",
    "RibbonButtonSpec",
    "RibbonGroup",
    "RibbonShell",
    "RibbonTab",
    "SessionRibbon",
    "SettingsRibbon",
    "ViewRibbon",
    "create_default_ribbon",
    "create_ribbon_button",
]
