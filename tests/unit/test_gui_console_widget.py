import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPlainTextEdit, QToolButton

from bootloader_upgrade_tool.gui.app import configure_application
from bootloader_upgrade_tool.gui.layout_metrics import (
    CONSOLE_HEADER_HEIGHT,
    CONSOLE_TOOL_BUTTON_SIZE,
)
from bootloader_upgrade_tool.gui.widgets import ConsoleRecord, ConsoleWidget


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_console_widget_frozen_structure_and_plain_text_behavior() -> None:
    app = qt_app()
    configure_application(app)
    console = ConsoleWidget(maximum_block_count=3)
    console.resize(900, 160)
    console.show()
    app.processEvents()

    assert console.objectName() == "bottomDock"
    assert console.header.objectName() == "bottomDockHeader"
    assert console.body.objectName() == "bottomConsoleBody"
    assert console.output.objectName() == "consoleOutput"
    assert isinstance(console.output, QPlainTextEdit)
    assert console.output.isReadOnly()
    assert console.output.maximumBlockCount() == 3

    for name in (
        "consoleCopyButton",
        "consoleAutoScrollButton",
        "consoleClearButton",
        "consoleExpandButton",
    ):
        button = console.findChild(QToolButton, name)
        assert button is not None
        assert (button.width(), button.height()) == CONSOLE_TOOL_BUTTON_SIZE
        assert button.geometry().top() >= 0
        assert button.geometry().bottom() < CONSOLE_HEADER_HEIGHT

    stamp = datetime(2026, 7, 10, 8, 30, 15, 123000, tzinfo=timezone.utc)
    console.append_message("info", "GUI", "Ready", timestamp=stamp)
    console.append_message("warning", "Preview", "Static Example", timestamp=stamp)

    assert console.output.toPlainText().splitlines() == [
        "[08:30:15.123] [INFO] GUI: Ready",
        "[08:30:15.123] [WARNING] Preview: Static Example",
    ]

    console.copy_all()
    assert QApplication.clipboard().text() == console.output.toPlainText()
    console.clear_button.click()
    assert console.output.toPlainText() == ""

    console.close()
    app.processEvents()


def test_console_record_validation_and_collapse_signal() -> None:
    app = qt_app()
    console = ConsoleWidget()
    changes: list[bool] = []
    console.expandedChanged.connect(changes.append)

    record = ConsoleRecord(
        datetime(2026, 7, 10, 8, 0, 0, tzinfo=timezone.utc),
        "protocol",
        "FrameReader",
        "RX 0001",
    )
    assert record.render() == "[08:00:00.000] [PROTOCOL] FrameReader: RX 0001"

    console.set_expanded(False)
    assert console.expanded is False
    assert console.body.isHidden()
    assert changes == [False]

    console.set_expanded(True)
    assert console.expanded is True
    assert changes == [False, True]

    try:
        ConsoleRecord(
            datetime.now(timezone.utc),
            "fatal",
            "GUI",
            "bad level",
        ).render()
    except ValueError as exc:
        assert "unknown Console level" in str(exc)
    else:
        raise AssertionError("invalid Console level must be rejected")

    console.close()
    app.processEvents()
