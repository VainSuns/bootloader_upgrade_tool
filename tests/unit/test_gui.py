import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui import MainWindow


def test_main_window_connects_only_through_io_device_abstraction() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._connect_device()

    assert "Connected" in window.status_label.text()
    assert window.workflow is not None
    assert window.operation_buttons["Erase"].isEnabled()
    assert not window.operation_buttons["Program"].isEnabled()

    window.close()
    app.processEvents()
