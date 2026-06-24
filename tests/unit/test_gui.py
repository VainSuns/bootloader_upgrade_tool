import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui import MainWindow
from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.io import IoCancelledError, SimulatorIoDevice
from bootloader_upgrade_tool.gui import application


def test_main_window_connects_only_through_io_device_abstraction() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.baudrate.text() == "9600"
    window._connect_device()

    assert "Connected" in window.status_label.text()
    assert window.workflow is not None
    assert window.operation_buttons["Erase"].isEnabled()
    assert not window.operation_buttons["Program"].isEnabled()
    assert "Revision ID: 0x00000000" in window.device_summary.toPlainText()
    assert "UID Unique: 0x00000000" in window.device_summary.toPlainText()

    window.close()
    app.processEvents()


def test_firmware_summary_is_read_only_and_reports_image(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "app.out"
    source.write_bytes(b"firmware")
    image = FirmwareImage(
        source_out_file=str(source),
        generated_hex_file=str(tmp_path / "app.txt"),
        entry_point=0x080000,
        blocks=(FirmwareBlock(0x080000, (1, 2, 3)),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )
    window = MainWindow()

    window._set_firmware_summary(source, image)

    text = window.firmware_summary.toPlainText()
    assert window.firmware_summary.isReadOnly()
    assert "File size: 8 bytes" in text
    assert "Entry point: 0x00080000" in text
    assert "Block count: 1" in text
    assert "Total words: 3" in text
    assert "Validation: OK" in text
    window.close()
    app.processEvents()


def test_serial_connect_waits_until_user_cancels(monkeypatch) -> None:
    class WaitingDevice:
        def open(self) -> None:
            pass

        def wait_slave(self, timeout_ms, cancel_event=None) -> None:
            while cancel_event is not None and not cancel_event.wait(0.01):
                pass
            raise IoCancelledError("cancelled")

        def close(self) -> None:
            pass

        def clear_input(self) -> None:
            pass

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(application, "SerialIoDevice", lambda *args, **kwargs: WaitingDevice())
    window = MainWindow()
    window.device_kind.setCurrentText("Serial")

    window._connect_device()
    assert window.connect_button.text() == "Cancel"
    window._connect_device()

    deadline = time.monotonic() + 1
    while window.connect_worker is not None and window.connect_worker.isRunning():
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("connection worker did not cancel")
    app.processEvents()
    assert window.status_label.text() == "Connection cancelled"
    window.close()


def test_serial_connect_waits_for_manual_device_info(monkeypatch) -> None:
    class RecordingDevice(SimulatorIoDevice):
        def __init__(self) -> None:
            super().__init__()
            self.clear_count = 0
            self.written_words: list[int] = []

        def clear_input(self) -> None:
            self.clear_count += 1
            super().clear_input()

        def write_word(self, word: int) -> None:
            self.written_words.append(word)
            super().write_word(word)

    device = RecordingDevice()
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(application, "SerialIoDevice", lambda *args, **kwargs: device)
    window = MainWindow()
    window.device_kind.setCurrentText("Serial")

    window._connect_device()
    deadline = time.monotonic() + 1
    while window.connect_worker is not None and window.connect_worker.isRunning():
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("connection worker did not finish")
    app.processEvents()

    assert window.status_label.text() == "Serial connected; click Get Device Info"
    assert window.device_info_button.isEnabled()
    assert window.workflow is None
    assert device.clear_count == 1
    assert device.written_words == []

    window._get_device_info()

    assert "Connected" in window.status_label.text()
    assert window.workflow is not None
    assert device.clear_count == 2
    assert device.written_words
    assert "TX bytes: 5A A5 A5 5A" in window.log_view.toPlainText()
    assert "Bytes written: 22" in window.log_view.toPlainText()
    assert "Flush: done" in window.log_view.toPlainText()
    window.close()
