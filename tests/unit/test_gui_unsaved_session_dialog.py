from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget

from bootloader_upgrade_tool.gui.theme_tokens import THEME_TOKENS
from bootloader_upgrade_tool.gui.widgets.unsaved_session_dialog import (
    UnsavedSessionChoice,
    UnsavedSessionDialog,
)


def qt_app():
    return QApplication.instance() or QApplication([])


def test_unsaved_session_dialog_uses_embedded_modal_and_exposes_session_details(tmp_path):
    app = qt_app()
    host = QWidget()
    host.resize(1000, 700)
    host.show()
    session_path = tmp_path / "project.session.json"
    dialog = UnsavedSessionDialog(
        "Project Session",
        session_path=session_path,
        parent=host,
    )
    dialog.show()
    app.processEvents()

    assert dialog.windowModality() is Qt.WindowModality.WindowModal
    for surface in (dialog.card, dialog.header, dialog.content_frame, dialog.footer):
        assert surface.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert dialog.session_value_label.text() == "Project Session"
    assert dialog.location_value_label.text() == str(Path(session_path))
    assert dialog.decision is UnsavedSessionChoice.CANCEL


def test_unsaved_session_buttons_map_to_save_discard_and_cancel():
    qt_app()
    host = QWidget()

    save_dialog = UnsavedSessionDialog("Untitled", parent=host)
    save_dialog.save_button.click()
    assert save_dialog.decision is UnsavedSessionChoice.SAVE

    discard_dialog = UnsavedSessionDialog("Untitled", parent=host)
    discard_dialog.discard_button.click()
    assert discard_dialog.decision is UnsavedSessionChoice.DISCARD

    cancel_dialog = UnsavedSessionDialog("Untitled", parent=host)
    cancel_dialog.reject()
    assert cancel_dialog.decision is UnsavedSessionChoice.CANCEL
    assert cancel_dialog.location_value_label.text() == "Not saved yet"


def test_qt_session_dialog_provider_uses_embedded_unsaved_dialog(monkeypatch, tmp_path):
    import bootloader_upgrade_tool.gui.session_gui_binding as binding_module
    from bootloader_upgrade_tool.gui.session_gui_binding import (
        DirtySessionDecision,
        QtSessionDialogProvider,
    )

    captured = {}

    class FakeDialog:
        decision = UnsavedSessionChoice.DISCARD

        def __init__(self, display_name, *, session_path=None, parent=None):
            captured.update(
                display_name=display_name,
                session_path=session_path,
                parent=parent,
            )

        def exec(self):
            captured["executed"] = True
            return 0

    monkeypatch.setattr(binding_module, "UnsavedSessionDialog", FakeDialog)
    parent = QWidget()
    path = tmp_path / "active.session.json"

    parent.session_binding = SimpleNamespace(
        service=SimpleNamespace(state=SimpleNamespace(path=path))
    )
    decision = QtSessionDialogProvider().confirm_dirty_session(
        parent,
        "Active Session",
    )

    assert decision is DirtySessionDecision.DISCARD
    assert captured == {
        "display_name": "Active Session",
        "session_path": path,
        "parent": parent,
        "executed": True,
    }

def test_embedded_modal_event_filter_is_safe_during_qt_teardown():
    """Late Qt events must not depend on attributes already cleared by teardown."""

    qt_app()
    host = QWidget()
    dialog = UnsavedSessionDialog("Untitled", parent=host)

    # Reproduce the teardown state seen when a previous dialog/host is destroyed
    # while the next main window is being constructed.
    del dialog._watched_widgets
    event = QEvent(QEvent.Type.Resize)

    assert dialog.eventFilter(host, event) is False


def test_embedded_modal_detaches_geometry_watchers_when_finished():
    qt_app()
    host = QWidget()
    dialog = UnsavedSessionDialog("Untitled", parent=host)

    assert dialog._watched_widgets
    dialog.reject()

    assert dialog._watched_widgets == []


def test_embedded_modal_renders_an_opaque_scrim_and_solid_card_on_offscreen_qt():
    app = qt_app()
    host = QWidget()
    host.resize(1000, 700)
    host.setStyleSheet("background-color: #D02020;")
    host.show()
    app.processEvents()

    dialog = UnsavedSessionDialog("Untitled", parent=host)
    dialog.show()
    app.processEvents()

    assert not dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    image = QImage(
        dialog.size(),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(Qt.GlobalColor.transparent)
    dialog.render(image)

    outside = image.pixelColor(QPoint(4, 4))
    assert outside.alpha() == 255

    card_sample = dialog.card.mapTo(dialog, QPoint(18, 18))
    rendered = image.pixelColor(card_sample)
    expected = QColor(THEME_TOKENS["SURFACE"])
    assert abs(rendered.red() - expected.red()) <= 3
    assert abs(rendered.green() - expected.green()) <= 3
    assert abs(rendered.blue() - expected.blue()) <= 3
    assert rendered.alpha() == 255

