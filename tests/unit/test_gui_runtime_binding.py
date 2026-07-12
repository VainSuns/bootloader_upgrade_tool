from datetime import datetime, timezone

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.pages.settings_page import SettingsPage
from bootloader_upgrade_tool.gui.runtime_binding import RuntimeViewBinding
from bootloader_upgrade_tool.gui.runtime_models import (
    CompletionPolicy,
    ConnectionInfo,
    ProgressMode,
    RuntimeSnapshot,
    RuntimeState,
    TaskConnectionRequirement,
    TaskPhase,
    TaskPlan,
    TaskState,
    TaskStepPlan,
)
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

    def request_cancel(self, _task_id):
        return None

    def respond_task_action(self, _task_id, _action):
        return None


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
    assert ribbon.sci_port_combo.currentText() == "ManualPort"
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
    assert settings.current_target_combo.currentText() == "CPU2"


def test_binding_rejects_empty_port_without_controller_request():
    app = QApplication.instance() or QApplication([])
    ribbon, settings, controller = OperateRibbon(), SettingsPage(), _Controller()
    binding = RuntimeViewBinding(operate_ribbon=ribbon, settings_page=settings, controller=controller)
    assert binding.request_connect() is None
    assert controller.connect_requests == []
    assert ribbon.sci_port_combo.property("state") == "error"


def test_binding_prefers_manual_edit_over_stale_item_data_and_selected_item_uses_device():
    app = QApplication.instance() or QApplication([])
    ribbon, settings, controller = OperateRibbon(), SettingsPage(), _Controller()
    binding = RuntimeViewBinding(operate_ribbon=ribbon, settings_page=settings, controller=controller, serial_port_provider=_Provider())
    binding.refresh_ports()
    ribbon.sci_port_combo.setCurrentIndex(0)
    binding.request_connect()
    assert controller.connect_requests[-1].port == "COM3"
    ribbon.sci_port_combo.setEditText("COM9")
    binding.request_connect()
    assert controller.connect_requests[-1].port == "COM9"


def test_binding_refresh_preserves_manual_port_and_provider_failure_then_clears_error():
    class FailingProvider:
        def list_ports(self):
            raise OSError("enumeration failed")

    app = QApplication.instance() or QApplication([])
    ribbon, settings, controller = OperateRibbon(), SettingsPage(), _Controller()
    binding = RuntimeViewBinding(operate_ribbon=ribbon, settings_page=settings, controller=controller, serial_port_provider=FailingProvider())
    ribbon.sci_port_combo.setEditText("COM9")
    assert binding.refresh_ports() is None
    assert ribbon.sci_port_combo.currentText() == "COM9" and ribbon.sci_port_combo.property("state") == "error"
    assert binding.last_port_error == "enumeration failed"
    assert ribbon.sci_port_combo.toolTip() == "enumeration failed"
    binding.serial_port_provider = _Provider()
    binding.refresh_ports()
    assert ribbon.sci_port_combo.currentIndex() == -1 and ribbon.sci_port_combo.currentText() == "COM9"
    assert ribbon.sci_port_combo.property("state") == "neutral" and binding.last_port_error is None


def test_binding_unrelated_actions_preserve_enumeration_error_until_port_edit():
    class FailingProvider:
        def list_ports(self):
            raise OSError("enumeration failed")

    app = QApplication.instance() or QApplication([])
    ribbon, settings, controller = OperateRibbon(), SettingsPage(), _Controller()
    binding = RuntimeViewBinding(operate_ribbon=ribbon, settings_page=settings, controller=controller, serial_port_provider=FailingProvider())
    ribbon.sci_port_combo.setEditText("COM9")
    binding.refresh_ports()

    ribbon.sci_baud_combo.setCurrentText("115200")
    binding.request_connect()
    assert controller.connect_requests[-1].port == "COM9"
    assert binding.last_port_error == ribbon.sci_port_combo.toolTip() == "enumeration failed"
    assert ribbon.sci_port_combo.property("state") == "error"

    ribbon.sci_port_combo.setEditText("COM10")
    assert binding.last_port_error is None
    assert ribbon.sci_port_combo.toolTip() == "Select a port or enter a COM port manually."
    assert ribbon.sci_port_combo.property("state") == "neutral"


def test_binding_initial_and_disconnected_target_are_not_identified_and_controls_are_bounded():
    app = QApplication.instance() or QApplication([])
    ribbon, settings, controller = OperateRibbon(), SettingsPage(), _Controller()
    binding = RuntimeViewBinding(operate_ribbon=ribbon, settings_page=settings, controller=controller)
    assert settings.current_target_combo.currentText() == "Not identified"
    assert settings.current_target_combo.findText("CPU1") >= 0 and settings.current_target_combo.findText("CPU2") >= 0
    assert min(settings.current_tx_timeout.minimum(), settings.current_rx_timeout.minimum(), settings.current_autobaud_timeout.minimum()) == 1
    assert [ribbon.sci_baud_combo.itemText(i) for i in range(ribbon.sci_baud_combo.count())] == ["9600", "19200", "38400", "57600", "115200"]
    binding.apply_snapshot(RuntimeSnapshot())
    assert settings.current_target_combo.currentText() == "Not identified"


def test_binding_clears_finished_task_dialog_reference():
    app = QApplication.instance() or QApplication([])
    ribbon, settings, controller = OperateRibbon(), SettingsPage(), _Controller()
    binding = RuntimeViewBinding(operate_ribbon=ribbon, settings_page=settings, controller=controller)
    plan = TaskPlan(
        "task",
        "Task",
        (TaskStepPlan("step", "Step", ProgressMode.INDETERMINATE),),
        TaskConnectionRequirement.NONE,
        True,
        CompletionPolicy.REQUIRE_ACKNOWLEDGEMENT,
    )
    controller.taskStarted.emit(TaskState("task", plan, TaskPhase.RUNNING))
    dialog = binding.task_dialog
    assert dialog is not None
    dialog.finished.emit(0)
    assert binding.task_dialog is None
