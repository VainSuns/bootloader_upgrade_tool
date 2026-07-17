from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.persistence_models import RecentSessionEntry
from bootloader_upgrade_tool.gui.recent_sessions_dialog import RecentSessionsDialog


def test_recent_dialog_keeps_missing_visible_and_disables_only_open(tmp_path):
    QApplication.instance() or QApplication([])
    available = tmp_path / "available.json"
    available.write_text("{}", encoding="utf-8")
    missing = tmp_path / "missing.json"
    dialog = RecentSessionsDialog(
        (
            RecentSessionEntry(str(available), datetime.now(timezone.utc)),
            RecentSessionEntry(str(missing), datetime.now(timezone.utc)),
        )
    )
    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, 2).text() == "Available"
    assert dialog.table.item(1, 2).text() == "Missing"
    dialog.table.selectRow(1)
    assert not dialog.open_button.isEnabled() and dialog.remove_button.isEnabled()
    removed = []
    dialog.removeRequested.connect(removed.append)
    dialog.remove_button.click()
    assert removed == [str(missing.resolve())]
    dialog.table.selectRow(0)
    opened = []
    dialog.openRequested.connect(opened.append)
    dialog.open_button.click()
    assert opened == [str(available.resolve())]
