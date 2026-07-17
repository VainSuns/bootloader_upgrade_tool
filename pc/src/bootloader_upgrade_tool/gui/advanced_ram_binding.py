"""Advanced RAM image selection and current-target operation binding."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..images.models import RamImageIdentity
from ..operations import operation_result_to_dict
from .advanced_ram_models import (
    AdvancedRamOperationSnapshot,
    CheckAdvancedRamCrcRequest,
    LoadAdvancedRamImageRequest,
    PrepareRamImageRequest,
    PreparedRamImageSummary,
    RunAdvancedRamImageRequest,
)
from .runtime_models import RuntimeSnapshot, RuntimeState, TaskFinalStatus
from .runtime_v2_events import RamImageChanged
from .runtime_v2_models import ImageParseStatus, RuntimeCpuId


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    kind: str
    target_key: str
    selection_revision: int
    connection_id: str | None = None


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
        self._edit_timers = {key: QTimer(self) for key in ("cpu1", "cpu2")}
        for key, timer in self._edit_timers.items():
            timer.setSingleShot(True)
            timer.setInterval(0)
            timer.timeout.connect(lambda key=key: self.prepare(key, force=False))

        page.cpu1_ram_image_edit.textChanged.connect(
            lambda text: self._selection_changed("cpu1", text)
        )
        page.cpu2_ram_image_edit.textChanged.connect(
            lambda text: self._selection_changed("cpu2", text)
        )
        page.cpu1_ram_image_edit.editingFinished.connect(
            lambda: self._editing_finished("cpu1")
        )
        page.cpu2_ram_image_edit.editingFinished.connect(
            lambda: self._editing_finished("cpu2")
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
        self._edit_timers[target_key].stop()
        if not path:
            return
        if self._set_path(target_key, path):
            self.prepare(target_key, force=True)

    def apply_session_path(self, target_key: str, path: str) -> None:
        self._edit_timers[target_key].stop()
        self._set_path(target_key, path)

    def prepare(self, target_key: str, *, force: bool = True):
        if not self._local_idle():
            return None
        cpu_id = RuntimeCpuId.from_target_key(target_key)
        resource = self.backend.target_resources[cpu_id]
        if not resource.ram_image_path.strip():
            return None
        if not force and resource.ram_image_parse_status in {
            ImageParseStatus.PARSING,
            ImageParseStatus.READY,
        }:
            return None
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

    def _editing_finished(self, target_key: str) -> None:
        if self._local_idle():
            self._edit_timers[target_key].start()

    def _selection_changed(self, target_key: str, text: str) -> None:
        if self._updating_view:
            return
        self._edit_timers[target_key].stop()
        self._set_path(target_key, text)

    def _set_path(self, target_key: str, path: str) -> bool:
        try:
            self.backend.set_ram_image_path(target_key, path)
        except Exception as exc:
            self._render_resource(RuntimeCpuId.from_target_key(target_key))
            self._show_selection_error("IMAGE_SELECTION_NOT_UPDATED", exc)
            return False
        self._render_resource(RuntimeCpuId.from_target_key(target_key))
        return True

    def _submit_operation(self, kind: str, request_type):
        snapshot = self.controller.snapshot
        info = snapshot.connection_info
        target_key = snapshot.active_target_key
        if info is None or target_key is None:
            return None
        revision = self.backend.ram_image_revision(target_key)
        context = _OwnedTask(kind, target_key, revision, info.connection_id)
        return self._submit(
            context, request_type(info.connection_id, target_key, revision)
        )

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
        return (
            payload.connection_id == context.connection_id
            and payload.target_key == context.target_key
            and payload.selection_revision == context.selection_revision
            and self._context_current(context)
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
        if cpu_ids:
            self._apply_enabled()

    def _render_resources(self) -> None:
        for cpu_id in RuntimeCpuId:
            self._render_resource(cpu_id)

    def _render_resource(self, cpu_id: RuntimeCpuId, resource=None) -> None:
        resource = resource or self.backend.target_resources[cpu_id]
        identity = (
            resource.ram_image_summary.identity
            if resource.ram_image_parse_status is ImageParseStatus.READY
            and resource.ram_image_summary is not None
            else None
        )
        edit = self._edit(cpu_id.value)
        self._updating_view = True
        blocked = edit.blockSignals(True)
        try:
            edit.setText(resource.ram_image_path)
        finally:
            edit.blockSignals(blocked)
            self._updating_view = False
        self._set_summary(cpu_id.value, identity)

    def _apply_enabled(self) -> None:
        snapshot = self.controller.snapshot
        local_idle = self._local_idle()
        clean = bool(
            snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_task_id is None
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
            and snapshot.connection_info is not None
            and snapshot.active_target_key == snapshot.connection_info.target_key
        )
        target_key = snapshot.active_target_key
        profile = self.backend.active_target
        valid = False
        if target_key is not None:
            cpu_id = RuntimeCpuId.from_target_key(target_key)
            resource = self.backend.target_resources[cpu_id]
            cached = self.backend.prepared_ram_image_cache(target_key)
            revision = self.backend.ram_image_revision(target_key)
            if (
                resource.ram_image_parse_status is ImageParseStatus.READY
                and resource.ram_image_summary is not None
                and cached is not None
            ):
                task_summary = cached[1]
                valid = (
                    task_summary.selection_revision == revision
                    and resource.ram_image_summary.identity
                    == RamImageIdentity(
                        task_summary.entry_point,
                        task_summary.image_size_words,
                        task_summary.image_crc32,
                    )
                )
        commands = getattr(profile, "command_set", None)
        self.page.set_ram_controls_enabled(
            cpu1_browse=local_idle,
            cpu2_browse=local_idle,
            load=clean
            and valid
            and all(
                getattr(commands, name, None) is not None
                for name in ("ram_load_begin", "ram_load_data", "ram_load_end")
            ),
            check_crc=clean
            and valid
            and getattr(commands, "ram_check_crc", None) is not None,
            run=clean and valid and getattr(commands, "run_ram", None) is not None,
        )

    def _local_idle(self) -> bool:
        snapshot = self.controller.snapshot
        return (
            snapshot.state in {RuntimeState.DISCONNECTED, RuntimeState.CONNECTED}
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
        )

    def _set_summary(self, target_key: str, identity: RamImageIdentity | None) -> None:
        values = {
            "entry_point": f"0x{identity.entry_point:08X}" if identity else "—",
            "image_size": f"{identity.total_words} words" if identity else "—",
            "crc32": f"0x{identity.image_crc32:08X}" if identity else "—",
        }
        method = (
            self.page.set_cpu1_ram_image_summary
            if target_key == "cpu1"
            else self.page.set_cpu2_ram_image_summary
        )
        method(**values)

    def _edit(self, target_key: str):
        if target_key == "cpu1":
            return self.page.cpu1_ram_image_edit
        if target_key == "cpu2":
            return self.page.cpu2_ram_image_edit
        raise ValueError("invalid RAM target key")

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
