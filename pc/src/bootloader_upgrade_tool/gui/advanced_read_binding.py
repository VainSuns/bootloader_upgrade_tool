"""Manual current-target Advanced reads and read-only result rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
import json

from PySide6.QtCore import QObject, Signal, Slot

from .runtime_models import RuntimeSnapshot, RuntimeState, TaskFinalStatus
from .runtime_v2_models import DataFreshness, DiagnosticGroup
from .status_models import (
    DeviceInfoRequest,
    DeviceInfoStatusSnapshot,
    LastErrorRequest,
    LastErrorStatusSnapshot,
    MetadataRefreshRequest,
    MetadataStatusSnapshot,
    ProtocolInfoRequest,
    ProtocolInfoStatusSnapshot,
)


@dataclass(frozen=True, slots=True)
class _ManualTask:
    kind: str
    connection_id: str
    target_key: str


_MANUAL_PAYLOAD_TYPES = {
    "device_info": DeviceInfoStatusSnapshot,
    "protocol_info": ProtocolInfoStatusSnapshot,
    "last_error": LastErrorStatusSnapshot,
    "metadata": MetadataStatusSnapshot,
}

_COMMAND_FIELDS = {
    "device_info": "get_device_info",
    "protocol_info": "get_protocol_info",
    "last_error": "get_last_error",
    "metadata": "get_metadata_summary",
}


class AdvancedReadOnlyBinding(QObject):
    _runtime_transition_received = Signal(object)

    def __init__(
        self,
        page,
        controller,
        backend,
        *,
        manual_read_started: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self.manual_read_started = manual_read_started
        self._snapshot = controller.snapshot
        self._pending: _ManualTask | None = None
        self._owned_tasks: dict[str, _ManualTask] = {}

        page.readDeviceInfoRequested.connect(self.read_device_info)
        page.readProtocolInfoRequested.connect(self.read_protocol_info)
        page.readLastErrorRequested.connect(self.read_last_error)
        page.refreshMetadataRequested.connect(self.refresh_metadata)
        controller.runtimeStateChanged.connect(self.apply_snapshot)
        controller.taskStarted.connect(self._on_task_started)
        controller.taskFinished.connect(self._on_task_finished)
        self._runtime_transition_received.connect(self._apply_runtime_transition)
        self._runtime_v2_listener = self._receive_runtime_transition_from_backend
        backend.subscribe_runtime_v2(self._runtime_v2_listener)
        self.destroyed.connect(
            lambda _object, backend=backend, listener=self._runtime_v2_listener: backend.unsubscribe_runtime_v2(listener)
        )
        self.clear_connection_state()
        self.apply_snapshot(controller.snapshot)

    def read_device_info(self):
        return self._submit("device_info", DeviceInfoRequest)

    def read_protocol_info(self):
        return self._submit("protocol_info", ProtocolInfoRequest)

    def read_last_error(self):
        return self._submit("last_error", LastErrorRequest)

    def refresh_metadata(self):
        return self._submit("metadata", MetadataRefreshRequest)

    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        changed = _identity(self._snapshot) != _identity(snapshot)
        self._snapshot = snapshot
        if changed:
            self.clear_connection_state()
            if snapshot.connection_info is not None:
                self._initialize_identity(snapshot)
        elif (
            snapshot.state in {RuntimeState.DISCONNECTED, RuntimeState.DISCONNECTING}
            or snapshot.shutdown_requested
        ):
            self.clear_connection_state()
        self._render_runtime_v2()
        self._apply_capabilities(snapshot)

    def clear_connection_state(self) -> None:
        for name in ("target", "device", "device_id", "cpu_id", "protocol_version", "last_error"):
            self.page.set_diagnostic_value(name, "Not connected" if name == "target" else "Unknown")
        self.clear_metadata()
        self.page.set_metadata_freshness("Empty", "unknown")
        self.page.result_output.clear()
        self.page.set_read_only_controls_enabled(
            device_info=False,
            protocol_info=False,
            last_error=False,
            metadata=False,
        )

    def clear_metadata(self, text: str = "Unknown") -> None:
        self.page.set_metadata_summary(
            {name: text for name in self.page.metadata_summary_values}
        )

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self._runtime_transition_received.emit(result)

    @Slot(object)
    def _apply_runtime_transition(self, _result) -> None:
        self._render_runtime_v2()

    def _render_runtime_v2(self) -> None:
        context = self.backend.active_target_context
        runtime = self.backend.runtime_v2_snapshot
        if (
            context is None
            or not self._is_current(context.connection.connection_id, context.target_key)
        ):
            self.clear_connection_state()
            return
        metadata = runtime.metadata_state
        tooltip = self._error_text(metadata.read_error)
        freshness_text, freshness_state = {
            DataFreshness.EMPTY: ("Empty", "unknown"),
            DataFreshness.FRESH: ("Fresh", "success"),
            DataFreshness.STALE: ("Stale", "warning"),
        }[metadata.freshness]
        self.page.set_metadata_freshness(freshness_text, freshness_state, tooltip)
        if isinstance(metadata.value, MetadataStatusSnapshot):
            self._render_metadata(metadata.value, metadata.read_error)
        else:
            self.clear_metadata("Unknown")
            self._set_metadata_tooltip(metadata.read_error)
        diagnostics = runtime.diagnostics_state
        self._render_diagnostic_group(DiagnosticGroup.DEVICE_INFO, diagnostics.device_info)
        self._render_diagnostic_group(DiagnosticGroup.PROTOCOL_INFO, diagnostics.protocol_info)
        self._render_diagnostic_group(DiagnosticGroup.LAST_ERROR, diagnostics.last_error)

    def _render_diagnostic_group(self, group, state) -> None:
        suffix = " (stale)" if state.freshness is DataFreshness.STALE else ""
        value = state.value
        if group is DiagnosticGroup.DEVICE_INFO:
            info = value.device_info if isinstance(value, DeviceInfoStatusSnapshot) else None
            self.page.set_diagnostic_value("device", f"TMS320F28377D{suffix}" if info else "Unknown")
            self.page.set_diagnostic_value("device_id", f"0x{info.device_id:04X}{suffix}" if info else "Unknown")
            self.page.set_diagnostic_value("cpu_id", f"CPU{info.cpu_id}{suffix}" if info else "Unknown")
            widgets = (
                self.page.diagnostics_device_value,
                self.page.diagnostics_device_id_value,
                self.page.diagnostics_cpu_id_value,
            )
        elif group is DiagnosticGroup.PROTOCOL_INFO:
            info = value.protocol_info if isinstance(value, ProtocolInfoStatusSnapshot) else None
            self.page.set_diagnostic_value("protocol_version", f"{info.protocol_ver}{suffix}" if info else "Unknown")
            widgets = (self.page.diagnostics_protocol_version_value,)
        else:
            detail = value.last_error if isinstance(value, LastErrorStatusSnapshot) else None
            self.page.set_diagnostic_value(
                "last_error",
                f"operation={detail.operation}, stage={detail.stage}{suffix}" if detail else "Unknown",
            )
            widgets = (self.page.diagnostics_last_error_value,)
        tooltip = self._error_text(state.read_error)
        for widget in widgets:
            widget.setToolTip(tooltip)

    def _set_metadata_tooltip(self, error) -> None:
        tooltip = self._error_text(error)
        for widget in self.page.metadata_summary_values.values():
            widget.setToolTip(tooltip)

    @staticmethod
    def _error_text(error) -> str:
        return "" if error is None else f"{error.code}: {error.message} ({error.stage})"

    def _initialize_identity(self, snapshot: RuntimeSnapshot) -> None:
        info = snapshot.connection_info
        assert info is not None
        details = info.details
        device_id = details.get("device_id")
        cpu_id = details.get("cpu_id")
        protocol = details.get("protocol_ver")
        self.page.set_diagnostic_value("target", info.target_key.upper())
        self.page.set_diagnostic_value("device", "TMS320F28377D")
        self.page.set_diagnostic_value(
            "device_id", f"0x{int(device_id):04X}" if device_id is not None else "Unknown"
        )
        self.page.set_diagnostic_value(
            "cpu_id", f"CPU{int(cpu_id)}" if cpu_id is not None else "Unknown"
        )
        self.page.set_diagnostic_value(
            "protocol_version", str(protocol) if protocol is not None else "Unknown"
        )
        self.page.set_diagnostic_value("last_error", "Unknown")

    def _apply_capabilities(self, snapshot: RuntimeSnapshot) -> None:
        context = self._ready_context(snapshot)
        commands = context.profile.command_set if context is not None else None
        self.page.set_read_only_controls_enabled(
            device_info=getattr(commands, "get_device_info", None) is not None,
            protocol_info=getattr(commands, "get_protocol_info", None) is not None,
            last_error=getattr(commands, "get_last_error", None) is not None,
            metadata=getattr(commands, "get_metadata_summary", None) is not None,
        )

    def _submit(self, kind: str, request_type):
        context = self._ready_context(self.controller.snapshot)
        command = _COMMAND_FIELDS.get(kind)
        if (
            context is None
            or command is None
            or getattr(context.profile.command_set, command, None) is None
        ):
            return None
        if self.manual_read_started is not None:
            self.manual_read_started()
        task = _ManualTask(kind, context.connection.connection_id, context.target_key)
        self._pending = task
        request = request_type(context.connection.connection_id)
        admission = self.controller.request_task(request)
        if admission.accepted:
            self._owned_tasks.setdefault(admission.task_id, task)
            self._pending = None
            return admission
        self._pending = None
        self._show_rejection(kind, task, admission)
        return admission

    def _ready_context(self, snapshot: RuntimeSnapshot):
        context = self.backend.active_target_context
        info = snapshot.connection_info
        if not (
            context is not None
            and snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_task_id is None
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
            and not snapshot.shutdown_requested
            and info is not None
            and info.connection_id == context.connection.connection_id
            and info.target_key == context.target_key
            and snapshot.active_target_key == context.target_key
        ):
            return None
        return context

    def _on_task_started(self, state) -> None:
        if self._pending is not None:
            self._owned_tasks[state.task_id] = self._pending
            self._pending = None

    def _on_task_finished(self, result) -> None:
        context = self._owned_tasks.pop(result.task_id, None)
        payload = result.payload
        if context is None:
            return
        if not self._is_current(context.connection_id, context.target_key):
            return
        if result.status is not TaskFinalStatus.SUCCEEDED:
            self._render_failure(context, result)
            return
        if not self._accepts_manual_payload(context, payload):
            return
        if context.kind == "metadata":
            self._show_success("MANUAL_REFRESH", context, payload)
        elif context.kind == "device_info":
            self._show_success("MANUAL", context, payload)
        elif context.kind == "protocol_info":
            self._show_success("MANUAL", context, payload)
        elif context.kind == "last_error":
            self._show_success("MANUAL", context, payload)

    def _accepts_manual_payload(self, context: _ManualTask, payload) -> bool:
        expected_type = _MANUAL_PAYLOAD_TYPES.get(context.kind)
        return bool(
            expected_type is not None
            and type(payload) is expected_type
            and payload.connection_id == context.connection_id
            and payload.target_key == context.target_key
            and self._is_current(payload.connection_id, payload.target_key)
            and (context.kind != "metadata" or not payload.automatic)
        )

    def _render_metadata(self, snapshot: MetadataStatusSnapshot, error=None) -> None:
        raw = snapshot.raw_metadata
        self.page.set_metadata_summary(
            {
                "metadata_valid": "Valid" if snapshot.metadata_valid else "Invalid",
                "image_valid": "Valid" if snapshot.image_valid else "Unavailable",
                "image_crc32": f"0x{raw.image_crc32:08X}" if snapshot.image_valid else "Unavailable",
                "boot_attempt": f"Yes ({raw.boot_attempt_count})" if snapshot.boot_attempt_present else "No",
                "entry_point": f"0x{raw.entry_point:08X}" if snapshot.entry_point_valid else "Unavailable",
                "app_confirmed": "Yes" if snapshot.app_confirmed else "No",
            }
        )
        self._set_metadata_tooltip(error)

    def _render_failure(self, context: _ManualTask, result) -> None:
        error = result.error
        data = {
            "operation": context.kind,
            "connection_id": context.connection_id,
            "target_key": context.target_key,
            "error": _plain(error) if error is not None else {
                "code": "READ_FAILED",
                "stage": "unknown",
                "message": result.message,
                "recoverable": False,
                "disposition": "SHOW_ONLY",
                "details": {},
            },
        }
        self.page.result_output.setPlainText(json.dumps(data, indent=2, sort_keys=True))

    def _show_success(self, source: str, context: _ManualTask, payload) -> None:
        data = {
            "source": source,
            "connection_id": context.connection_id,
            "target_key": context.target_key,
            "result": _plain(payload),
            "operation_result": _plain(payload.operation_result),
        }
        self.page.result_output.setPlainText(json.dumps(data, indent=2, sort_keys=True))

    def _show_rejection(self, kind: str, context: _ManualTask, admission) -> None:
        data = {
            "operation": kind,
            "connection_id": context.connection_id,
            "target_key": context.target_key,
            "rejection": _plain(admission.rejection or admission.error),
        }
        self.page.result_output.setPlainText(json.dumps(data, indent=2, sort_keys=True))

    def _is_current(self, connection_id: str, target_key: str) -> bool:
        snapshot = self.controller.snapshot
        info = snapshot.connection_info
        context = self.backend.active_target_context
        return bool(
            context is not None
            and info is not None
            and snapshot.state not in {RuntimeState.DISCONNECTED, RuntimeState.DISCONNECTING}
            and not snapshot.shutdown_requested
            and info.connection_id == connection_id
            and info.target_key == target_key
            and snapshot.active_target_key == target_key
            and context.connection.connection_id == connection_id
            and context.target_key == target_key
        )


def _identity(snapshot: RuntimeSnapshot) -> tuple[str, str] | None:
    info = snapshot.connection_info
    return (info.connection_id, info.target_key) if info is not None else None


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    raise TypeError(f"unsupported result value: {type(value).__name__}")


__all__ = ["AdvancedReadOnlyBinding"]
