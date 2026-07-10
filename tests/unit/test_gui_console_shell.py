import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPlainTextEdit

from bootloader_upgrade_tool.gui import BootloaderMainWindow
from bootloader_upgrade_tool.gui.layout_metrics import (
    CONSOLE_COLLAPSED_HEIGHT,
    CONSOLE_MINIMUM_EXPANDED_HEIGHT,
    WINDOW_MINIMUM_SIZE,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_console_contract_and_expand_height_restore() -> None:
    app = qt_app()
    window = BootloaderMainWindow()
    window.show()
    app.processEvents()

    output = window.findChild(QPlainTextEdit, "consoleOutput")
    assert output is window.bottom_dock.output
    assert output.isReadOnly()
    assert output.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap
    assert window.bottom_dock.expanded

    window.workspace_splitter.setSizes([600, 180])
    app.processEvents()
    remembered = window.workspace_splitter.sizes()[1]
    assert remembered >= CONSOLE_MINIMUM_EXPANDED_HEIGHT

    window.set_console_expanded(False)
    app.processEvents()
    assert not window.bottom_dock.expanded
    assert window.workspace_splitter.sizes()[1] == CONSOLE_COLLAPSED_HEIGHT
    assert not window.view_ribbon.console_toggle_button.isChecked()

    window.set_console_expanded(True)
    app.processEvents()
    assert window.bottom_dock.expanded
    assert window.workspace_splitter.sizes()[1] >= CONSOLE_MINIMUM_EXPANDED_HEIGHT
    assert abs(window.workspace_splitter.sizes()[1] - remembered) <= 2
    assert window.view_ribbon.console_toggle_button.isChecked()

    window.close()
    app.processEvents()


def test_short_window_starts_with_console_collapsed() -> None:
    app = qt_app()
    window = BootloaderMainWindow()
    window.resize(WINDOW_MINIMUM_SIZE[0], WINDOW_MINIMUM_SIZE[1])
    window.show()
    app.processEvents()
    app.processEvents()

    assert not window.bottom_dock.expanded
    assert window.workspace_splitter.sizes()[1] == CONSOLE_COLLAPSED_HEIGHT

    window.close()
    app.processEvents()


