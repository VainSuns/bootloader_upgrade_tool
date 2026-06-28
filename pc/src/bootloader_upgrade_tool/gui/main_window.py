"""PySide6 main window shell for the bootloader upgrade tool."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import ProtocolClient, UpgradeWorkflow
from ..firmware import FirmwareImage, build_firmware_image, run_hex2000
from ..io import IoCancelledError
from ..protocol.constants import Feature
from .flash_sectors import calculate_sector_mask, touched_sector_names
from .theme import load_theme


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


class _TaskWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int)

    def __init__(self, action: Callable[["_TaskWorker"], object]) -> None:
        super().__init__()
        self.action = action

    def run(self) -> None:
        try:
            result = self.action(self)
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)


class CollapsibleSection(QFrame):
    def __init__(self, title: str, content: QWidget, expanded: bool = False) -> None:
        super().__init__()
        self.setObjectName("CollapsibleSection")
        self.expanded = expanded
        self._content = content

        self._header = QFrame()
        self._header.setObjectName("expanderHeader")
        self._header.setFixedHeight(38)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.mousePressEvent = lambda event: self._toggle_section()
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(10, 0, 12, 0)
        header_layout.setSpacing(6)
        self._arrow = QLabel()
        self._arrow.setObjectName("expanderArrow")
        self._arrow.setFixedWidth(26)
        self._arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(title)
        label.setObjectName("expanderTitle")
        header_layout.addWidget(self._arrow)
        header_layout.addWidget(label, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(content)
        self._sync()

    def _toggle_section(self) -> None:
        self.expanded = not self.expanded
        self._sync()

    def _sync(self) -> None:
        self._content.setVisible(self.expanded)
        self._arrow.setText("▾" if self.expanded else "▸")


class MainWindow(QMainWindow):
    protocol_log = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        icon = QIcon(str(Path(__file__).with_name("resources") / "images" / "icon.png"))
        if app is not None:
            load_theme(app)
            app.setWindowIcon(icon)
        self.setWindowTitle("DSP28377D Bootloader Upgrade Tool")
        self.setWindowIcon(icon)
        self.resize(1080, 760)
        self.image: FirmwareImage | None = None
        self.client: ProtocolClient | None = None
        self.workflow: UpgradeWorkflow | None = None
        self.connect_worker: _ConnectWorker | None = None
        self.task_worker: _TaskWorker | None = None
        self.device_info = None
        self.device_features = Feature(0)
        self.calculated_sector_mask: int | None = None
        self.console_expanded = False
        self.console_log_count = 0
        self.page_names = ("Device", "Firmware", "Operation", "Memory", "Logs", "Settings")
        self.nav_buttons: dict[str, QPushButton] = {}
        self.protocol_log.connect(lambda text: self._log("PROTO", text))

        self._create_controls()
        self._build_layout()
        self._update_buttons()

    def _create_controls(self) -> None:
        self.out_path = QLineEdit()
        self.out_path.setObjectName("firmwarePathEdit")
        self.out_path.setReadOnly(True)
        self.hex2000_path = QLineEdit()
        self.hex2000_path.setPlaceholderText("Optional manual hex2000.exe path")
        self.device_kind = QComboBox()
        self.device_kind.addItems(("Simulator", "Serial"))
        self.serial_port = QLineEdit("COM1")
        self.serial_port.setMaximumWidth(260)
        self.baudrate = QLineEdit("9600")
        self.baudrate.setMaximumWidth(200)
        self.sector_mask = QLineEdit()
        self.sector_mask.setReadOnly(True)
        self.sector_mask.setPlaceholderText("Calculated after firmware load")
        self.sector_mask.setMaximumWidth(220)
        self.status_dot = QLabel()
        self.status_dot.setObjectName("StatusDot")
        self.status_dot.setProperty("state", "disconnected")
        self.status_label = QLabel("Disconnected")
        self.status_label.setObjectName("StatusText")
        self.status_label.setProperty("state", "disconnected")

        self.firmware_summary = QPlainTextEdit()
        self.firmware_summary.setProperty("role", "summary")
        self.firmware_summary.setReadOnly(True)
        self.firmware_summary.setMinimumHeight(100)
        self.firmware_summary.setMaximumHeight(120)
        self.firmware_summary.setPlainText("No firmware loaded")
        self.device_summary = QPlainTextEdit()
        self.device_summary.setProperty("role", "summary")
        self.device_summary.setReadOnly(True)
        self.device_summary.setMinimumHeight(100)
        self.device_summary.setMaximumHeight(120)
        self.device_summary.setPlainText("No device connected")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(10)
        self.progress.setTextVisible(False)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("consoleLogView")
        self.log_view.setReadOnly(True)

        self.browse_button = QPushButton("Select .out")
        self.browse_button.setProperty("variant", "secondary")
        self.browse_button.setFixedWidth(116)
        self.browse_button.clicked.connect(self._select_out_file)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("variant", "primary")
        self.connect_button.clicked.connect(self._connect_device)
        self.device_info_button = QPushButton("Get Device Info")
        self.device_info_button.setProperty("variant", "secondary")
        self.device_info_button.setEnabled(False)
        self.device_info_button.clicked.connect(self._get_device_info)

        self.operation_buttons: dict[str, QPushButton] = {}
        for label, callback in (
            ("Erase", self._erase),
            ("Program", self._program),
            ("Verify", self._verify),
            ("DFU", self._dfu),
            ("Run", self._run),
        ):
            button = QPushButton(label)
            button.setEnabled(False)
            button.clicked.connect(callback)
            button.setProperty("variant", "secondary")
            self.operation_buttons[label] = button
        self.operation_buttons["DFU"].setProperty("variant", "primary")
        for name in ("Erase", "Program", "Verify", "DFU"):
            self.operation_buttons[name].setFixedWidth(132)
        self.operation_buttons["Run"].setFixedWidth(150)
        for control in (
            self.out_path,
            self.hex2000_path,
            self.device_kind,
            self.serial_port,
            self.baudrate,
            self.sector_mask,
            self.browse_button,
            self.connect_button,
            self.device_info_button,
            *self.operation_buttons.values(),
        ):
            control.setFixedHeight(32)

    def _build_layout(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_top_bar())

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.setObjectName("MainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self._build_body())
        self.console_container = self._build_console_container()
        self.main_splitter.addWidget(self.console_container)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        self.main_splitter.setSizes([700, 40])
        layout.addWidget(self.main_splitter, 1)
        self.setCentralWidget(root)

    def _build_console_container(self) -> QWidget:
        container = QFrame()
        container.setObjectName("ConsoleContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.console_panel = self._build_bottom_console()
        self.console_collapsed_bar = self._build_console_collapsed_bar()
        layout.addWidget(self.console_panel)
        layout.addWidget(self.console_collapsed_bar)
        self._sync_console_visibility()
        return container

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(52)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 16, 0)
        layout.setSpacing(8)
        title = QLabel("DSP28377D Bootloader Upgrade Tool")
        title.setObjectName("TopBarTitle")
        settings = QPushButton("Settings")
        settings.setProperty("variant", "toolbar")
        settings.clicked.connect(lambda: self._select_page("Settings"))
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(self.status_dot)
        layout.addWidget(self.status_label)
        layout.addWidget(settings)
        return bar

    def _build_body(self) -> QWidget:
        body = QWidget()
        body.setObjectName("Body")
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.setObjectName("BodySplitter")
        self.body_splitter.setChildrenCollapsible(False)
        self.sidebar = self._build_side_nav()
        self.body_splitter.addWidget(self.sidebar)
        self.main_stack = QStackedWidget()
        self.main_stack.setObjectName("MainStack")
        self.main_stack.addWidget(
            self._build_placeholder_page("Device", QLabel("Device details will live here."))
        )
        self.main_stack.addWidget(
            self._build_placeholder_page("Firmware", QLabel("Firmware details will live here."))
        )
        self.main_stack.addWidget(self._scroll_page(self._build_operation_page()))
        self.main_stack.addWidget(
            self._build_placeholder_page("Memory", QLabel("Memory map and sectors will live here."))
        )
        self.main_stack.addWidget(
            self._build_placeholder_page("Logs", QLabel("Use the bottom console for live logs."))
        )
        self.main_stack.addWidget(self._scroll_page(self._build_settings_page()))
        self._select_page("Operation")
        self.body_splitter.addWidget(self.main_stack)
        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)
        self.body_splitter.setSizes([184, 1100])
        layout.addWidget(self.body_splitter, 1)
        return body

    def _build_side_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("SideNav")
        nav.setMinimumWidth(160)
        nav.setMaximumWidth(260)
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)
        group = QButtonGroup(nav)
        group.setExclusive(True)
        for index, name in enumerate(self.page_names):
            button = QPushButton(name)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setProperty("nav", True)
            button.clicked.connect(lambda checked=False, page=name: self._select_page(page))
            group.addButton(button, index)
            self.nav_buttons[name] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self.nav_group = group
        return nav

    def _select_page(self, page_name: str) -> None:
        index = self.page_names.index(page_name)
        self.main_stack.setCurrentIndex(index)
        for name, button in self.nav_buttons.items():
            selected = name == page_name
            button.setChecked(selected)
            button.setProperty("selected", "true" if selected else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def _scroll_page(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("PageScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_operation_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("OperationPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._build_firmware_card())
        layout.addWidget(self._build_target_device_card())
        layout.addWidget(self._build_flash_operation_card())
        layout.addWidget(self._build_target_control_card())
        layout.addStretch(1)
        return page

    def _build_firmware_card(self) -> QWidget:
        card, layout = self._card("Firmware Image")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.out_path, 1)
        row.addWidget(self.browse_button)
        layout.addLayout(row)
        summary_label = QLabel("Firmware Summary")
        summary_label.setObjectName("FieldHeading")
        layout.addWidget(summary_label)
        layout.addWidget(self.firmware_summary)
        return card

    def _build_target_device_card(self) -> QWidget:
        card, layout = self._card("Target Device")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        transport_label = QLabel("Transport")
        serial_label = QLabel("Serial Port")
        baud_label = QLabel("Baud Rate")
        for label in (transport_label, serial_label, baud_label):
            label.setObjectName("FieldLabel")
            label.setFixedWidth(96)
        grid.addWidget(transport_label, 0, 0)
        grid.addWidget(self.device_kind, 0, 1, 1, 3)
        grid.addWidget(serial_label, 1, 0)
        grid.addWidget(self.serial_port, 1, 1)
        grid.addWidget(baud_label, 1, 2)
        grid.addWidget(self.baudrate, 1, 3)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.connect_button)
        actions.addWidget(self.device_info_button)
        actions.addStretch(1)
        grid.addLayout(actions, 2, 1, 1, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        summary_label = QLabel("Target Device Summary")
        summary_label.setObjectName("FieldHeading")
        layout.addWidget(summary_label)
        layout.addWidget(self.device_summary)
        return card

    def _build_flash_operation_card(self) -> QWidget:
        card, layout = self._card("Flash Operation")
        mask_row = QHBoxLayout()
        mask_label = QLabel("Erase Sector Mask")
        mask_label.setObjectName("FieldLabel")
        mask_label.setFixedWidth(128)
        mask_row.addWidget(mask_label)
        mask_row.addWidget(self.sector_mask)
        mask_row.addStretch(1)
        layout.addLayout(mask_row)
        grid = QHBoxLayout()
        grid.setSpacing(8)
        for index, name in enumerate(("Erase", "Program", "Verify", "DFU")):
            grid.addWidget(self.operation_buttons[name])
        grid.addStretch(1)
        layout.addLayout(grid)
        progress_label = QLabel("Progress")
        progress_label.setObjectName("FieldHeading")
        layout.addWidget(progress_label)
        layout.addWidget(self.progress)
        return card

    def _build_target_control_card(self) -> QWidget:
        card, layout = self._card("Target Control")
        row = QHBoxLayout()
        row.addWidget(self.operation_buttons["Run"])
        row.addStretch(1)
        layout.addLayout(row)
        return card

    def _build_bottom_console(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("BottomConsole")
        panel.setMinimumHeight(120)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(0)
        header_bar = QFrame()
        header_bar.setObjectName("ConsoleHeader")
        header = QHBoxLayout(header_bar)
        header.setContentsMargins(12, 0, 12, 0)
        header.setSpacing(8)
        title = QLabel("Console")
        title.setObjectName("ConsoleTitle")
        clear = QPushButton("Clear")
        clear.setProperty("variant", "consoleTool")
        clear.clicked.connect(self._clear_console)
        save = QPushButton("Save Log")
        save.setProperty("variant", "consoleTool")
        save.setEnabled(False)
        raw = QPushButton("Raw Trace")
        raw.setProperty("variant", "consoleTool")
        raw.setEnabled(False)
        collapse = QPushButton("Collapse")
        collapse.setProperty("variant", "consoleTool")
        collapse.clicked.connect(self._toggle_console)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(raw)
        header.addWidget(clear)
        header.addWidget(save)
        header.addWidget(collapse)
        layout.addWidget(header_bar)
        layout.addWidget(self.log_view, 1)
        return panel

    def _build_console_collapsed_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ConsoleCollapsedBar")
        bar.setFixedHeight(32)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(6)
        button = QPushButton("Console")
        button.setObjectName("ConsoleCollapsedButton")
        button.clicked.connect(self._toggle_console)
        self.console_count_label = QLabel("0")
        self.console_count_label.setObjectName("ConsoleCountBadge")
        self.console_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.console_count_label.setVisible(False)
        layout.addWidget(button)
        layout.addWidget(self.console_count_label)
        layout.addStretch(1)
        return bar

    def _toggle_console(self) -> None:
        self.console_expanded = not self.console_expanded
        self._sync_console_visibility()

    def _sync_console_visibility(self) -> None:
        self.console_panel.setVisible(self.console_expanded)
        self.console_collapsed_bar.setVisible(not self.console_expanded)
        if hasattr(self, "main_splitter"):
            self.main_splitter.setSizes([700, 220] if self.console_expanded else [900, 40])

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("SettingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)
        layout.addWidget(
            self._settings_section(
                "Toolchain Settings",
                (("hex2000.exe path", self.hex2000_path),),
                expanded=True,
            )
        )
        layout.addWidget(
            self._settings_section(
                "Connection Settings",
                (("Default Transport", QLabel("Simulator")), ("Default Baud Rate", QLabel("9600"))),
                expanded=True,
            )
        )
        layout.addWidget(
            self._settings_section(
                "Protocol Settings",
                (("Raw Protocol Trace", QLabel("Disabled")), ("Post-write Delay", QLabel("100 ms"))),
            )
        )
        layout.addWidget(
            self._settings_section(
                "Flash Operation Settings",
                (
                    ("Erase Sector Mask", QLabel("Calculated from firmware image")),
                    ("Verify After Program", QLabel("Enabled")),
                ),
            )
        )
        layout.addWidget(
            self._settings_section(
                "Logging Settings",
                (
                    ("Log Level", QLabel("INFO")),
                    ("Save .log", QLabel("Enabled")),
                    ("Save .jsonl", QLabel("Enabled")),
                ),
            )
        )
        layout.addWidget(
            self._settings_section(
                "Advanced / Experimental",
                (
                    ("Reset Target", QLabel("Not exposed in GUI")),
                    ("W5300/TCP", QLabel("Future")),
                ),
            )
        )
        layout.addStretch(1)
        return page

    def _settings_section(
        self, title: str, rows: tuple[tuple[str, QWidget], ...], expanded: bool = False
    ) -> CollapsibleSection:
        content = QWidget()
        content.setObjectName("expanderContent")
        form = QGridLayout(content)
        form.setContentsMargins(24, 10, 12, 12)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setColumnMinimumWidth(0, 160)
        form.setColumnStretch(1, 1)
        for row, (label, widget) in enumerate(rows):
            field_label = QLabel(label)
            field_label.setObjectName("FieldLabel")
            field_label.setProperty("role", "expanderContentLabel")
            form.addWidget(field_label, row, 0)
            if isinstance(widget, QLabel):
                widget.setProperty("role", "expanderContentLabel")
            form.addWidget(widget, row, 1)
        return CollapsibleSection(title, content, expanded)

    def _build_placeholder_page(self, title: str, content: QWidget) -> QWidget:
        page = QWidget()
        page.setObjectName(f"{title}Page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        card, card_layout = self._card(title)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        card_layout.addWidget(content)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        card.setProperty("role", "card")
        card.setMaximumWidth(1120)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        label = QLabel(title)
        label.setObjectName("CardTitle")
        label.setProperty("role", "cardTitle")
        layout.addWidget(label)
        return card, layout

    def _set_status(self, text: str, state: str = "disconnected") -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_dot.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

    def _log(self, level: str, message: str) -> None:
        self.log_view.appendPlainText(f"{level}: {message}")
        self.console_log_count += 1
        self.console_count_label.setText(str(self.console_log_count))
        self.console_count_label.setVisible(self.console_log_count > 0)

    def _clear_console(self) -> None:
        self.log_view.clear()
        self.console_log_count = 0
        self.console_count_label.setVisible(False)

    def _show_error(self, title: str, exc: Exception) -> None:
        self._log("ERROR", str(exc))
        QMessageBox.critical(self, title, str(exc))

    def _log_protocol_bytes(self, label: str, data: bytes) -> None:
        text = " ".join(f"{byte:02X}" for byte in data) or "<empty>"
        self.protocol_log.emit(f"{label}: {text}")

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
            try:
                self.calculated_sector_mask = calculate_sector_mask(image)
                self.sector_mask.setText(f"0x{self.calculated_sector_mask:08X}")
                sector_line = "Touched sectors: " + ", ".join(touched_sector_names(image))
                validation = "Validation: OK"
            except Exception as exc:
                self.calculated_sector_mask = None
                self.sector_mask.clear()
                sector_line = "Touched sectors: unavailable"
                validation = f"Validation: ERROR ({exc})"
            lines.extend(
                (
                    f"Entry point: 0x{image.entry_point:08X}",
                    f"Block count: {len(image.blocks)}",
                    f"Total words: {image.total_words}",
                    f"Address ranges: {ranges}",
                    f"Calculated sector_mask: {self.sector_mask.text() or '<none>'}",
                    sector_line,
                    validation,
                )
            )
        else:
            self.calculated_sector_mask = None
            self.sector_mask.clear()
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

        def load_firmware(_worker: _TaskWorker) -> tuple[Path, FirmwareImage]:
            run_hex2000(source, generated, hex2000_path=manual)
            return source, build_firmware_image(source, generated)

        def loaded(result: object) -> None:
            loaded_source, loaded_image = result
            self.image = loaded_image
            self._set_firmware_summary(loaded_source, self.image)
            self._log(
                "INFO",
                f"Loaded {self.image.total_words} words, entry 0x{self.image.entry_point:08X}",
            )

        self.image = None
        self._set_firmware_summary(source, None)
        self._start_task("Firmware conversion", load_firmware, loaded)

    def _connect_device(self) -> None:
        if self.connect_worker is not None and self.connect_worker.isRunning():
            self.connect_worker.cancel()
            self.connect_button.setEnabled(False)
            self._set_status("Cancelling connection...", "busy")
            return
        if self.client is not None:
            try:
                self.client.close()
            except Exception as exc:
                self._log("WARN", str(exc))
        try:
            from . import application

            if self.device_kind.currentText() == "Simulator":
                device = application.SimulatorIoDevice()
            else:
                device = application.SerialIoDevice(
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
                self._set_status(
                    f"Waiting for DSP on {self.serial_port.text().strip()} at "
                    f"{self.baudrate.text().strip()} baud...",
                    "busy",
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
        self._set_status("Serial connected; click Get Device Info", "connected")
        self.device_summary.setPlainText(
            "Autobaud complete. Waiting for the next GUI command."
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
        self.device_info = info
        self.device_features = Feature(info.feature_flags)
        self.workflow = UpgradeWorkflow(self.client, progress=self._on_progress)
        self.connect_button.setText("Connect")
        self.connect_button.setEnabled(True)
        self.device_info_button.setEnabled(True)
        self._set_status(
            f"Connected: device 0x{info.device_id:04X}, max data {info.max_data_words} words",
            "connected",
        )
        self.device_summary.setPlainText(
            f"Device ID: 0x{info.device_id:04X}\n"
            f"CPU ID: {info.cpu_id}\n"
            f"Protocol Version: {info.protocol_ver}\n"
            f"Feature Flags: 0x{info.feature_flags:08X} ({self._feature_names(info.feature_flags)})\n"
            f"Max Payload Words: {info.max_payload_words}\n"
            f"Max Data Words: {info.max_data_words}\n"
            f"Boot Mode: {info.boot_mode}\n"
            f"Kernel Layout: {info.kernel_layout}\n"
            f"Revision ID: 0x{info.revision_id:08X}\n"
            f"UID Unique: 0x{info.uid_unique:08X}"
        )
        self._log("INFO", self.status_label.text())
        self._update_buttons()

    def _connection_failed(self, message: str) -> None:
        self.client = None
        self.workflow = None
        self.device_info = None
        self.device_features = Feature(0)
        self.connect_button.setText("Connect")
        self.connect_button.setEnabled(True)
        self.device_info_button.setEnabled(False)
        self._set_status("Disconnected", "disconnected")
        self.device_summary.setPlainText(f"Connection failed: {message}")
        self._show_error("Connection failed", RuntimeError(message))
        self._update_buttons()

    def _connection_cancelled(self) -> None:
        self.client = None
        self.workflow = None
        self.device_info = None
        self.device_features = Feature(0)
        self.connect_button.setText("Connect")
        self.connect_button.setEnabled(True)
        self.device_info_button.setEnabled(False)
        self._set_status("Connection cancelled", "warning")
        self.device_summary.setPlainText("No device connected")
        self._log("INFO", "Connection cancelled")
        self._update_buttons()

    def _update_buttons(self) -> None:
        busy = self._is_busy()
        connected = self.workflow is not None
        has_image = self.image is not None
        has_mask = self.calculated_sector_mask is not None
        features = self.device_features
        required = {
            "Erase": Feature.ERASE,
            "Program": Feature.PROGRAM,
            "Verify": Feature.VERIFY,
            "Run": Feature.RUN,
        }
        self.browse_button.setEnabled(not busy)
        self.device_info_button.setEnabled(not busy and self.client is not None)
        for name, button in self.operation_buttons.items():
            if busy or not connected:
                button.setEnabled(False)
                continue
            if name == "DFU":
                needed = Feature.ERASE | Feature.PROGRAM | Feature.VERIFY
                button.setEnabled(has_image and has_mask and (features & needed) == needed)
                continue
            feature = required[name]
            needs_image = name in {"Erase", "Program", "Verify", "Run"}
            needs_mask = name == "Erase"
            button.setEnabled(
                (features & feature) == feature
                and (has_image if needs_image else True)
                and (has_mask if needs_mask else True)
            )

    def _on_progress(self, operation: str, current: int, total: int) -> None:
        self.progress.setValue(round(current * 100 / total) if total else 0)
        self._set_status(f"{operation}: {current}/{total}", "busy")

    def _require_workflow(self) -> UpgradeWorkflow:
        if self.workflow is None:
            raise RuntimeError("connect an IO Device first")
        return self.workflow

    def _require_image(self) -> FirmwareImage:
        if self.image is None:
            raise RuntimeError("select and convert an application .out file first")
        return self.image

    def _mask(self) -> int:
        if self.calculated_sector_mask is None:
            raise RuntimeError("load a valid firmware image before erase")
        if self.calculated_sector_mask & 0x1:
            raise RuntimeError("calculated sector_mask includes forbidden Sector A")
        return self.calculated_sector_mask

    def _is_busy(self) -> bool:
        return (
            (self.connect_worker is not None and self.connect_worker.isRunning())
            or (self.task_worker is not None and self.task_worker.isRunning())
        )

    def _feature_names(self, flags: int) -> str:
        features = Feature(flags)
        names = [feature.name for feature in Feature if feature in features]
        known = 0
        for feature in Feature:
            known |= int(feature)
        unknown = flags & ~known
        if unknown:
            names.append(f"UNKNOWN_0x{unknown:X}")
        return ", ".join(names) if names else "none"

    def _start_task(
        self,
        name: str,
        action: Callable[[_TaskWorker], object],
        on_success: Callable[[object], None] | None = None,
    ) -> None:
        if self.task_worker is not None and self.task_worker.isRunning():
            self._show_error("Operation busy", RuntimeError("another operation is already active"))
            return
        self.progress.setValue(0)
        self._set_status(f"{name} running...", "busy")
        worker = _TaskWorker(action)
        self.task_worker = worker
        worker.progress.connect(self._on_progress)

        def succeeded(result: object) -> None:
            if on_success is not None:
                on_success(result)
            self.progress.setValue(100)
            self._set_status(f"{name} complete", "complete")
            self._log("INFO", f"{name} complete")
            self.task_worker = None
            self._update_buttons()

        def failed(message: str) -> None:
            self.task_worker = None
            self._show_error(f"{name} failed", RuntimeError(message))
            self._update_buttons()

        worker.succeeded.connect(succeeded)
        worker.failed.connect(failed)
        self._update_buttons()
        worker.start()

    def _operation(self, name: str, action: Callable[[], None]) -> None:
        def run_action(worker: _TaskWorker) -> None:
            if self.workflow is not None:
                self.workflow.progress = worker.progress.emit
            action()

        self._start_task(name, run_action)

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

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if self.connect_worker is not None and self.connect_worker.isRunning():
            self.connect_worker.cancel()
            self.connect_worker.wait(1000)
        if self.task_worker is not None and self.task_worker.isRunning():
            self.task_worker.wait(1000)
        if self.client is not None:
            try:
                self.client.close()
            except Exception as exc:
                self._log("WARN", str(exc))
        event.accept()
