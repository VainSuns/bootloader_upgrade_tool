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
    "MODAL_SCRIM": "rgba(31, 41, 55, 128)",
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
    # Console remains tokenized, but now uses a light engineering palette.
    "CONSOLE_BG": "#FFFFFF",
    "CONSOLE_TEXT": "#1F2937",
    "CONSOLE_BORDER": "#D6DCE4",
    "CONSOLE_SELECTION_BG": "#E8F2FF",
    "CONSOLE_SELECTION_TEXT": "#1F2937",
    "CONSOLE_TIMESTAMP": "#7B8794",
    "CONSOLE_SOURCE": "#526173",
    "CONSOLE_DEBUG": "#7B8794",
    "CONSOLE_INFO": "#0958D9",
    "CONSOLE_WARNING": "#A84D00",
    "CONSOLE_ERROR": "#B71C1C",
    "CONSOLE_SUCCESS": "#2E7D32",
    "CONSOLE_PROTOCOL": "#6F42C1",
    "CONSOLE_WARNING_BG": "#FFF4E5",
    "CONSOLE_ERROR_BG": "#FDECEC",
    "CONSOLE_SCROLL_THUMB": "#B8C2CF",
    "CONSOLE_SCROLL_HOVER": "#A8B4C2",
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
