"""Reusable static-layout widgets for the Phase 11 GUI V1.0 migration."""

from .card import CardFrame, CardHeader, NoticeBanner, SectionCard, SeparatorLine
from .console_widget import ConsoleRecord, ConsoleWidget
from .form_rows import LabeledFieldRow, PathFieldRow, ReadOnlyValueRow
from .navigation_panel import NavigationItemSpec, NavigationPanel
from .page_header import PageHeader, TargetPageHeader
from .status_widgets import ScopeBadge, StateIconLabel, StatusBadge, StatusDot

__all__ = [
    "CardFrame",
    "CardHeader",
    "ConsoleRecord",
    "ConsoleWidget",
    "LabeledFieldRow",
    "NavigationItemSpec",
    "NavigationPanel",
    "NoticeBanner",
    "PageHeader",
    "PathFieldRow",
    "ReadOnlyValueRow",
    "ScopeBadge",
    "SectionCard",
    "SeparatorLine",
    "StateIconLabel",
    "StatusBadge",
    "StatusDot",
    "TargetPageHeader",
]
