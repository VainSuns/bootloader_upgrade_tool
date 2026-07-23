"""Advanced RAM image selection and current-target operation binding."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..images.models import RamImageIdentity
from ..operations import operation_result_to_dict
from .advanced_ram_models import (
    AdvancedRamOperationSnapshot,
    AdvancedRamOperationType,
    CheckAdvancedRamCrcRequest,
    LoadAdvancedRamImageRequest,
    PrepareRamImageRequest,
    PreparedRamImageSummary,
    RunAdvancedRamImageRequest,
)
from .runtime_models import RuntimeSnapshot, RuntimeState, TaskFinalStatus
from .runtime_v2_events import RamImageChanged
from .runtime_v2_models import ImageParseStatus, RamCrcEvidence, RuntimeCpuId


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    kind: str
    target_key: str
    selection_revision: int
    connection_id: str | None = None
    expected_image_identity: RamImageIdentity | None = None
    operation_type: AdvancedRamOperationType | None = None
    expected_ram_crc_evidence: RamCrcEvidence | None = None


@dataclass(frozen=True, slots=True)
class _TargetView:
    image_edit: object
    set_summary: Callable[..., None]


class AdvancedRamBinding(QObject):
    _runtime_transition_received = Signal(object)

    def __init__(self, page, controller, backend, parent: QObject | None = None) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self._snapshot = controller.snapshot
        self._pending: _OwnedTask | None = None
        self._owned: dict[str, _OwnedTask] = {}
        self._completed_submission_ids: set[str] = set()
        self._submitting = False
        self._updating_view = False
        self._target_views = MappingProxyType(
            dict(
                zip(
                    RuntimeCpuId,
                    (
                        _TargetView(
                            page.cpu1_ram_image_edit,
                            page.set_cpu1_ram_image_summary,
                        ),
                        _TargetView(
                            page.cpu2_ram_image_edit,
                            page.set_cpu2_ram_image_summary,
                        ),
                    ),
                    strict=True,
                )
            )
        )
        self._edit_timers = MappingProxyType(
            {cpu_id: QTimer(self) for cpu_id in self._target_views}
        )
        for cpu_id, view in self._target_views.items():
            timer = self._edit_timers[cpu_id]
            timer.setSingleShot(True)
            timer.setInterval(0)
            timer.timeout.connect(
                lambda cpu_id=cpu_id: self._prepare(cpu_id, force=False)
            )
            view.image_edit.textChanged.connect(
                lambda text, cpu_id=cpu_id: self._selection_changed(cpu_id, text)
            )
            view.image_edit.editingFinished.connect(
                lambda cpu_id=cpu_id: self._editing_finished(cpu_id)
            )
        page.ramLoadRequested.connect(self.load)
        page.ramCheckCrcRequested.connect(self.check_crc)
        page.ramRunRequested.connect(self.run)
        controller.runtimeStateChanged.connect(self.apply_snapshot)
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        self._runtime_transition_received.connect(self._apply_runtime_transition)
        self._runtime_v2_listener = self._receive_runtime_transition_from_backend
        backend.subscribe_runtime_v2(self._runtime_v2_listener)
        self.destroyed.connect(
            lambda _object, backend=backend, listener=self._runtime_v2_listener: backend.unsubscribe_runtime_v2(
                listener
            )
        )
        self._render_resources()
        self.apply_snapshot(controller.snapshot)

    def select_image(self, target_key: str, path: str) -> None:
        cpu_id = RuntimeCpuId.from_target_key(target_key)
        self._edit_timers[cpu_id].stop()
        if not path:
            return
        if self._set_path(cpu_id, path):
            self._prepare(cpu_id, force=True)

    def apply_session_path(self, target_key: str, path: str) -> None:
        cpu_id = RuntimeCpuId.from_target_key(target_key)
        self._edit_timers[cpu_id].stop()
        self._set_path(cpu_id, path)

    def prepare(self, target_key: str, *, force: bool = True):
        return self._prepare(RuntimeCpuId.from_target_key(target_key), force=force)

    def _prepare(self, cpu_id: RuntimeCpuId, *, force: bool):
        if not self._local_idle():
            return None
        resource = self.backend.target_resources[cpu_id]
        if not resource.ram_image_path.strip():
            return None
        if not force and resource.ram_image_parse_status in {
            ImageParseStatus.PARSING,
            ImageParseStatus.READY,
        }:
            return None
        target_key = cpu_id.value
        try:
            path = self._normalize_path(resource.ram_image_path)
            revision = self.backend.ram_image_revision(target_key)
            self.backend.begin_ram_image_parse(target_key, path, revision)
        except Exception as exc:
            self._show_selection_error("IMAGE_PREPARATION_NOT_STARTED", exc)
            return None
        context = _OwnedTask("prepare", target_key, revision)
        request = PrepareRamImageRequest(target_key, path, revision)
        return self._submit(context, request, parse_request=True)

    def load(self):
        return self._submit_operation("load", LoadAdvancedRamImageRequest)

    def check_crc(self):
        return self._submit_operation("check_crc", CheckAdvancedRamCrcRequest)

    def run(self):
        return self._submit_operation("run", RunAdvancedRamImageRequest)

    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        self._snapshot = snapshot
        if not self._local_idle():
            for timer in self._edit_timers.values():
                timer.stop()
        self._apply_enabled()

    def _editing_finished(self, cpu_id: RuntimeCpuId) -> None:
        if self._local_idle():
            self._edit_timers[cpu_id].start()

    def _selection_changed(self, cpu_id: RuntimeCpuId, text: str) -> None:
        if self._updating_view:
            return
        self._edit_timers[cpu_id].stop()
        self._set_path(cpu_id, text)

    def _set_path(self, cpu_id: RuntimeCpuId, path: str) -> bool:
        try:
            self.backend.set_ram_image_path(cpu_id.value, path)
        except Exception as exc:
            self._render_resource(cpu_id)
            self._show_selection_error("IMAGE_SELECTION_NOT_UPDATED", exc)
            return False
        self._render_resource(cpu_id)
        return True

    def _submit_operation(self, kind: str, request_type):
        snapshot = self.controller.snapshot
        capability = self._operation_context(kind, snapshot)
        if capability is None:
            return None
        context, evidence = capability
        target_key = context.target_key
        resource = context.resource
        revision = self.backend.ram_image_revision(target_key)
        identity = resource.ram_image_summary.identity
        operation_type = {
            "load": AdvancedRamOperationType.LOAD,
            "check_crc": AdvancedRamOperationType.CHECK_CRC,
            "run": AdvancedRamOperationType.RUN,
        }[kind]
        owned = _OwnedTask(
            kind,
            target_key,
            revision,
            context.connection.connection_id,
            identity,
            operation_type,
            evidence,
        )
        request = (
            request_type(context.connection.connection_id, target_key, revision, identity, evidence)
            if request_type is RunAdvancedRamImageRequest
            else request_type(
                context.connection.connection_id,
                target_key,
                self._normalize_path(resource.ram_image_path),
                revision,
                self.backend.configuration_revision,
                identity,
            )
        )
        return self._submit(owned, request)

    def _submit(self, context: _OwnedTask, request, *, parse_request: bool = False):
        self._pending = context
        self._submitting = True
        try:
            admission = self.controller.request_task(request)
        except Exception as exc:
            self._submitting = False
            self._pending = None
            message = str(exc) or type(exc).__name__
            if parse_request:
                state_update_error = self._fail_parse_safely(
                    context, request, "IMAGE_PREPARATION_NOT_STARTED", message
                )
                self._show_prepare_failure(
                    "IMAGE_PREPARATION_NOT_STARTED",
                    "prepare_ram_image",
                    message,
                    state_update_error=state_update_error,
                )
            else:
                self._show_operation_submission_failure(
                    context.kind,
                    "FAILED",
                    "RAM_OPERATION_NOT_STARTED",
                    context.kind,
                    message,
                )
            return None
        self._submitting = False
        if admission.accepted:
            if admission.task_id in self._completed_submission_ids:
                self._completed_submission_ids.remove(admission.task_id)
            else:
                self._owned.setdefault(admission.task_id, context)
        self._pending = None
        if not admission.accepted and self._context_current(context):
            if parse_request:
                if admission.error is not None:
                    code = admission.error.code
                    stage = admission.error.stage
                    message = admission.error.message
                    details = dict(admission.error.details)
                    failure_code = code
                elif admission.rejection is not None:
                    code = admission.rejection.code.name
                    stage = "prepare_ram_image"
                    message = admission.rejection.message
                    details = None
                    failure_code = "IMAGE_PREPARATION_NOT_STARTED"
                else:
                    code = failure_code = "IMAGE_PREPARATION_NOT_STARTED"
                    stage = "prepare_ram_image"
                    message = "Request rejected"
                    details = None
                state_update_error = self._fail_parse_safely(
                    context, request, failure_code, message
                )
                self._show_prepare_failure(
                    code,
                    stage,
                    message,
                    details=details,
                    state_update_error=state_update_error,
                )
            elif admission.error is not None:
                self._show_operation_submission_failure(
                    context.kind,
                    "FAILED",
                    admission.error.code,
                    admission.error.stage,
                    admission.error.message,
                    details=dict(admission.error.details),
                )
            elif admission.rejection is not None:
                self._show_operation_submission_failure(
                    context.kind,
                    "REJECTED",
                    admission.rejection.code.name,
                    context.kind,
                    admission.rejection.message,
                )
            else:
                self._show_operation_submission_failure(
                    context.kind,
                    "REJECTED",
                    "RAM_OPERATION_NOT_STARTED",
                    context.kind,
                    "Request rejected",
                )
        return admission

    def _task_started(self, state) -> None:
        if self._pending is not None:
            self._owned[state.task_id] = self._pending

    def _task_finished(self, result) -> None:
        context = self._owned.pop(result.task_id, None)
        if context is None:
            return
        if self._submitting:
            self._completed_submission_ids.add(result.task_id)
        if not self._context_current(context):
            return
        if result.status is TaskFinalStatus.SUCCEEDED and context.kind == "prepare":
            summary = result.payload
            if type(summary) is not PreparedRamImageSummary or not self._summary_current(
                context, summary
            ):
                return
            self._show(
                {
                    "operation": "prepare_ram_image",
                    "target_key": context.target_key,
                    "selection_revision": context.selection_revision,
                    "source_path": summary.source_path,
                    "entry_point": f"0x{summary.entry_point:08X}",
                    "image_size_words": summary.image_size_words,
                    "image_crc32": f"0x{summary.image_crc32:08X}",
                }
            )
        elif context.kind != "prepare" and result.status in {
            TaskFinalStatus.SUCCEEDED,
            TaskFinalStatus.CANCELLED,
            TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST,
        }:
            payload = result.payload
            if type(payload) is not AdvancedRamOperationSnapshot or not self._operation_payload_current(
                context, payload
            ):
                return
            self._show(
                {
                    "operation": context.kind,
                    "connection_id": context.connection_id,
                    "target_key": context.target_key,
                    "selection_revision": context.selection_revision,
                    "status": result.status.name,
                    "result": operation_result_to_dict(payload.operation_result),
                }
            )
        elif result.status is TaskFinalStatus.FAILED:
            self._show(
                {
                    "operation": context.kind,
                    "connection_id": context.connection_id,
                    "target_key": context.target_key,
                    "selection_revision": context.selection_revision,
                    "status": "FAILED",
                    "error": {
                        "code": result.error.code,
                        "stage": result.error.stage,
                        "message": result.error.message,
                    }
                    if result.error
                    else None,
                }
            )
        self._apply_enabled()

    def _context_current(self, context: _OwnedTask) -> bool:
        if context.selection_revision != self.backend.ram_image_revision(context.target_key):
            return False
        if context.connection_id is None:
            return True
        snapshot = self.controller.snapshot
        if (
            snapshot.state is RuntimeState.DISCONNECTED
            and snapshot.active_task_id is None
            and snapshot.connection_info is None
            and snapshot.active_target_key is None
            and not snapshot.cleanup_pending
        ):
            return True
        info = snapshot.connection_info
        return bool(
            info is not None
            and info.connection_id == context.connection_id
            and info.target_key == context.target_key
            and snapshot.active_target_key == context.target_key
        )

    def _summary_current(self, context: _OwnedTask, summary: PreparedRamImageSummary) -> bool:
        resource = self.backend.target_resources[
            RuntimeCpuId.from_target_key(context.target_key)
        ]
        try:
            selected = self._normalize_path(resource.ram_image_path)
        except (OSError, RuntimeError, ValueError):
            return False
        return (
            summary.target_key == context.target_key
            and summary.selection_revision == context.selection_revision
            and summary.source_path == selected
            and resource.ram_image_parse_status is ImageParseStatus.READY
        )

    def _operation_payload_current(
        self, context: _OwnedTask, payload: AdvancedRamOperationSnapshot
    ) -> bool:
        resource = self.backend.target_resources[
            RuntimeCpuId.from_target_key(context.target_key)
        ]
        return (
            payload.connection_id == context.connection_id
            and payload.target_key == context.target_key
            and payload.selection_revision == context.selection_revision
            and payload.operation_type is context.operation_type
            and payload.image_identity == context.expected_image_identity
            and (
                payload.ram_crc_evidence == context.expected_ram_crc_evidence
                if context.operation_type is AdvancedRamOperationType.RUN
                else payload.ram_crc_evidence is None
            )
            and self._context_current(context)
            and resource.ram_image_parse_status is ImageParseStatus.READY
            and resource.ram_image_summary is not None
            and resource.ram_image_summary.identity == context.expected_image_identity
        )

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self._runtime_transition_received.emit(result)

    @Slot(object)
    def _apply_runtime_transition(self, result) -> None:
        cpu_ids = {
            event.cpu_id
            for event in (result.source_event, *result.derived_events)
            if isinstance(event, RamImageChanged)
        }
        for cpu_id in cpu_ids:
            resource = result.snapshot.target_resources[cpu_id]
            if resource == self.backend.target_resources[cpu_id]:
                self._render_resource(cpu_id, resource)
        self._apply_enabled()

    def _render_resources(self) -> None:
        for cpu_id in RuntimeCpuId:
            self._render_resource(cpu_id)

    def _render_resource(self, cpu_id: RuntimeCpuId, resource=None) -> None:
        resource = resource or self.backend.target_resources[cpu_id]
        view = self._target_views[cpu_id]
        identity = (
            resource.ram_image_summary.identity
            if resource.ram_image_parse_status is ImageParseStatus.READY
            and resource.ram_image_summary is not None
            else None
        )
        self._updating_view = True
        blocked = view.image_edit.blockSignals(True)
        try:
            view.image_edit.setText(resource.ram_image_path)
        finally:
            view.image_edit.blockSignals(blocked)
            self._updating_view = False
        view.set_summary(
            entry_point=f"0x{identity.entry_point:08X}" if identity else "—",
            image_size=f"{identity.total_words} words" if identity else "—",
            crc32=f"0x{identity.image_crc32:08X}" if identity else "—",
        )

    def _apply_enabled(self) -> None:
        local_idle = self._local_idle()
        self.page.set_ram_controls_enabled(
            cpu1_browse=local_idle,
            cpu2_browse=local_idle,
            load=self._operation_context("load") is not None,
            check_crc=self._operation_context("check_crc") is not None,
            run=self._operation_context("run") is not None,
        )

    def _connected_ram_context(self, snapshot):
        context = self.backend.active_target_context
        info = snapshot.connection_info
        if (
            snapshot.state is not RuntimeState.CONNECTED
            or snapshot.active_task_id is not None
            or snapshot.shutdown_requested
            or snapshot.cleanup_pending
            or snapshot.connection_suspect
            or snapshot.disconnect_decision_pending
            or info is None
            or context is None
            or context.connection.connection_id != info.connection_id
            or context.target_key != info.target_key
            or context.target_key != snapshot.active_target_key
            or context.connection.cpu_id is not context.cpu_id
            or RuntimeCpuId.from_target_key(info.target_key) is not context.cpu_id
            or context.resource.ram_image_parse_status is not ImageParseStatus.READY
            or context.resource.ram_image_summary is None
            or not context.resource.ram_image_path.strip()
        ):
            return None
        return context

    def _operation_context(self, kind: str, snapshot=None):
        snapshot = snapshot or self.controller.snapshot
        context = self._connected_ram_context(snapshot)
        if context is None:
            return None
        fields = {
            "load": ("ram_load_begin", "ram_load_data", "ram_load_end"),
            "check_crc": ("ram_check_crc",),
            "run": ("run_ram",),
        }[kind]
        if any(getattr(context.profile.command_set, field) is None for field in fields):
            return None
        evidence = self._current_run_evidence(snapshot, context) if kind == "run" else None
        return None if kind == "run" and evidence is None else (context, evidence)

    def _current_run_evidence(self, snapshot, context=None):
        context = context or self._connected_ram_context(snapshot)
        if context is None:
            return None
        cpu_id = context.cpu_id
        resource = context.resource
        target_key = context.target_key
        evidence = resource.ram_crc_evidence
        connection = context.connection
        identity = resource.ram_image_summary.identity if resource.ram_image_summary else None
        if not (
            snapshot.active_target_key == target_key
            and snapshot.connection_info.target_key == target_key
            and type(evidence) is RamCrcEvidence
            and evidence.cpu_id is cpu_id
            and evidence.connection_generation == connection.generation
            and connection.connection_id == snapshot.connection_info.connection_id
            and connection.cpu_id is cpu_id
            and connection.generation == evidence.connection_generation
            and identity is not None
            and evidence.ram_image_identity == identity
            and evidence.entry_point == identity.entry_point
            and evidence.image_crc32 == identity.image_crc32
        ):
            return None
        return evidence

    def _local_idle(self) -> bool:
        snapshot = self.controller.snapshot
        return (
            snapshot.state in {RuntimeState.DISCONNECTED, RuntimeState.CONNECTED}
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
        )

    def _show_selection_error(self, code: str, exc: Exception) -> None:
        self._show(
            {
                "operation": "prepare_ram_image",
                "status": "FAILED",
                "error": {"code": code, "message": str(exc)},
            }
        )

    def _fail_parse_safely(self, context: _OwnedTask, request, code: str, message: str):
        try:
            self.backend.fail_ram_image_parse(
                context.target_key,
                request.source_path,
                context.selection_revision,
                code,
                message,
            )
        except Exception as exc:
            return {"exception_type": type(exc).__name__, "message": str(exc)}
        return None

    def _show_prepare_failure(
        self,
        code: str,
        stage: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
        state_update_error: dict[str, str] | None = None,
    ) -> None:
        error = {"code": code, "stage": stage, "message": message}
        if details:
            error["details"] = details
        value = {"operation": "prepare", "status": "FAILED", "error": error}
        if state_update_error is not None:
            value["state_update_error"] = state_update_error
        self._show(value)

    def _show_operation_submission_failure(
        self,
        operation: str,
        status: str,
        code: str,
        stage: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        error = {"code": code, "stage": stage, "message": message}
        if details:
            error["details"] = details
        self._show({"operation": operation, "status": status, "error": error})

    def _show(self, value: dict[str, object]) -> None:
        self.page.result_output.setPlainText(json.dumps(value, indent=2, sort_keys=True))

    @staticmethod
    def _normalize_path(text: str) -> str:
        if type(text) is not str or not text.strip():
            raise ValueError("RAM image path must not be empty")
        return str(Path(text.strip()).expanduser().resolve(strict=False))


__all__ = ["AdvancedRamBinding"]
