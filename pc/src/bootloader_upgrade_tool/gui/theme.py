"""QSS loading and application-level theme helpers for the Phase 11 GUI."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Mapping

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from .theme_tokens import (
    APPLICATION_FONT_FAMILY,
    APPLICATION_FONT_POINT_SIZE,
    THEME_TOKENS,
)

_TOKEN_PATTERN = re.compile(r"@([A-Z][A-Z0-9_]*)@")


class ThemeError(RuntimeError):
    """Raised when the QSS theme cannot be loaded or rendered safely."""


def theme_qss_text(path: Path | None = None) -> str:
    """Read the project QSS from an explicit path or package resources."""

    try:
        if path is not None:
            return path.read_text(encoding="utf-8")
        resource = resources.files(__package__).joinpath("resources/styles/theme.qss")
        return resource.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        location = str(path) if path is not None else "package resource theme.qss"
        raise ThemeError(f"unable to read GUI theme from {location}: {exc}") from exc


def render_theme(qss: str, tokens: Mapping[str, str] = THEME_TOKENS) -> str:
    """Replace every ``@TOKEN@`` and reject unknown or unresolved values."""

    if not isinstance(qss, str):
        raise TypeError("qss must be a string")

    referenced = set(_TOKEN_PATTERN.findall(qss))
    unknown = sorted(referenced.difference(tokens))
    if unknown:
        raise ThemeError(f"unknown QSS theme token(s): {', '.join(unknown)}")

    empty = sorted(name for name in referenced if not str(tokens[name]).strip())
    if empty:
        raise ThemeError(f"empty QSS theme token(s): {', '.join(empty)}")

    rendered = _TOKEN_PATTERN.sub(lambda match: str(tokens[match.group(1)]), qss)
    unresolved = sorted(set(_TOKEN_PATTERN.findall(rendered)))
    if unresolved:
        raise ThemeError(
            f"unresolved QSS theme token(s): {', '.join(unresolved)}"
        )
    return rendered


def apply_application_font(app: QApplication) -> None:
    app.setFont(QFont(APPLICATION_FONT_FAMILY, APPLICATION_FONT_POINT_SIZE))


def apply_palette_fallback(app: QApplication) -> None:
    """Set a minimal palette for native dialogs and unstyled fallback widgets."""

    palette = app.palette()
    active = QPalette.ColorGroup.Active
    inactive = QPalette.ColorGroup.Inactive
    disabled = QPalette.ColorGroup.Disabled

    for group in (active, inactive):
        palette.setColor(
            group,
            QPalette.ColorRole.Window,
            QColor(THEME_TOKENS["WINDOW_BG"]),
        )
        palette.setColor(
            group,
            QPalette.ColorRole.WindowText,
            QColor(THEME_TOKENS["TEXT_PRIMARY"]),
        )
        palette.setColor(
            group,
            QPalette.ColorRole.Base,
            QColor(THEME_TOKENS["SURFACE"]),
        )
        palette.setColor(
            group,
            QPalette.ColorRole.AlternateBase,
            QColor(THEME_TOKENS["TABLE_ALTERNATE_BG"]),
        )
        palette.setColor(
            group,
            QPalette.ColorRole.Text,
            QColor(THEME_TOKENS["TEXT_PRIMARY"]),
        )
        palette.setColor(
            group,
            QPalette.ColorRole.Button,
            QColor(THEME_TOKENS["SURFACE"]),
        )
        palette.setColor(
            group,
            QPalette.ColorRole.ButtonText,
            QColor(THEME_TOKENS["TEXT_PRIMARY"]),
        )
        palette.setColor(
            group,
            QPalette.ColorRole.Highlight,
            QColor(THEME_TOKENS["PRIMARY"]),
        )
        palette.setColor(
            group,
            QPalette.ColorRole.HighlightedText,
            QColor(THEME_TOKENS["TEXT_ON_ACCENT"]),
        )

    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(
            disabled,
            role,
            QColor(THEME_TOKENS["TEXT_DISABLED"]),
        )
    app.setPalette(palette)


def load_theme(app: QApplication, path: Path | None = None) -> str:
    """Render and apply the frozen QSS, returning the rendered stylesheet."""

    if not isinstance(app, QApplication):
        raise TypeError("app must be a QApplication")
    rendered = render_theme(theme_qss_text(path))
    app.setStyleSheet(rendered)
    return rendered
