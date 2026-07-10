from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.icon_manager import IconError, IconManager


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_project_icon_manifest_and_assets_are_complete() -> None:
    manager = IconManager()

    assert manager.version == "3.44.0"
    assert len(manager.semantic_names) == 130
    assert manager.has_icon("advanced.metadata.image_valid")
    assert manager.has_icon("console.copy")
    manager.validate_resources()


def test_semantic_icon_renders_and_is_cached() -> None:
    app = qt_app()
    manager = IconManager()

    first = manager.icon("common.success", size=16)
    second = manager.icon("common.success", size=16)

    assert not first.isNull()
    assert not second.isNull()
    assert not first.pixmap(16, 16).isNull()
    app.processEvents()


def test_unknown_semantic_icon_is_rejected() -> None:
    manager = IconManager()

    with pytest.raises(IconError, match="unknown semantic icon"):
        manager.icon("missing.semantic.icon")
