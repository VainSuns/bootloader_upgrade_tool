"""Frozen visual tokens for the Phase 11 GUI V1.0 theme.

This module contains visual values only. Layout dimensions belong in
``layout_metrics.py`` and operation / hardware behavior must not be added here.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping

THEME_ID: Final = "phase11-light-engineering-v1"
APPLICATION_FONT_FAMILY: Final = "Segoe UI"
APPLICATION_FONT_POINT_SIZE: Final = 9
CONSOLE_FONT_FAMILIES: Final = ("Cascadia Mono", "Consolas", "Courier New")
CONSOLE_FONT_POINT_SIZE: Final = 9

_THEME_TOKEN_VALUES = {
    "WINDOW_BG": "#F3F5F7",
    "SURFACE": "#FFFFFF",
    "SURFACE_SUBTLE": "#F7F9FB",
    "SURFACE_SUNKEN": "#EEF1F4",
    "SURFACE_HOVER": "#EEF4FC",
    "SURFACE_SELECTED": "#E8F2FF",
    "SURFACE_PRESSED": "#DCEBFF",
    "SURFACE_DISABLED": "#F1F3F5",
    "CARD_HEADER_BG": "#FBFCFD",
    "TABLE_ALTERNATE_BG": "#FAFBFC",
    "BORDER": "#D6DCE4",
    "BORDER_STRONG": "#B8C2CF",
    "BORDER_HOVER": "#A8B4C2",
    "SEPARATOR": "#E5E9EE",
    "FOCUS_BORDER": "#69A7F8",
    "TEXT_PRIMARY": "#1F2937",
    "TEXT_SECONDARY": "#526173",
    "TEXT_MUTED": "#7B8794",
    "TEXT_DISABLED": "#A6AFBA",
    "TEXT_ON_ACCENT": "#FFFFFF",
    "TEXT_LINK": "#0958D9",
    "TEXT_DANGER": "#B71C1C",
    "PRIMARY": "#1677FF",
    "PRIMARY_HOVER": "#4096FF",
    "PRIMARY_PRESSED": "#0958D9",
    "PRIMARY_SOFT": "#E8F2FF",
    "PRIMARY_BORDER": "#91CAFF",
    "SUCCESS": "#2E7D32",
    "SUCCESS_HOVER": "#256628",
    "SUCCESS_SOFT": "#EAF6EC",
    "SUCCESS_BORDER": "#A5D6A7",
    "WARNING": "#ED6C02",
    "WARNING_STRONG": "#A84D00",
    "WARNING_SOFT": "#FFF4E5",
    "WARNING_BORDER": "#F2C078",
    "ERROR": "#D32F2F",
    "ERROR_HOVER": "#B71C1C",
    "ERROR_PRESSED": "#8E1515",
    "ERROR_SOFT": "#FDECEC",
    "ERROR_BORDER": "#E6A0A0",
    "NEUTRAL": "#667085",
    "NEUTRAL_SOFT": "#EEF1F4",
    "UNAVAILABLE": "#8C96A3",
    "CONSOLE_BG": "#171B22",
    "CONSOLE_TEXT": "#D6DAE1",
    "CONSOLE_BORDER": "#2B313C",
    "CONSOLE_SELECTION_BG": "#345F91",
    "CONSOLE_SELECTION_TEXT": "#FFFFFF",
    "CONSOLE_TIMESTAMP": "#778192",
    "CONSOLE_SOURCE": "#AEB7C6",
    "CONSOLE_DEBUG": "#8B95A5",
    "CONSOLE_INFO": "#69A7F8",
    "CONSOLE_WARNING": "#F2B84B",
    "CONSOLE_ERROR": "#FF6B6B",
    "CONSOLE_SUCCESS": "#67C587",
    "CONSOLE_PROTOCOL": "#B79AF4",
    "CONSOLE_WARNING_BG": "#2B261B",
    "CONSOLE_ERROR_BG": "#302025",
    "CONSOLE_SCROLL_THUMB": "#485161",
    "CONSOLE_SCROLL_HOVER": "#5C6678",
    "TOOLTIP_BG": "#273142",
    "TOOLTIP_TEXT": "#FFFFFF",
}

THEME_TOKENS: Final[Mapping[str, str]] = MappingProxyType(_THEME_TOKEN_VALUES)

ICON_TONES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "neutral": THEME_TOKENS["TEXT_SECONDARY"],
        "primary": THEME_TOKENS["PRIMARY"],
        "disabled": THEME_TOKENS["TEXT_DISABLED"],
        "success": THEME_TOKENS["SUCCESS"],
        "warning": THEME_TOKENS["WARNING"],
        "error": THEME_TOKENS["ERROR"],
        "inverse": THEME_TOKENS["TEXT_ON_ACCENT"],
    }
)


def token(name: str) -> str:
    """Return one frozen theme token or raise a descriptive error."""

    try:
        return THEME_TOKENS[name]
    except KeyError as exc:
        raise KeyError(f"unknown GUI theme token: {name!r}") from exc
