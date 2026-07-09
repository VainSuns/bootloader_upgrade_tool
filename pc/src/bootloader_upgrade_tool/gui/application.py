"""Compatibility entrypoint for the Phase 11 PySide6 GUI."""

from __future__ import annotations

from .app import main


def run() -> int:
    return main()