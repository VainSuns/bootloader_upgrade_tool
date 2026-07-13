"""The only binding between the final GUI views and GuiController."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QWidget

from .connection_models import SerialConnectRequest, SerialDisconnectRequest
from .runtime_models import (
    TaskFinalStatus,
    RuntimeSnapshot,
    RuntimeState,
    TaskPhase,
    TaskState,
)
from .serial_ports import SerialPortInfo, SerialPortProvider, SystemSerialPortProvider
from .status_models import (
    DeviceInfoRequest,
    DeviceInfoStatusSnapshot,
    LastErrorRequest,
    LastErrorStatusSnapshot,
    LoadedImageMatch,
    MetadataRefreshRequest,
    MetadataStatusSnapshot,
    ProtocolInfoRequest,
    ProtocolInfoStatusSnapshot,
)
from .ui_state import set_ui_state
from .widgets.task_dialog import TaskDialog

from ..operations import operation_result_to_dict


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
        self.program_page = getattr(view, "program_cpu1_page", None)
        self.advanced_page = getattr(view, "advanced_page", None)
        self.controller = controller
        self.serial_port_provider = serial_port_provider or SystemSerialPortProvider()
        self.task_dialog: TaskDialog | None = None
        self.last_port_error: str | None = None
        self._snapshot = self.controller.snapshot if self.controller is not None else RuntimeSnapshot()
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setSingleShot(True)
        self._auto_refresh_timer.timeout.connect(self._submit_auto_refresh)
        self._auto_refresh_pending = False
        self._auto_refresh_connection_id: str | None = None
        self._auto_refresh_task_id: str | None = None

        if self.controller is None or self.operate_ribbon is None or self.settings_page is None:
            raise ValueError("RuntimeViewBinding requires view, controller, and settings page")
        self._normal_port_tooltip = self.operate_ribbon.sci_port_combo.toolTip()
        self.operate_ribbon.connectRequested.connect(self.request_connect)
        self.operate_ribbon.disconnectRequested.connect(self.request_disconnect)
        self.operate_ribbon.sci_port_combo.popupAboutToShow.connect(self.refresh_ports)
        self.operate_ribbon.sci_port_combo.currentTextChanged.connect(self._on_port_text_changed)
        self.operate_ribbon.sci_baud_combo.currentTextChanged.connect(self._on_baud_changed)
        self.controller.runtimeStateChanged.connect(self.apply_snapshot)
        self.controller.taskStarted.connect(self._on_task_started)
        self.controller.taskStateChanged.connect(self._on_task_state)
        task_finished = getattr(self.controller, "taskFinished", None)
        if task_finished is not None:
            task_finished.connect(self._on_task_finished)
        self.controller.shutdownReady.connect(self._authorize_close)
        self.controller.forceExitReady.connect(self._authorize_close)
        if self.advanced_page is not None:
            self.advanced_page.statusRequested.connect(self.request_status)
        self.apply_snapshot(self.controller.snapshot)

    def request_connect(self):
        self._cancel_auto_refresh()
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
        return self.controller.request_connect(request)

    def request_disconnect(self):
        self._cancel_auto_refresh()
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
            combo.blockSignals(True)
            try:
                combo.setEditText(previous_text)
            finally:
                combo.blockSignals(False)
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
        previous = self._snapshot
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

        if self.advanced_page is not None:
            connected = state is RuntimeState.CONNECTED and snapshot.active_target_key is not None
            target_text = (
                snapshot.active_target_key.upper() + " / TMS320F28377D"
                if connected
                else "Not connected"
            )
            self.advanced_page.set_connected_target(target_text)
            self.advanced_page.set_status_controls_enabled(connected)

        connection_changed = (
            previous.active_target_key != snapshot.active_target_key
            or previous.connection_info is None
            or snapshot.connection_info is None
            or previous.connection_info.connection_id != snapshot.connection_info.connection_id
        )
        new_cpu1_connection = (
            state is RuntimeState.CONNECTED
            and snapshot.active_target_key == "cpu1"
            and connection_changed
        )
        self._snapshot = snapshot
        if new_cpu1_connection:
            self._schedule_auto_refresh()
        elif state is not RuntimeState.CONNECTED or snapshot.active_target_key != "cpu1":
            self._cancel_auto_refresh()

    def request_application_close(self):
        self._cancel_auto_refresh()
        return self.controller.request_application_close()

    def request_status(self, operation: str):
        self._cancel_auto_refresh()
        info = self._snapshot.connection_info
        if info is None:
            return None
        if operation == "get_device_info":
            request = DeviceInfoRequest(info.connection_id)
        elif operation == "get_protocol_info":
            request = ProtocolInfoRequest(info.connection_id)
        elif operation == "get_last_error":
            request = LastErrorRequest(info.connection_id)
        elif operation == "get_metadata_summary":
            request = MetadataRefreshRequest(info.connection_id)
        else:
            raise ValueError(f"unsupported status operation: {operation!r}")
        return self.controller.request_task(request)

    def _on_task_started(self, state: TaskState) -> None:
        self._cancel_auto_refresh()
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

    def _on_task_finished(self, result) -> None:
        if self._auto_refresh_task_id == result.task_id:
            self._auto_refresh_task_id = None
        if result.status is not TaskFinalStatus.SUCCEEDED:
            return
        snapshot = result.payload
        if not isinstance(
            snapshot,
            (
                MetadataStatusSnapshot,
                DeviceInfoStatusSnapshot,
                ProtocolInfoStatusSnapshot,
                LastErrorStatusSnapshot,
            ),
        ):
            return
        current = self._snapshot.connection_info
        if (
            current is None
            or snapshot.connection_id != current.connection_id
            or snapshot.target_key != current.target_key
        ):
            return
        self._render_status_snapshot(snapshot)

    def _schedule_auto_refresh(self) -> None:
        self._cancel_auto_refresh()
        info = self._snapshot.connection_info
        if info is None:
            return
        self._auto_refresh_pending = True
        self._auto_refresh_connection_id = info.connection_id
        self._auto_refresh_timer.start(0)

    def _cancel_auto_refresh(self) -> None:
        self._auto_refresh_timer.stop()
        self._auto_refresh_pending = False
        self._auto_refresh_connection_id = None

    def _submit_auto_refresh(self) -> None:
        if not self._auto_refresh_pending:
            return
        connection_id = self._auto_refresh_connection_id
        self._auto_refresh_pending = False
        self._auto_refresh_connection_id = None
        if (
            self._snapshot.state is not RuntimeState.CONNECTED
            or self._snapshot.active_target_key != "cpu1"
            or self._snapshot.active_task_id is not None
            or self._snapshot.connection_info is None
            or self._snapshot.connection_info.connection_id != connection_id
        ):
            return
        admission = self.controller.request_task(MetadataRefreshRequest(connection_id, automatic=True))
        if admission.accepted:
            self._auto_refresh_task_id = admission.task_id

    def _render_status_snapshot(self, snapshot) -> None:
        result = snapshot.operation_result
        if self.advanced_page is not None:
            self.advanced_page.result_output.setPlainText(
                json.dumps(operation_result_to_dict(result), indent=2, sort_keys=True)
            )
        if isinstance(snapshot, MetadataStatusSnapshot):
            self._render_metadata_summary(snapshot)
        elif isinstance(snapshot, DeviceInfoStatusSnapshot) and self.advanced_page is not None:
            info = snapshot.device_info
            self.advanced_page.set_diagnostic_value("device", "TMS320F28377D")
            self.advanced_page.set_diagnostic_value("device_id", f"0x{info.device_id:04X}")
            self.advanced_page.set_diagnostic_value("cpu_id", f"CPU{info.cpu_id}")
            self.advanced_page.set_diagnostic_value("protocol_version", str(info.protocol_ver))
        elif isinstance(snapshot, ProtocolInfoStatusSnapshot) and self.advanced_page is not None:
            self.advanced_page.set_diagnostic_value("protocol_version", str(snapshot.protocol_info.protocol_ver))
        elif isinstance(snapshot, LastErrorStatusSnapshot) and self.advanced_page is not None:
            detail = snapshot.last_error
            self.advanced_page.set_diagnostic_value(
                "last_error",
                f"operation={detail.operation}, stage={detail.stage}",
            )

    def _render_metadata_summary(self, snapshot: MetadataStatusSnapshot) -> None:
        raw = snapshot.raw_metadata
        loaded_text, loaded_state = {
            LoadedImageMatch.MATCH: ("Yes", "success"),
            LoadedImageMatch.MISMATCH: ("No", "warning"),
            LoadedImageMatch.NO_PREPARED_IMAGE: ("Unknown", "unknown"),
            LoadedImageMatch.NO_VALID_TARGET_IMAGE: ("Unknown", "unknown"),
        }[snapshot.loaded_image_match]
        statuses = {
            "metadata_valid": ("Valid" if snapshot.metadata_valid else "Invalid", "success" if snapshot.metadata_valid else "warning"),
            "entry_point_valid": ("Valid" if snapshot.entry_point_valid else "Invalid", "success" if snapshot.entry_point_valid else "warning"),
            "image_valid": ("Valid" if snapshot.image_valid else "Unavailable", "success" if snapshot.image_valid else "warning"),
            "flash_app_crc32": (
                f"0x{raw.image_crc32:08X}" if snapshot.image_valid else "Unavailable",
                "success" if snapshot.image_valid else "warning",
            ),
            "boot_attempt": (
                f"Yes ({raw.boot_attempt_count}/{raw.boot_attempt_limit})" if snapshot.boot_attempt_present else "No",
                "success" if snapshot.boot_attempt_present else "neutral",
            ),
            "loaded_image_matches": (loaded_text, loaded_state),
            "app_confirmed": ("Yes" if snapshot.app_confirmed else "No", "success" if snapshot.app_confirmed else "neutral"),
            "confirmed_bootable": (
                "Yes" if snapshot.confirmed_bootable else "No",
                "success" if snapshot.confirmed_bootable else "warning",
            ),
        }
        if self.program_page is not None:
            for key, (text, state) in statuses.items():
                self.program_page.set_status(key, text, state)
        if self.advanced_page is not None:
            self.advanced_page.set_metadata_summary(
                {
                    "metadata_valid": "Valid" if snapshot.metadata_valid else "Invalid",
                    "image_valid": "Valid" if snapshot.image_valid else "Unavailable",
                    "image_crc32": statuses["flash_app_crc32"][0],
                    "boot_attempt": statuses["boot_attempt"][0],
                    "entry_point": f"0x{raw.entry_point:08X}" if snapshot.entry_point_valid else "Unavailable",
                    "app_confirmed": statuses["app_confirmed"][0],
                }
            )

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
        self.settings_page.set_connection_mirror(
            port,
            int(self.operate_ribbon.sci_baud_combo.currentText()),
        )

    def _on_port_text_changed(self, *_args) -> None:
        if self._port_for_display():
            self._clear_port_error()
        else:
            self._sync_current_port_tooltip()
        self._mirror_ribbon_values()

    def _on_baud_changed(self, *_args) -> None:
        self._mirror_ribbon_values()

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
        set_ui_state(self.operate_ribbon.sci_port_combo, "neutral")
        self._sync_current_port_tooltip()

    def _sync_current_port_tooltip(self) -> None:
        if self.last_port_error is not None:
            return
        combo = self.operate_ribbon.sci_port_combo
        tooltip = None
        index = combo.currentIndex()
        if index >= 0 and combo.currentText().strip() == combo.itemText(index).strip():
            tooltip = combo.itemData(index, Qt.ItemDataRole.ToolTipRole)
        combo.setToolTip(tooltip or self._normal_port_tooltip)

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
