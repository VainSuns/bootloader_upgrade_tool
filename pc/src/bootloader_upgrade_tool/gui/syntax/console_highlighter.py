"""Incremental syntax highlighting for the global Console text view."""

from __future__ import annotations

import re
from typing import Final

from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

from ..theme_tokens import THEME_TOKENS

CONSOLE_LINE_PATTERN: Final = re.compile(
    r"^\[(\d{2}:\d{2}:\d{2}\.\d{3})\]\s+"
    r"\[(DEBUG|INFO|WARN|WARNING|ERROR|SUCCESS|PROTOCOL)\]\s+"
    r"([^:]+):"
)

_LEVEL_TOKEN_NAMES: Final = {
    "DEBUG": "CONSOLE_DEBUG",
    "INFO": "CONSOLE_INFO",
    "WARN": "CONSOLE_WARNING",
    "WARNING": "CONSOLE_WARNING",
    "ERROR": "CONSOLE_ERROR",
    "SUCCESS": "CONSOLE_SUCCESS",
    "PROTOCOL": "CONSOLE_PROTOCOL",
}


class ConsoleSyntaxHighlighter(QSyntaxHighlighter):
    """Highlight timestamp, level and source tokens without changing plain text."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._timestamp = self._format("CONSOLE_TIMESTAMP")
        self._source = self._format(
            "CONSOLE_SOURCE",
            weight=QFont.Weight.DemiBold,
        )
        self._levels = {
            level: self._format(
                token_name,
                weight=(
                    QFont.Weight.DemiBold
                    if level in {"WARN", "WARNING", "ERROR", "SUCCESS"}
                    else QFont.Weight.Normal
                ),
            )
            for level, token_name in _LEVEL_TOKEN_NAMES.items()
        }

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        match = CONSOLE_LINE_PATTERN.match(text)
        if match is None:
            return

        level = match.group(2)
        background_token = None
        if level in {"WARN", "WARNING"}:
            background_token = "CONSOLE_WARNING_BG"
        elif level == "ERROR":
            background_token = "CONSOLE_ERROR_BG"

        base = self._format("CONSOLE_TEXT", background=background_token)
        self.setFormat(0, len(text), base)

        timestamp_start, timestamp_end = match.span(1)
        level_start, level_end = match.span(2)
        source_start, source_end = match.span(3)

        self.setFormat(
            timestamp_start,
            timestamp_end - timestamp_start,
            self._with_background(self._timestamp, background_token),
        )
        self.setFormat(
            level_start,
            level_end - level_start,
            self._with_background(self._levels[level], background_token),
        )
        self.setFormat(
            source_start,
            source_end - source_start,
            self._with_background(self._source, background_token),
        )

    @staticmethod
    def _format(
        foreground_token: str,
        *,
        weight: QFont.Weight = QFont.Weight.Normal,
        background: str | None = None,
    ) -> QTextCharFormat:
        result = QTextCharFormat()
        result.setForeground(QColor(THEME_TOKENS[foreground_token]))
        result.setFontWeight(weight)
        if background is not None:
            result.setBackground(QColor(THEME_TOKENS[background]))
        return result

    @staticmethod
    def _with_background(
        source: QTextCharFormat,
        background_token: str | None,
    ) -> QTextCharFormat:
        result = QTextCharFormat(source)
        if background_token is not None:
            result.setBackground(QColor(THEME_TOKENS[background_token]))
        return result
