"""Static page modules for the approved Phase 11 GUI migration."""

from .placeholder_page import PlaceholderPage, PlaceholderPageSpec
from .program_page import PROGRAM_STATUS_DEFINITIONS, ProgramTargetPage

__all__ = [
    "PROGRAM_STATUS_DEFINITIONS",
    "PlaceholderPage",
    "PlaceholderPageSpec",
    "ProgramTargetPage",
]
