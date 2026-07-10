"""Reusable static-layout widgets for the Phase 11 GUI V1.0 migration."""

from .card import CardFrame, CardHeader, NoticeBanner, SectionCard, SeparatorLine
from .console_widget import ConsoleRecord, ConsoleWidget
from .form_rows import LabeledFieldRow, PathFieldRow, ReadOnlyValueRow
from .navigation_panel import (
    NavigationItemSpec,
    NavigationPanel,
    approved_navigation_items,
)
from .page_header import PageHeader, TargetPageHeader
from .ribbon import (
    DEFAULT_RIBBON_TAB,
    RIBBON_TAB_ORDER,
    OperateRibbon,
    RibbonGroup,
    RibbonShell,
    RibbonTab,
    SessionRibbon,
    SettingsRibbon,
    ViewRibbon,
    create_default_ribbon,
)
from .status_widgets import ScopeBadge, StateIconLabel, StatusBadge, StatusDot

__all__ = [
    "CardFrame",
    "CardHeader",
    "ConsoleRecord",
    "ConsoleWidget",
    "DEFAULT_RIBBON_TAB",
    "LabeledFieldRow",
    "NavigationItemSpec",
    "NavigationPanel",
    "NoticeBanner",
    "OperateRibbon",
    "PageHeader",
    "PathFieldRow",
    "RIBBON_TAB_ORDER",
    "ReadOnlyValueRow",
    "RibbonGroup",
    "RibbonShell",
    "RibbonTab",
    "ScopeBadge",
    "SectionCard",
    "SeparatorLine",
    "SessionRibbon",
    "SettingsRibbon",
    "StateIconLabel",
    "StatusBadge",
    "StatusDot",
    "TargetPageHeader",
    "ViewRibbon",
    "approved_navigation_items",
    "create_default_ribbon",
]
