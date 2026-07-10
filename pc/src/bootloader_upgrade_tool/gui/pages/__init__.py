"""Static page modules for the approved Phase 11 GUI migration."""

from .placeholder_page import PlaceholderPage, PlaceholderPageSpec
from .program_page import PROGRAM_STATUS_DEFINITIONS, ProgramTargetPage
from .settings_page import CURRENT_CATEGORIES, GLOBAL_CATEGORIES, SettingsPage

__all__ = [
    "CURRENT_CATEGORIES",
    "GLOBAL_CATEGORIES",
    "PROGRAM_STATUS_DEFINITIONS",
    "PlaceholderPage",
    "PlaceholderPageSpec",
    "ProgramTargetPage",
    "SettingsPage",
]
