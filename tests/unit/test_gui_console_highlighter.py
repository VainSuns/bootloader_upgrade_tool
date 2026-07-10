from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextDocument
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.syntax.console_highlighter import (
    CONSOLE_LINE_PATTERN,
    ConsoleSyntaxHighlighter,
)
from bootloader_upgrade_tool.gui.theme_tokens import THEME_TOKENS


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def format_ranges(document: QTextDocument):
    block = document.firstBlock()
    return list(block.layout().formats())


def test_console_line_pattern_accepts_frozen_levels() -> None:
    for level in (
        "DEBUG",
        "INFO",
        "WARN",
        "WARNING",
        "ERROR",
        "SUCCESS",
        "PROTOCOL",
    ):
        line = f"[12:34:56.789] [{level}] Session: message"
        assert CONSOLE_LINE_PATTERN.match(line)


def test_console_highlighter_formats_structured_line() -> None:
    app = qt_app()
    document = QTextDocument()
    highlighter = ConsoleSyntaxHighlighter(document)
    document.setPlainText("[12:34:56.789] [INFO] Session: connected")
    highlighter.rehighlight()
    app.processEvents()

    ranges = format_ranges(document)
    colors = {item.format.foreground().color().name().upper() for item in ranges}

    assert THEME_TOKENS["CONSOLE_TIMESTAMP"] in colors
    assert THEME_TOKENS["CONSOLE_INFO"] in colors
    assert THEME_TOKENS["CONSOLE_SOURCE"] in colors


def test_warning_and_error_lines_receive_weak_backgrounds() -> None:
    app = qt_app()
    for level, token_name in (
        ("WARNING", "CONSOLE_WARNING_BG"),
        ("ERROR", "CONSOLE_ERROR_BG"),
    ):
        document = QTextDocument()
        highlighter = ConsoleSyntaxHighlighter(document)
        document.setPlainText(f"[12:34:56.789] [{level}] Operation: detail")
        highlighter.rehighlight()
        app.processEvents()

        backgrounds = {
            item.format.background().color().name().upper()
            for item in format_ranges(document)
            if item.format.background().style() != Qt.BrushStyle.NoBrush
        }
        assert QColor(THEME_TOKENS[token_name]).name().upper() in backgrounds


def test_unstructured_and_continuation_lines_remain_unformatted() -> None:
    app = qt_app()
    for text in ("plain text", "    continuation detail"):
        document = QTextDocument()
        highlighter = ConsoleSyntaxHighlighter(document)
        document.setPlainText(text)
        highlighter.rehighlight()
        app.processEvents()
        assert format_ranges(document) == []
