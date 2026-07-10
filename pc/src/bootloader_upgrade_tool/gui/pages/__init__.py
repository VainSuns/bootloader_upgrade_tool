"""Static page modules for the approved Phase 11 GUI migration."""

from .advanced_page import ADVANCED_TAB_LABELS, ERASE_SCOPE_LABELS, AdvancedPage
from .logs_page import LOG_LEVEL_CHOICES, LOG_TABLE_HEADERS, LogsPage
from .memory_page import MEMORY_DISPLAY_FORMATS, MEMORY_TABLE_HEADERS, MemoryTargetPage
from .placeholder_page import PlaceholderPage, PlaceholderPageSpec
from .program_page import PROGRAM_STATUS_DEFINITIONS, ProgramTargetPage
from .settings_page import CURRENT_CATEGORIES, GLOBAL_CATEGORIES, SettingsPage

__all__ = [
    "ADVANCED_TAB_LABELS",
    "ERASE_SCOPE_LABELS",
    "AdvancedPage",
    "CURRENT_CATEGORIES",
    "LOG_LEVEL_CHOICES",
    "LOG_TABLE_HEADERS",
    "LogsPage",
    "MEMORY_DISPLAY_FORMATS",
    "MEMORY_TABLE_HEADERS",
    "MemoryTargetPage",
    "GLOBAL_CATEGORIES",
    "PROGRAM_STATUS_DEFINITIONS",
    "PlaceholderPage",
    "PlaceholderPageSpec",
    "ProgramTargetPage",
    "SettingsPage",
]
