"""Manual current-target Advanced reads and read-only result rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
import json

from PySide6.QtCore import QObject

from .runtime_models import RuntimeSnapshot, RuntimeState, TaskFinalStatus
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


class AdvancedReadOnlyBinding(QObject):
    def __init__(
        self,
        page,
        controller,
        target_provider: Callable[[], object | None],
        *,
        manual_read_started: Callable[[], None] | None = None,
        manual_metadata_failed: Callable[[str], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.target_provider = target_provider
        self.manual_read_started = manual_read_started
        self.manual_metadata_failed = manual_metadata_failed
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
        self._apply_capabilities(snapshot)

    def clear_connection_state(self) -> None:
        for name in ("target", "device", "device_id", "cpu_id", "protocol_version", "last_error"):
            self.page.set_diagnostic_value(name, "Not connected" if name == "target" else "Unknown")
        self.clear_metadata()
        self.page.result_output.clear()
        self.page.set_read_only_controls_enabled(
            device_info=False,
            protocol_info=False,
            last_error=False,
            metadata=False,
        )

    def clear_metadata(self) -> None:
        self.page.set_metadata_summary(
            {name: "Unknown" for name in self.page.metadata_summary_values}
        )

    def handle_automatic_metadata_failure(self, connection_id: str, target_key: str) -> None:
        if self._is_current(connection_id, target_key):
            self.clear_metadata()

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
        profile = self.target_provider()
        clean = bool(
            snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_task_id is None
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
            and not snapshot.shutdown_requested
            and snapshot.connection_info is not None
            and snapshot.active_target_key == snapshot.connection_info.target_key
            and profile is not None
        )
        commands = getattr(profile, "command_set", None)
        self.page.set_read_only_controls_enabled(
            device_info=clean and getattr(commands, "get_device_info", None) is not None,
            protocol_info=clean and getattr(commands, "get_protocol_info", None) is not None,
            last_error=clean and getattr(commands, "get_last_error", None) is not None,
            metadata=clean and getattr(commands, "get_metadata_summary", None) is not None,
        )

    def _submit(self, kind: str, request_type):
        info = self.controller.snapshot.connection_info
        if info is None:
            return None
        if self.manual_read_started is not None:
            self.manual_read_started()
        context = _ManualTask(kind, info.connection_id, info.target_key)
        self._pending = context
        request = request_type(info.connection_id)
        admission = self.controller.request_task(request)
        if admission.accepted:
            self._owned_tasks.setdefault(admission.task_id, context)
            self._pending = None
            return admission
        self._pending = None
        self._show_rejection(kind, context, admission)
        return admission

    def _on_task_started(self, state) -> None:
        if self._pending is not None:
            self._owned_tasks[state.task_id] = self._pending
            self._pending = None

    def _on_task_finished(self, result) -> None:
        context = self._owned_tasks.pop(result.task_id, None)
        payload = result.payload
        if context is None:
            if (
                result.status is TaskFinalStatus.SUCCEEDED
                and isinstance(payload, MetadataStatusSnapshot)
                and payload.automatic
                and self._is_current(payload.connection_id, payload.target_key)
            ):
                self._render_metadata(payload)
            return
        if not self._is_current(context.connection_id, context.target_key):
            return
        if result.status is not TaskFinalStatus.SUCCEEDED:
            self._render_failure(context, result)
            return
        if isinstance(payload, MetadataStatusSnapshot) and context.kind == "metadata":
            self._render_metadata(payload)
            self._show_success("MANUAL_REFRESH", context, payload)
        elif isinstance(payload, DeviceInfoStatusSnapshot) and context.kind == "device_info":
            info = payload.device_info
            self.page.set_diagnostic_value("device", "TMS320F28377D")
            self.page.set_diagnostic_value("device_id", f"0x{info.device_id:04X}")
            self.page.set_diagnostic_value("cpu_id", f"CPU{info.cpu_id}")
            self.page.set_diagnostic_value("protocol_version", str(info.protocol_ver))
            self._show_success("MANUAL", context, payload)
        elif isinstance(payload, ProtocolInfoStatusSnapshot) and context.kind == "protocol_info":
            self.page.set_diagnostic_value("protocol_version", str(payload.protocol_info.protocol_ver))
            self._show_success("MANUAL", context, payload)
        elif isinstance(payload, LastErrorStatusSnapshot) and context.kind == "last_error":
            detail = payload.last_error
            self.page.set_diagnostic_value("last_error", f"operation={detail.operation}, stage={detail.stage}")
            self._show_success("MANUAL", context, payload)

    def _render_metadata(self, snapshot: MetadataStatusSnapshot) -> None:
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

    def _render_failure(self, context: _ManualTask, result) -> None:
        if context.kind == "metadata":
            self.clear_metadata()
            if self.manual_metadata_failed is not None:
                self.manual_metadata_failed(context.target_key)
        elif context.kind == "last_error":
            self.page.set_diagnostic_value("last_error", "Failed")
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
        return bool(
            info is not None
            and snapshot.state not in {RuntimeState.DISCONNECTED, RuntimeState.DISCONNECTING}
            and not snapshot.shutdown_requested
            and info.connection_id == connection_id
            and info.target_key == target_key
            and snapshot.active_target_key == target_key
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
