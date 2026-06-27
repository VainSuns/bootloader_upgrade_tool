"""Minimal source-run PySide6 main window for the Phase 3 workflows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import ProtocolClient, UpgradeWorkflow
from ..firmware import FirmwareImage, build_firmware_image, run_hex2000
from ..io import IoCancelledError, SerialIoDevice, SimulatorIoDevice


class _ConnectWorker(QThread):
    connected = Signal()
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, client: ProtocolClient) -> None:
        super().__init__()
        self.client = client
        self.cancel_event = Event()

    def run(self) -> None:
        try:
            self.client.connect(cancel_event=self.cancel_event)
        except IoCancelledError:
            self.cancelled.emit()
        except Exception as exc:
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))
        else:
            self.connected.emit()

    def cancel(self) -> None:
        self.cancel_event.set()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DSP28377D Bootloader Upgrade Tool")
        self.resize(820, 600)
        self.image: FirmwareImage | None = None
        self.client: ProtocolClient | None = None
        self.workflow: UpgradeWorkflow | None = None
        self.connect_worker: _ConnectWorker | None = None

        self.out_path = QLineEdit()
        self.out_path.setReadOnly(True)
        self.hex2000_path = QLineEdit()
        self.hex2000_path.setPlaceholderText("Optional manual hex2000.exe path")
        self.device_kind = QComboBox()
        self.device_kind.addItems(("Simulator", "Serial"))
        self.serial_port = QLineEdit("COM1")
        self.baudrate = QLineEdit("9600")
        self.sector_mask = QLineEdit("0x1")
        self.status_label = QLabel("Disconnected")
        self.firmware_summary = QPlainTextEdit()
        self.firmware_summary.setReadOnly(True)
        self.firmware_summary.setMaximumHeight(140)
        self.firmware_summary.setPlainText("No firmware loaded")
        self.device_summary = QPlainTextEdit()
        self.device_summary.setReadOnly(True)
        self.device_summary.setMaximumHeight(80)
        self.device_summary.setPlainText("No device connected")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)

        browse = QPushButton("Select .out")
        browse.clicked.connect(self._select_out_file)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._connect_device)
        self.device_info_button = QPushButton("Get Device Info")
        self.device_info_button.setEnabled(False)
        self.device_info_button.clicked.connect(self._get_device_info)

        file_row = QHBoxLayout()
        file_row.addWidget(self.out_path)
        file_row.addWidget(browse)
        form = QFormLayout()
        form.addRow("Application .out", file_row)
        form.addRow("hex2000", self.hex2000_path)
        form.addRow("IO Device", self.device_kind)
        form.addRow("Serial port", self.serial_port)
        form.addRow("Baudrate", self.baudrate)
        form.addRow("Erase sector mask", self.sector_mask)
        form.addRow("Firmware summary", self.firmware_summary)
        form.addRow("Device summary", self.device_summary)

        self.operation_buttons: dict[str, QPushButton] = {}
        operations = QGridLayout()
        for index, (label, callback) in enumerate(
            (
                ("Erase", self._erase),
                ("Program", self._program),
                ("Verify", self._verify),
                ("DFU", self._dfu),
                ("Run", self._run),
                ("Reset", self._reset),
            )
        ):
            button = QPushButton(label)
            button.setEnabled(False)
            button.clicked.connect(callback)
            self.operation_buttons[label] = button
            operations.addWidget(button, index // 3, index % 3)

        connection_row = QHBoxLayout()
        connection_row.addWidget(self.connect_button)
        connection_row.addWidget(self.device_info_button)
        connection_row.addWidget(self.status_label, 1)
        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(connection_row)
        layout.addLayout(operations)
        layout.addWidget(self.progress)
        layout.addWidget(self.log_view, 1)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _log(self, level: str, message: str) -> None:
        self.log_view.appendPlainText(f"{level}: {message}")

    def _show_error(self, title: str, exc: Exception) -> None:
        self._log("ERROR", str(exc))
        QMessageBox.critical(self, title, str(exc))

    def _log_protocol_bytes(self, label: str, data: bytes) -> None:
        text = " ".join(f"{byte:02X}" for byte in data) or "<empty>"
        self._log("PROTO", f"{label}: {text}")

    def _set_firmware_summary(
        self,
        source: Path,
        image: FirmwareImage | None,
        error: Exception | None = None,
    ) -> None:
        size = f"{source.stat().st_size} bytes" if source.is_file() else "unavailable"
        lines = [f"Path: {source}", f"File size: {size}"]
        if image is not None:
            ranges = ", ".join(
                f"0x{item.start:08X}-0x{item.end_exclusive - 1:08X}"
                for item in image.address_ranges
            )
            lines.extend(
                (
                    f"Entry point: 0x{image.entry_point:08X}",
                    f"Block count: {len(image.blocks)}",
                    f"Total words: {image.total_words}",
                    f"Address ranges: {ranges}",
                    "Validation: OK",
                )
            )
        else:
            lines.append("Validation: ERROR")
            if error is not None:
                lines.append(f"Message: {error}")
        self.firmware_summary.setPlainText("\n".join(lines))

    def _select_out_file(self) -> None:
        source_name, _ = QFileDialog.getOpenFileName(
            self, "Select application output", "", "C2000 output (*.out);;All files (*)"
        )
        if not source_name:
            return
        source = Path(source_name)
        self.out_path.setText(str(source))
        generated = source.with_suffix(".sci8.txt")
        manual = self.hex2000_path.text().strip() or None
        try:
            run_hex2000(source, generated, hex2000_path=manual)
            self.image = build_firmware_image(source, generated)
        except Exception as exc:
            self.image = None
            self._set_firmware_summary(source, None, exc)
            self._show_error("Firmware conversion failed", exc)
            self._update_buttons()
            return
        self._set_firmware_summary(source, self.image)
        self._log(
            "INFO",
            f"Loaded {self.image.total_words} words, entry 0x{self.image.entry_point:08X}",
        )
        self._update_buttons()

    def _connect_device(self) -> None:
        if self.connect_worker is not None and self.connect_worker.isRunning():
            self.connect_worker.cancel()
            self.connect_button.setEnabled(False)
            self.status_label.setText("Cancelling connection...")
            return
        if self.client is not None:
            try:
                self.client.close()
            except Exception as exc:
                self._log("WARN", str(exc))
        try:
            if self.device_kind.currentText() == "Simulator":
                device = SimulatorIoDevice()
            else:
                device = SerialIoDevice(
                    self.serial_port.text().strip(), baudrate=int(self.baudrate.text(), 0)
                )
            client = ProtocolClient(
                device,
                post_write_delay_ms=100 if self.device_kind.currentText() == "Serial" else 0,
            )
            client.trace_bytes = self._log_protocol_bytes
            self.client = client
            if self.device_kind.currentText() == "Serial":
                self.connect_worker = _ConnectWorker(client)
                self.connect_worker.connected.connect(self._serial_connection_succeeded)
                self.connect_worker.failed.connect(self._connection_failed)
                self.connect_worker.cancelled.connect(self._connection_cancelled)
                self.connect_button.setText("Cancel")
                self.status_label.setText(
                    f"Waiting for DSP on {self.serial_port.text().strip()} at "
                    f"{self.baudrate.text().strip()} baud..."
                )
                self.device_summary.setPlainText(
                    "Sending ASCII A until DSP autobaud responds. Click Cancel to stop."
                )
                self._update_buttons()
                self.connect_worker.start()
                return
            info = client.open()
        except Exception as exc:
            self._connection_failed(str(exc))
            return
        self._connection_succeeded(info)

    def _serial_connection_succeeded(self) -> None:
        self.workflow = None
        self.connect_button.setText("Connect")
        self.connect_button.setEnabled(True)
        self.device_info_button.setEnabled(True)
        self.status_label.setText("Serial connected; click Get Device Info")
        self.device_summary.setPlainText(
            "Autobaud complete. Input buffer cleared; waiting for the next GUI command."
        )
        self._log("INFO", self.status_label.text())
        self._update_buttons()

    def _get_device_info(self) -> None:
        if self.client is None:
            return
        result = self.client.get_device_info_debug(timeout_ms=5000)
        pending = result.input_bytes_pending_before_clear
        lines = [
            "GetDeviceInfo diagnostic",
            f"Input bytes pending before request clear: {pending if pending is not None else 'unavailable'}",
            "TX words: " + " ".join(f"{word:04X}" for word in result.request_words),
            "TX bytes: " + " ".join(f"{byte:02X}" for byte in result.request_bytes),
            f"Bytes written: {result.bytes_written}",
            f"Flush: {'done' if result.flush_done else 'not done'}",
            "RX bytes: "
            + (" ".join(f"{byte:02X}" for byte in result.rx_bytes) or "<empty>"),
            f"Error stage: {result.error_stage or '<none>'}",
            f"Error message: {result.error_message or '<none>'}",
        ]
        if result.device_info is not None:
            lines.append(
                "Decoded DeviceInfo: "
                f"device=0x{result.device_info.device_id:04X}, "
                f"cpu={result.device_info.cpu_id}, "
                f"max_payload={result.device_info.max_payload_words}, "
                f"max_data={result.device_info.max_data_words}, "
                f"revision=0x{result.device_info.revision_id:08X}, "
                f"uid=0x{result.device_info.uid_unique:08X}"
            )
        self._log("INFO", "\n".join(lines))
        if result.device_info is None:
            self._show_error(
                "Get Device Info failed",
                RuntimeError(result.error_message or "GetDeviceInfo failed"),
            )
            return
        self._connection_succeeded(result.device_info)

    def _connection_succeeded(self, info) -> None:
        assert self.client is not None
        self.workflow = UpgradeWorkflow(self.client, progress=self._on_progress)
        self.connect_button.setText("Connect")
        self.connect_button.setEnabled(True)
        self.device_info_button.setEnabled(True)
        self.status_label.setText(
            f"Connected: device 0x{info.device_id:04X}, max data {info.max_data_words} words"
        )
        self.device_summary.setPlainText(
            f"Device ID: 0x{info.device_id:04X}\n"
            f"Revision ID: 0x{info.revision_id:08X}\n"
            f"UID Unique: 0x{info.uid_unique:08X}"
        )
        self._log("INFO", self.status_label.text())
        self._update_buttons()

    def _connection_failed(self, message: str) -> None:
        self.client = None
        self.workflow = None
        self.connect_button.setText("Connect")
        self.connect_button.setEnabled(True)
        self.device_info_button.setEnabled(False)
        self.status_label.setText("Disconnected")
        self.device_summary.setPlainText(f"Connection failed: {message}")
        self._show_error("Connection failed", RuntimeError(message))
        self._update_buttons()

    def _connection_cancelled(self) -> None:
        self.client = None
        self.workflow = None
        self.connect_button.setText("Connect")
        self.connect_button.setEnabled(True)
        self.device_info_button.setEnabled(False)
        self.status_label.setText("Connection cancelled")
        self.device_summary.setPlainText("No device connected")
        self._log("INFO", "Connection cancelled")
        self._update_buttons()

    def _update_buttons(self) -> None:
        connected = self.workflow is not None
        has_image = self.image is not None
        for name, button in self.operation_buttons.items():
            button.setEnabled(connected and (has_image or name in ("Erase", "Reset")))

    def _on_progress(self, operation: str, current: int, total: int) -> None:
        self.progress.setValue(round(current * 100 / total) if total else 0)
        self.status_label.setText(f"{operation}: {current}/{total}")
        QApplication.processEvents()

    def _require_workflow(self) -> UpgradeWorkflow:
        if self.workflow is None:
            raise RuntimeError("connect an IO Device first")
        return self.workflow

    def _require_image(self) -> FirmwareImage:
        if self.image is None:
            raise RuntimeError("select and convert an application .out file first")
        return self.image

    def _mask(self) -> int:
        return int(self.sector_mask.text().strip(), 0)

    def _operation(self, name: str, action: Callable[[], None]) -> None:
        self.progress.setValue(0)
        try:
            action()
        except Exception as exc:
            self._show_error(f"{name} failed", exc)
            return
        self.progress.setValue(100)
        self.status_label.setText(f"{name} complete")
        self._log("INFO", f"{name} complete")

    def _erase(self) -> None:
        self._operation("Erase", lambda: self._require_workflow().erase(self._mask()))

    def _program(self) -> None:
        self._operation(
            "Program", lambda: self._require_workflow().program(self._require_image())
        )

    def _verify(self) -> None:
        self._operation("Verify", lambda: self._require_workflow().verify(self._require_image()))

    def _dfu(self) -> None:
        self._operation(
            "DFU",
            lambda: self._require_workflow().dfu(self._mask(), self._require_image()),
        )

    def _run(self) -> None:
        self._operation("Run", lambda: self._require_workflow().run(self._require_image()))

    def _reset(self) -> None:
        self._operation("Reset", lambda: self._require_workflow().reset())

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if self.connect_worker is not None and self.connect_worker.isRunning():
            self.connect_worker.cancel()
            self.connect_worker.wait(1000)
        if self.client is not None:
            try:
                self.client.close()
            except Exception as exc:
                self._log("WARN", str(exc))
        event.accept()


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
