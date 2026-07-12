"""Static Operate Ribbon page for transport and normal workflow controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...icon_manager import IconManager
from ...layout_metrics import (
    RIBBON_TRANSPORT_FIELD_HEIGHT,
    RIBBON_TRANSPORT_TAB_HEIGHT,
    RIBBON_TRANSPORT_TABS_HEIGHT,
)
from ..input_controls import IndicatorComboBox
from ..status_widgets import StatusDot
from ...ui_state import set_ui_role
from .ribbon_shell import (
    RibbonButtonSpec,
    RibbonGroup,
    create_ribbon_button,
    create_ribbon_page,
)


class OperateRibbon(QWidget):
    connectRequested = Signal()
    disconnectRequested = Signal()
    loadImageRequested = Signal()
    runRequested = Signal()

    def __init__(
        self,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("operateRibbonPage")
        self._icon_manager = icon_manager or IconManager()
        self._connected = False
        self._controls_enabled = False

        page = create_ribbon_page("operateRibbonContent", self)
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(page, 0, 0)
        row = page.layout()

        row.addWidget(self._create_transport_group(page))
        row.addWidget(self._create_operation_group(page))
        row.addWidget(self._create_status_group(page))
        row.addStretch(1)

    def set_operation_controls_enabled(self, enabled: bool) -> None:
        self._controls_enabled = bool(enabled)
        self.connect_button.setEnabled(enabled)
        self.sci_port_combo.setEnabled(enabled and not self._connected)
        self.sci_baud_combo.setEnabled(enabled and not self._connected)
        self.load_image_button.setEnabled(False)
        self.run_button.setEnabled(False)

    def set_connected(self, connected: bool) -> None:
        self._connected = bool(connected)
        self.connect_button.setText("Disconnect" if connected else "Connect")
        semantic = (
            "ribbon.connection.disconnect" if connected else "ribbon.connection.connect"
        )
        self.connect_button.setIcon(self._icon_manager.icon(semantic, size=24))
        self.sci_port_combo.setEnabled(self._controls_enabled and not connected)
        self.sci_baud_combo.setEnabled(self._controls_enabled and not connected)

    def set_cpu_status(self, target: str, text: str, state: str) -> None:
        normalized = target.strip().lower()
        if normalized == "cpu1":
            dot, label = self.cpu1_status_dot, self.cpu1_status_text
        elif normalized == "cpu2":
            dot, label = self.cpu2_status_dot, self.cpu2_status_text
        else:
            raise ValueError(f"unknown target status row: {target!r}")
        dot.set_state(state)
        label.setText(text)

    def _create_transport_group(self, parent: QWidget) -> RibbonGroup:
        group = RibbonGroup("Transport", object_name="transportRibbonGroup", parent=parent)
        group.setMinimumWidth(360)
        group.setMaximumWidth(390)

        self.transport_tabs = QTabWidget(group)
        self.transport_tabs.setObjectName("transportTabs")
        self.transport_tabs.setDocumentMode(True)
        self.transport_tabs.setFixedHeight(RIBBON_TRANSPORT_TABS_HEIGHT)
        self.transport_tabs.tabBar().setObjectName("transportTabBar")
        self.transport_tabs.tabBar().setFixedHeight(RIBBON_TRANSPORT_TAB_HEIGHT)
        self.transport_tabs.tabBar().setUsesScrollButtons(False)
        # The global tab/input QSS is intentionally roomy. This compact,
        # dimension-only override keeps the 86 px Ribbon content row unclipped.
        field_height = RIBBON_TRANSPORT_FIELD_HEIGHT
        # Qt stylesheet min/max-height applies to the content box; the 1 px
        # top and bottom borders add two logical pixels to the final geometry.
        field_content_height = max(0, field_height - 2)
        self.transport_tabs.setStyleSheet(
            "QTabBar::tab { min-height: 18px; max-height: 20px; padding: 1px 10px; } "
            f"QComboBox, QLineEdit {{ min-height: {field_content_height}px; max-height: {field_content_height}px; }} "
            "QComboBox { padding-left: 6px; padding-right: 24px; } "
            "QComboBox::drop-down { width: 20px; }"
        )

        sci = QWidget(self.transport_tabs)
        sci_layout = QHBoxLayout(sci)
        sci_layout.setContentsMargins(6, 0, 6, 0)
        sci_layout.setSpacing(6)
        sci_layout.addWidget(QLabel("Port:"))
        self.sci_port_combo = IndicatorComboBox(
            sci, icon_manager=self._icon_manager, indicator_width=20
        )
        self.sci_port_combo.setObjectName("sciPortCombo")
        self.sci_port_combo.setEditable(True)
        self.sci_port_combo.setInsertPolicy(IndicatorComboBox.InsertPolicy.NoInsert)
        self.sci_port_combo.clear()
        self.sci_port_combo.setCurrentIndex(-1)
        self.sci_port_combo.lineEdit().setPlaceholderText("Select or enter COM port")
        self.sci_port_combo.setFixedWidth(150)
        self.sci_port_combo.setFixedHeight(RIBBON_TRANSPORT_FIELD_HEIGHT)
        self.sci_port_combo.setToolTip("Select a port or enter a COM port manually.")
        sci_layout.addWidget(self.sci_port_combo)
        sci_layout.addWidget(QLabel("Baud:"))
        self.sci_baud_combo = IndicatorComboBox(
            sci, icon_manager=self._icon_manager, indicator_width=20
        )
        self.sci_baud_combo.setObjectName("sciBaudCombo")
        self.sci_baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.sci_baud_combo.setFixedWidth(112)
        self.sci_baud_combo.setFixedHeight(RIBBON_TRANSPORT_FIELD_HEIGHT)
        sci_layout.addWidget(self.sci_baud_combo)
        self.transport_tabs.addTab(
            sci, self._icon_manager.icon("ribbon.transport.sci", size=16), "SCI"
        )

        tcp = QWidget(self.transport_tabs)
        tcp.setEnabled(False)
        tcp_layout = QHBoxLayout(tcp)
        tcp_layout.setContentsMargins(6, 0, 6, 0)
        tcp_layout.setSpacing(6)
        tcp_layout.addWidget(QLabel("IP:"))
        self.tcp_ip_edit = QLineEdit("192.168.1.100", tcp)
        self.tcp_ip_edit.setObjectName("tcpIpLineEdit")
        self.tcp_ip_edit.setFixedWidth(150)
        self.tcp_ip_edit.setFixedHeight(RIBBON_TRANSPORT_FIELD_HEIGHT)
        tcp_layout.addWidget(self.tcp_ip_edit)
        tcp_layout.addWidget(QLabel("Port:"))
        self.tcp_port_edit = QLineEdit("5000", tcp)
        self.tcp_port_edit.setObjectName("tcpPortLineEdit")
        self.tcp_port_edit.setMaximumWidth(72)
        self.tcp_port_edit.setFixedHeight(RIBBON_TRANSPORT_FIELD_HEIGHT)
        tcp_layout.addWidget(self.tcp_port_edit)
        self.transport_tabs.addTab(
            tcp, self._icon_manager.icon("ribbon.transport.tcp", size=16), "TCP"
        )
        self.transport_tabs.setTabEnabled(1, False)
        self.transport_tabs.setToolTip("Reserved for future W5300 TCP transport.")
        group.add_widget(self.transport_tabs, 1)
        return group

    def _create_operation_group(self, parent: QWidget) -> RibbonGroup:
        group = RibbonGroup("Operate", object_name="operationRibbonGroup", parent=parent)
        group.setMinimumWidth(230)
        self.connect_button = create_ribbon_button(
            RibbonButtonSpec(
                "Connect",
                "connectButton",
                "ribbon.connection.connect",
                enabled=False,
                tooltip="Connect or disconnect the selected SCI / RS232 port.",
            ),
            icon_manager=self._icon_manager,
            parent=group,
        )
        self.load_image_button = create_ribbon_button(
            RibbonButtonSpec(
                "Load\nImage",
                "loadImageButton",
                "ribbon.operation.load_image",
                enabled=False,
            ),
            icon_manager=self._icon_manager,
            parent=group,
        )
        self.run_button = create_ribbon_button(
            RibbonButtonSpec(
                "Run",
                "runButton",
                "ribbon.operation.run",
                enabled=False,
            ),
            icon_manager=self._icon_manager,
            parent=group,
        )
        self.connect_button.clicked.connect(lambda _checked=False: self._on_connect_clicked())
        self.load_image_button.clicked.connect(lambda _checked=False: self.loadImageRequested.emit())
        self.run_button.clicked.connect(lambda _checked=False: self.runRequested.emit())
        for button in (self.connect_button, self.load_image_button, self.run_button):
            group.add_widget(button)
        return group

    def _create_status_group(self, parent: QWidget) -> RibbonGroup:
        group = RibbonGroup("Status", object_name="cpuStatusRibbonGroup", parent=parent)
        group.setMinimumWidth(170)
        container = QWidget(group)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(4)
        self.cpu1_status_dot, self.cpu1_status_text = self._status_row(
            container, "CPU1", "Unavailable", "cpu1StatusIndicator", "cpu1StatusText"
        )
        self.cpu2_status_dot, self.cpu2_status_text = self._status_row(
            container, "CPU2", "Unavailable", "cpu2StatusIndicator", "cpu2StatusText"
        )
        layout.addWidget(self.cpu1_status_dot.parentWidget())
        layout.addWidget(self.cpu2_status_dot.parentWidget())
        group.add_widget(container, 1)
        return group

    def _status_row(
        self,
        parent: QWidget,
        target: str,
        text: str,
        dot_name: str,
        text_name: str,
    ) -> tuple[StatusDot, QLabel]:
        row = QWidget(parent)
        row.setFixedHeight(24)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        dot = StatusDot(
            "unavailable",
            accessible_name=f"{target} status",
            object_name=dot_name,
            parent=row,
        )
        layout.addWidget(dot)
        target_label = QLabel(target, row)
        target_label.setMinimumWidth(34)
        set_ui_role(target_label, "fieldLabel")
        layout.addWidget(target_label)
        value = QLabel(text, row)
        value.setObjectName(text_name)
        set_ui_role(value, "valueLabel")
        layout.addWidget(value, 1)
        return dot, value

    def _on_connect_clicked(self) -> None:
        if self._connected:
            self.disconnectRequested.emit()
        else:
            self.connectRequested.emit()
