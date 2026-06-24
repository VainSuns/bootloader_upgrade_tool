import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui import MainWindow
from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage


def test_main_window_connects_only_through_io_device_abstraction() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
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
