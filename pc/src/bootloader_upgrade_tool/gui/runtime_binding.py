"""The only binding between the final GUI views and GuiController."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QWidget

from .connection_models import SerialConnectRequest, SerialDisconnectRequest
from .runtime_models import (
    RuntimeSnapshot,
    RuntimeState,
    TaskPhase,
    TaskState,
)
from .serial_ports import SerialPortInfo, SerialPortProvider, SystemSerialPortProvider
from .ui_state import set_ui_state
from .widgets.task_dialog import TaskDialog


class RuntimeViewBinding(QObject):
    """Connects view intents to the existing controller without owning resources."""

    def __init__(
        self,
        view_or_window: QWidget | None = None,
        controller=None,
        serial_port_provider: SerialPortProvider | None = None,
        *,
        operate_ribbon=None,
        settings_page=None,
        main_window: QWidget | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        view = view_or_window
        self.main_window = main_window or (view if hasattr(view, "authorize_close") else None)
        self.operate_ribbon = operate_ribbon or getattr(view, "operate_ribbon", view)
        self.settings_page = settings_page or getattr(view, "settings_page", None)
        self.controller = controller
        self.serial_port_provider = serial_port_provider or SystemSerialPortProvider()
        self.task_dialog: TaskDialog | None = None
        self.last_port_error: str | None = None

        if self.controller is None or self.operate_ribbon is None or self.settings_page is None:
            raise ValueError("RuntimeViewBinding requires view, controller, and settings page")
        self._normal_port_tooltip = self.operate_ribbon.sci_port_combo.toolTip()
        self.operate_ribbon.connectRequested.connect(self.request_connect)
        self.operate_ribbon.disconnectRequested.connect(self.request_disconnect)
        self.operate_ribbon.sci_port_combo.popupAboutToShow.connect(self.refresh_ports)
        self.operate_ribbon.sci_port_combo.currentTextChanged.connect(self._mirror_ribbon_values)
        self.operate_ribbon.sci_baud_combo.currentTextChanged.connect(self._mirror_ribbon_values)
        self.controller.runtimeStateChanged.connect(self.apply_snapshot)
        self.controller.taskStarted.connect(self._on_task_started)
        self.controller.taskStateChanged.connect(self._on_task_state)
        self.controller.shutdownReady.connect(self._authorize_close)
        self.controller.forceExitReady.connect(self._authorize_close)
        self.apply_snapshot(self.controller.snapshot)

    def request_connect(self):
        combo = self.operate_ribbon.sci_port_combo
        try:
            request = SerialConnectRequest(
                self._resolved_port(),
                int(self.operate_ribbon.sci_baud_combo.currentText()),
                self.settings_page.current_tx_timeout.value(),
                self.settings_page.current_rx_timeout.value(),
                self.settings_page.current_autobaud_timeout.value(),
            )
        except (TypeError, ValueError) as exc:
            self.last_port_error = str(exc)
            combo.setToolTip(str(exc))
            set_ui_state(combo, "error")
            combo.lineEdit().setFocus()
            return None
        self._clear_port_error()
        return self.controller.request_connect(request)

    def request_disconnect(self):
        return self.controller.request_disconnect(SerialDisconnectRequest())

    def refresh_ports(self) -> tuple[SerialPortInfo, ...] | None:
        if self.controller.snapshot.state is not RuntimeState.DISCONNECTED:
            return None
        combo = self.operate_ribbon.sci_port_combo
        try:
            previous_text = self._resolved_port()
        except ValueError:
            previous_text = combo.currentText().strip()
            if previous_text == "Select port…":
                previous_text = ""
        try:
            ports = tuple(self.serial_port_provider.list_ports())
        except Exception as exc:
            self.last_port_error = str(exc)
            combo.setToolTip(str(exc))
            set_ui_state(combo, "error")
            combo.setEditText(previous_text)
            return None

        combo.blockSignals(True)
        try:
            combo.clear()
            for port in ports:
                index = combo.count()
                combo.addItem(port.display_name, port.device)
                combo.setItemData(index, port.tooltip, Qt.ItemDataRole.ToolTipRole)
            match = next(
                (
                    index
                    for index in range(combo.count())
                    if combo.itemData(index) == previous_text
                ),
                -1,
            )
            if match >= 0:
                combo.setCurrentIndex(match)
            else:
                combo.setCurrentIndex(-1)
                combo.setEditText(previous_text)
        finally:
            combo.blockSignals(False)
        self._clear_port_error()
        self._mirror_ribbon_values()
        return ports

    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        state = snapshot.state
        controls_enabled = state in {RuntimeState.DISCONNECTED, RuntimeState.CONNECTED}
        self.operate_ribbon.set_operation_controls_enabled(controls_enabled)
        self.operate_ribbon.set_connected(
            snapshot.active_target_key is not None
            and state not in {RuntimeState.DISCONNECTED, RuntimeState.CONNECTING}
        )
        self.settings_page.set_timeout_controls_enabled(state is RuntimeState.DISCONNECTED)
        self.settings_page.set_connection_mirror(
            self._port_for_display(),
            int(self.operate_ribbon.sci_baud_combo.currentText()),
            snapshot.active_target_key if state is not RuntimeState.DISCONNECTED else None,
        )

        if state is RuntimeState.DISCONNECTED:
            self._set_status("cpu1", "Disconnected", "disconnected")
            self._set_status("cpu2", "Disconnected", "disconnected")
        elif state is RuntimeState.CONNECTING:
            self._set_status("cpu1", "Detecting", "connecting")
            self._set_status("cpu2", "Detecting", "connecting")
        elif state is RuntimeState.ERROR:
            if snapshot.active_target_key in {"cpu1", "cpu2"}:
                active = snapshot.active_target_key
                self._set_status(active, "Runtime Error", "error")
                self._set_status("cpu2" if active == "cpu1" else "cpu1", "Not connected", "disconnected")
            else:
                self._set_status("cpu1", "Runtime Error", "error")
                self._set_status("cpu2", "Runtime Error", "error")
        else:
            active = snapshot.active_target_key
            text = {
                RuntimeState.CONNECTED: "Connected",
                RuntimeState.BUSY: "Busy",
                RuntimeState.DISCONNECTING: "Disconnecting",
            }.get(state, "Not connected")
            icon_state = "connected" if state is RuntimeState.CONNECTED else "busy"
            for target in ("cpu1", "cpu2"):
                if target == active:
                    self._set_status(target, text, icon_state)
                else:
                    self._set_status(target, "Not connected", "disconnected")

    def request_application_close(self):
        return self.controller.request_application_close()

    def _on_task_started(self, state: TaskState) -> None:
        parent = self.main_window or self.operate_ribbon.window()
        if parent is None:
            raise RuntimeError("TaskDialog requires a main window")
        if self.task_dialog is not None:
            if self.task_dialog._state.phase is not TaskPhase.FINISHED:
                raise RuntimeError("cannot replace an active TaskDialog")
            self._cleanup_task_dialog(self.task_dialog)
        self.task_dialog = TaskDialog(state, parent)
        self.task_dialog.cancelRequested.connect(self.controller.request_cancel)
        self.task_dialog.actionRequested.connect(self.controller.respond_task_action)
        self.task_dialog.finished.connect(self._on_task_dialog_finished)
        self.task_dialog.open()

    def _on_task_state(self, state: TaskState) -> None:
        if self.task_dialog is not None:
            self.task_dialog.apply_state(state)

    def _authorize_close(self, *_args) -> None:
        if self.main_window is not None and hasattr(self.main_window, "authorize_close"):
            self.main_window.authorize_close()

    def _set_status(self, target: str, text: str, state: str) -> None:
        self.operate_ribbon.set_cpu_status(target, text, state)

    def _mirror_ribbon_values(self, *_args) -> None:
        port = self._port_for_display()
        if port:
            self._clear_port_error()
        self.settings_page.set_connection_mirror(
            port,
            int(self.operate_ribbon.sci_baud_combo.currentText()),
        )

    def _resolved_port(self) -> str:
        combo = self.operate_ribbon.sci_port_combo
        text = combo.currentText().strip()
        if not text or text == "Select port…":
            raise ValueError("Select or enter a COM port")
        index = combo.currentIndex()
        if index >= 0 and text == combo.itemText(index).strip():
            device = combo.itemData(index)
            if isinstance(device, str) and device.strip():
                return device.strip()
        return text

    def _port_for_display(self) -> str:
        try:
            return self._resolved_port()
        except ValueError:
            return ""

    def _clear_port_error(self) -> None:
        self.last_port_error = None
        self.operate_ribbon.sci_port_combo.setToolTip(self._normal_port_tooltip)
        set_ui_state(self.operate_ribbon.sci_port_combo, "neutral")

    def _on_task_dialog_finished(self, _result: int) -> None:
        if self.task_dialog is not None:
            self._cleanup_task_dialog(self.task_dialog)

    def _cleanup_task_dialog(self, dialog: TaskDialog) -> None:
        for signal, slot in (
            (dialog.cancelRequested, self.controller.request_cancel),
            (dialog.actionRequested, self.controller.respond_task_action),
            (dialog.finished, self._on_task_dialog_finished),
        ):
            try:
                signal.disconnect(slot)
            except RuntimeError:
                pass
        if self.task_dialog is dialog:
            self.task_dialog = None
        dialog.deleteLater()


__all__ = ["RuntimeViewBinding"]
