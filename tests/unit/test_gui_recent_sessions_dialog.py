from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from bootloader_upgrade_tool.gui.persistence_models import RecentSessionEntry
from bootloader_upgrade_tool.gui.recent_sessions_dialog import RecentSessionsDialog


def qt_app():
    return QApplication.instance() or QApplication([])


def test_recent_dialog_keeps_missing_visible_and_disables_only_open(tmp_path):
    app = qt_app()
    host = QWidget()
    host.resize(1100, 720)
    host.show()
    available = tmp_path / "available.json"
    available.write_text("{}", encoding="utf-8")
    missing = tmp_path / "missing.json"
    dialog = RecentSessionsDialog(
        (
            RecentSessionEntry(str(available), datetime.now(timezone.utc)),
            RecentSessionEntry(str(missing), datetime.now(timezone.utc)),
        ),
        host,
    )
    dialog.show()
    app.processEvents()

    assert dialog.windowModality() is Qt.WindowModality.WindowModal
    for surface in (dialog.card, dialog.header, dialog.content_frame, dialog.footer):
        assert surface.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert dialog.list.count() == 2
    first_row = dialog.list.itemWidget(dialog.list.item(0))
    second_row = dialog.list.itemWidget(dialog.list.item(1))
    assert first_row.status_label.text() == "Available"
    assert second_row.status_label.text() == "Missing"

    dialog.list.setCurrentRow(1)
    dialog.list.item(1).setSelected(True)
    app.processEvents()
    assert not dialog.open_button.isEnabled()
    assert dialog.remove_button.isEnabled()
    removed = []
    dialog.removeRequested.connect(removed.append)
    dialog.remove_button.click()
    assert removed == [str(missing.resolve())]

    dialog.list.setCurrentRow(0)
    dialog.list.item(0).setSelected(True)
    app.processEvents()
    opened = []
    dialog.openRequested.connect(opened.append)
    dialog.open_button.click()
    assert opened == [str(available.resolve())]


def test_recent_dialog_has_clear_empty_state():
    qt_app()
    host = QWidget()
    dialog = RecentSessionsDialog((), host)
    assert dialog.content_stack.currentWidget() is dialog.empty_widget
    assert dialog.empty_title.text() == "No recent sessions"
    assert not dialog.open_button.isEnabled()
    assert not dialog.remove_button.isEnabled()
