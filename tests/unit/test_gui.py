import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog

from bootloader_upgrade_tool.gui import MainWindow
from bootloader_upgrade_tool.gui.flash_sectors import calculate_sector_mask
from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.io import IoCancelledError, SimulatorIoDevice
from bootloader_upgrade_tool.gui import application


def wait_for_task(window: MainWindow, app: QApplication) -> None:
    deadline = time.monotonic() + 1
    while window.task_worker is not None and window.task_worker.isRunning():
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("task worker did not finish")
    app.processEvents()


def test_main_window_connects_only_through_io_device_abstraction() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.baudrate.text() == "9600"
    window._connect_device()

    assert "Connected" in window.status_label.text()
    assert window.workflow is not None
    assert "Reset" not in window.operation_buttons
    assert not window.operation_buttons["Erase"].isEnabled()
    assert not window.operation_buttons["Program"].isEnabled()
    assert "CPU ID: 1" in window.device_summary.toPlainText()
    assert "Feature Flags:" in window.device_summary.toPlainText()
    assert "Max Payload Words: 256" in window.device_summary.toPlainText()
    assert "Max Data Words: 248" in window.device_summary.toPlainText()
    assert "Revision ID: 0x00000000" in window.device_summary.toPlainText()
    assert "UID Unique: 0x00000000" in window.device_summary.toPlainText()
    assert "Device ID: 0x377D" in window.device_detail.toPlainText()
    assert "Device connected: yes" in window.workflow_summary.toPlainText()
    assert "DeviceInfo read: yes" in window.workflow_summary.toPlainText()
    assert "Ready for Run: no" in window.workflow_summary.toPlainText()

    window.close()
    app.processEvents()


def test_firmware_summary_is_read_only_and_reports_image(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "app.out"
    source.write_bytes(b"firmware")
    image = FirmwareImage(
        source_out_file=str(source),
        generated_hex_file=str(tmp_path / "app.txt"),
        entry_point=0x082000,
        blocks=(FirmwareBlock(0x082000, (1, 2, 3)),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )
    window = MainWindow()

    window._set_firmware_summary(source, image)

    text = window.firmware_summary.toPlainText()
    assert window.firmware_summary.isReadOnly()
    assert "File size: 8 bytes" in text
    assert "Entry point: 0x00082000" in text
    assert "Block count: 1" in text
    assert "Total words: 3" in text
    assert "Calculated sector_mask: 0x00000002" in text
    assert "Validation: OK" in text
    assert window.sector_mask.text() == "0x00000002"
    assert "FLASHB" in window.firmware_detail.toPlainText()
    assert "App Flash Range: 0x00082000-0x000BFFFF" in window.memory_detail.toPlainText()
    assert "Protected Sector A" in window.memory_detail.toPlainText()
    assert "Allowed Erase Mask: 0x00003FFE" in window.memory_detail.toPlainText()
    assert "Touched Sectors: FLASHB" in window.memory_detail.toPlainText()
    assert "Firmware loaded: no" in window.workflow_summary.toPlainText()
    window.close()
    app.processEvents()


def test_gui_sector_mask_rejects_sector_a() -> None:
    image = FirmwareImage(
        source_out_file="<test>",
        generated_hex_file="<test>",
        entry_point=0x080000,
        blocks=(FirmwareBlock(0x080000, (1, 2, 3)),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )

    try:
        calculate_sector_mask(image)
    except ValueError as exc:
        assert "Sector A" in str(exc)
    else:
        raise AssertionError("Sector A image should be rejected")


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
    app.processEvents()


def test_serial_connect_auto_queries_device_info(monkeypatch) -> None:
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

    deadline = time.monotonic() + 1
    while window.workflow is None:
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("DeviceInfo auto-query did not finish")
    wait_for_task(window, app)

    assert "Connected" in window.status_label.text()
    assert window.workflow is not None
    assert window.client is not None
    assert window.client.post_write_delay_ms == 100
    assert device.clear_count == 1
    assert device.written_words
    assert "TX bytes: 5A A5 A5 5A" in window.log_view.toPlainText()
    assert "Bytes written: 22" in window.log_view.toPlainText()
    assert "Flush: done" in window.log_view.toPlainText()
    assert "GetDeviceInfo: OK" in window.workflow_summary.toPlainText()
    window.close()
    app.processEvents()


def test_save_log_writes_console_text(monkeypatch, tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    target = tmp_path / "gui.log"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))

    window._log("INFO", "hello")
    window._save_log()

    assert "INFO: hello" in target.read_text(encoding="utf-8")
    assert "Saved log to" in window.log_view.toPlainText()
    window.close()
    app.processEvents()
