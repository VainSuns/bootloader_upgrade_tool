"""Minimal source-run PySide6 main window for the Phase 3 workflows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys

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
from ..io import SerialIoDevice, SimulatorIoDevice


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DSP28377D Bootloader Upgrade Tool")
        self.resize(820, 600)
        self.image: FirmwareImage | None = None
        self.client: ProtocolClient | None = None
        self.workflow: UpgradeWorkflow | None = None

        self.out_path = QLineEdit()
        self.out_path.setReadOnly(True)
        self.hex2000_path = QLineEdit()
        self.hex2000_path.setPlaceholderText("Optional manual hex2000.exe path")
        self.device_kind = QComboBox()
        self.device_kind.addItems(("Simulator", "Serial"))
        self.serial_port = QLineEdit("COM1")
        self.baudrate = QLineEdit("115200")
        self.sector_mask = QLineEdit("0x1")
        self.status_label = QLabel("Disconnected")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)

        browse = QPushButton("Select .out")
        browse.clicked.connect(self._select_out_file)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._connect_device)

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

    def _select_out_file(self) -> None:
        source_name, _ = QFileDialog.getOpenFileName(
            self, "Select application output", "", "C2000 output (*.out);;All files (*)"
        )
        if not source_name:
            return
        source = Path(source_name)
        generated = source.with_suffix(".sci8.txt")
        manual = self.hex2000_path.text().strip() or None
        try:
            run_hex2000(source, generated, hex2000_path=manual)
            self.image = build_firmware_image(source, generated)
        except Exception as exc:
            self.image = None
            self._show_error("Firmware conversion failed", exc)
            return
        self.out_path.setText(str(source))
        self._log(
            "INFO",
            f"Loaded {self.image.total_words} words, entry 0x{self.image.entry_point:08X}",
        )
        self._update_buttons()

    def _connect_device(self) -> None:
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
            client = ProtocolClient(device)
            info = client.open()
            self.client = client
            self.workflow = UpgradeWorkflow(client, progress=self._on_progress)
        except Exception as exc:
            self.client = None
            self.workflow = None
            self.status_label.setText("Disconnected")
            self._show_error("Connection failed", exc)
            self._update_buttons()
            return
        self.status_label.setText(
            f"Connected: device 0x{info.device_id:04X}, max data {info.max_data_words} words"
        )
        self._log("INFO", self.status_label.text())
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
