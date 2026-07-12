from datetime import datetime, timezone

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.pages.settings_page import SettingsPage
from bootloader_upgrade_tool.gui.runtime_binding import RuntimeViewBinding
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, RuntimeSnapshot, RuntimeState
from bootloader_upgrade_tool.gui.serial_ports import SerialPortInfo
from bootloader_upgrade_tool.gui.widgets.ribbon.operate_ribbon import OperateRibbon


class _Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskStateChanged = Signal(object)
    shutdownReady = Signal()
    forceExitReady = Signal(object)

    def __init__(self):
        super().__init__()
        self._snapshot = RuntimeSnapshot()
        self.connect_requests = []
        self.disconnect_requests = []

    @property
    def snapshot(self):
        return self._snapshot

    def request_connect(self, request):
        self.connect_requests.append(request)

    def request_disconnect(self, request):
        self.disconnect_requests.append(request)

    def request_application_close(self):
        raise AssertionError("close is not part of this binding test")


class _Provider:
    def list_ports(self):
        return (
            SerialPortInfo("COM3", "COM3 - FTDI", "device: COM3\nhwid: ftdi"),
            SerialPortInfo("COM4", "COM4 - CH340", "device: COM4\nhwid: ch340"),
        )


def test_binding_uses_ribbon_and_current_timeout_sources_and_preserves_manual_port():
    app = QApplication.instance() or QApplication([])
    ribbon = OperateRibbon()
    settings = SettingsPage()
    controller = _Controller()
    binding = RuntimeViewBinding(
        operate_ribbon=ribbon,
        settings_page=settings,
        controller=controller,
        serial_port_provider=_Provider(),
    )
    ribbon.sci_port_combo.setEditText(" ManualPort ")
    ribbon.sci_baud_combo.setCurrentText("115200")
    settings.current_tx_timeout.setValue(11)
    settings.current_rx_timeout.setValue(22)
    settings.current_autobaud_timeout.setValue(33)
    binding.request_connect()
    request = controller.connect_requests[0]
    assert (request.port, request.baudrate, request.tx_timeout_ms, request.rx_timeout_ms, request.autobaud_timeout_ms) == ("ManualPort", 115200, 11, 22, 33)

    binding.refresh_ports()
    assert ribbon.sci_port_combo.currentText() == " ManualPort "
    assert ribbon.sci_port_combo.itemData(0) == "COM3"
    assert "hwid: ftdi" in ribbon.sci_port_combo.itemData(0, Qt.ItemDataRole.ToolTipRole)
    assert settings.current_port_edit.isReadOnly()
    assert not settings.global_scope.isEnabled()


def test_binding_maps_cpu2_status():
    app = QApplication.instance() or QApplication([])
    ribbon = OperateRibbon()
    settings = SettingsPage()
    controller = _Controller()
    binding = RuntimeViewBinding(operate_ribbon=ribbon, settings_page=settings, controller=controller)
    info = ConnectionInfo("id", "SCI", "COM3", datetime.now(timezone.utc), target_key="cpu2")
    controller._snapshot = RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=info, active_target_key="cpu2")
    binding.apply_snapshot(controller.snapshot)
    assert ribbon.cpu1_status_text.text() == "Not connected"
    assert ribbon.cpu2_status_text.text() == "Connected"
