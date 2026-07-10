from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from bootloader_upgrade_tool.gui.theme import (
    ThemeError,
    load_theme,
    render_theme,
    theme_qss_text,
)
from bootloader_upgrade_tool.gui.theme_tokens import THEME_TOKENS
from bootloader_upgrade_tool.gui.ui_state import set_ui_properties


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_theme_qss_resolves_all_tokens() -> None:
    rendered = render_theme(theme_qss_text())

    assert not re.search(r"@[A-Z][A-Z0-9_]*@", rendered)
    assert THEME_TOKENS["WINDOW_BG"] in rendered
    assert THEME_TOKENS["CONSOLE_BG"] in rendered


def test_unknown_theme_token_is_rejected() -> None:
    with pytest.raises(ThemeError, match="unknown QSS theme token"):
        render_theme("QWidget { color: @DOES_NOT_EXIST@; }")


def test_empty_theme_token_is_rejected() -> None:
    with pytest.raises(ThemeError, match="empty QSS theme token"):
        render_theme("QWidget { color: @TEXT@; }", {"TEXT": ""})


def test_load_theme_applies_rendered_qss() -> None:
    app = qt_app()
    rendered = load_theme(app)

    assert app.styleSheet() == rendered
    assert "@WINDOW_BG@" not in app.styleSheet()


def test_dynamic_properties_validate_and_repolish() -> None:
    app = qt_app()
    label = QLabel("state")

    assert set_ui_properties(label, uiRole="statusBadge", state="busy")
    assert label.property("uiRole") == "statusBadge"
    assert label.property("state") == "busy"
    assert not set_ui_properties(label, uiRole="statusBadge", state="busy")

    with pytest.raises(ValueError, match="invalid state value"):
        set_ui_properties(label, state="valid")

    label.deleteLater()
    app.processEvents()
