"""Advanced RAM image selection and current-target operation binding."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PySide6.QtCore import QObject

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


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    kind: str
    target_key: str
    selection_revision: int
    connection_id: str | None = None


class AdvancedRamBinding(QObject):
    def __init__(self, page, controller, backend, parent: QObject | None = None) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self._snapshot = controller.snapshot
        self._revisions = {"cpu1": 0, "cpu2": 0}
        self._summaries: dict[str, PreparedRamImageSummary] = {}
        self._pending: _OwnedTask | None = None
        self._owned: dict[str, _OwnedTask] = {}

        page.cpu1_ram_image_edit.textChanged.connect(lambda _text: self._selection_changed("cpu1"))
        page.cpu2_ram_image_edit.textChanged.connect(lambda _text: self._selection_changed("cpu2"))
        page.cpu1_ram_image_edit.editingFinished.connect(lambda: self.prepare("cpu1"))
        page.cpu2_ram_image_edit.editingFinished.connect(lambda: self.prepare("cpu2"))
        page.ramLoadRequested.connect(self.load)
        page.ramCheckCrcRequested.connect(self.check_crc)
        page.ramRunRequested.connect(self.run)
        controller.runtimeStateChanged.connect(self.apply_snapshot)
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        self.apply_snapshot(controller.snapshot)

    def select_image(self, target_key: str, path: str) -> None:
        edit = self._edit(target_key)
        if edit.text() != path:
            edit.setText(path)
        self.prepare(target_key)

    def prepare(self, target_key: str):
        path = self._edit(target_key).text().strip()
        if not path:
            return None
        context = _OwnedTask("prepare", target_key, self._revisions[target_key])
        return self._submit(context, PrepareRamImageRequest(target_key, path, context.selection_revision))

    def load(self):
        return self._submit_operation("load", LoadAdvancedRamImageRequest)

    def check_crc(self):
        return self._submit_operation("check_crc", CheckAdvancedRamCrcRequest)

    def run(self):
        return self._submit_operation("run", RunAdvancedRamImageRequest)

    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        self._snapshot = snapshot
        self._apply_enabled()

    def _selection_changed(self, target_key: str) -> None:
        self._revisions[target_key] += 1
        self._summaries.pop(target_key, None)
        self.backend.invalidate_prepared_ram_image(target_key, self._revisions[target_key])
        self._set_summary(target_key, None)
        self._apply_enabled()

    def _submit_operation(self, kind: str, request_type):
        snapshot = self.controller.snapshot
        info = snapshot.connection_info
        target_key = snapshot.active_target_key
        if info is None or target_key is None:
            return None
        context = _OwnedTask(kind, target_key, self._revisions[target_key], info.connection_id)
        return self._submit(
            context,
            request_type(info.connection_id, target_key, context.selection_revision),
        )

    def _submit(self, context: _OwnedTask, request):
        self._pending = context
        admission = self.controller.request_task(request)
        if admission.accepted:
            self._owned.setdefault(admission.task_id, context)
        self._pending = None
        if not admission.accepted and self._context_current(context):
            self._show({"operation": context.kind, "status": "rejected", "message": admission.rejection.message if admission.rejection else "Request rejected"})
        return admission

    def _task_started(self, state) -> None:
        if self._pending is not None:
            self._owned[state.task_id] = self._pending

    def _task_finished(self, result) -> None:
        context = self._owned.pop(result.task_id, None)
        if context is None or not self._context_current(context):
            return
        if result.status is TaskFinalStatus.SUCCEEDED and context.kind == "prepare":
            summary = result.payload
            if type(summary) is not PreparedRamImageSummary or not self._summary_current(context, summary):
                return
            self._summaries[context.target_key] = summary
            self._set_summary(context.target_key, summary)
            self._show({
                "operation": "prepare_ram_image",
                "target_key": context.target_key,
                "selection_revision": context.selection_revision,
                "source_path": summary.source_path,
                "entry_point": f"0x{summary.entry_point:08X}",
                "image_size_words": summary.image_size_words,
                "image_crc32": f"0x{summary.image_crc32:08X}",
            })
        elif context.kind != "prepare" and result.status in {
            TaskFinalStatus.SUCCEEDED,
            TaskFinalStatus.CANCELLED,
            TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST,
        }:
            payload = result.payload
            if type(payload) is not AdvancedRamOperationSnapshot or not self._operation_payload_current(context, payload):
                return
            self._show({
                "operation": context.kind,
                "connection_id": context.connection_id,
                "target_key": context.target_key,
                "selection_revision": context.selection_revision,
                "status": result.status.name,
                "result": operation_result_to_dict(payload.operation_result),
            })
        elif result.status is TaskFinalStatus.FAILED:
            self._show({
                "operation": context.kind,
                "connection_id": context.connection_id,
                "target_key": context.target_key,
                "selection_revision": context.selection_revision,
                "status": "FAILED",
                "error": {
                    "code": result.error.code,
                    "stage": result.error.stage,
                    "message": result.error.message,
                } if result.error else None,
            })
        self._apply_enabled()

    def _context_current(self, context: _OwnedTask) -> bool:
        if context.selection_revision != self._revisions[context.target_key]:
            return False
        if context.connection_id is None:
            return True
        info = self.controller.snapshot.connection_info
        return bool(
            info is not None
            and info.connection_id == context.connection_id
            and info.target_key == context.target_key
            and self.controller.snapshot.active_target_key == context.target_key
        )

    def _summary_current(self, context: _OwnedTask, summary: PreparedRamImageSummary) -> bool:
        try:
            selected = str(Path(self._edit(context.target_key).text()).expanduser().resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            return False
        return (
            summary.target_key == context.target_key
            and summary.selection_revision == context.selection_revision
            and summary.source_path == selected
        )

    def _operation_payload_current(self, context: _OwnedTask, payload: AdvancedRamOperationSnapshot) -> bool:
        return (
            payload.connection_id == context.connection_id
            and payload.target_key == context.target_key
            and payload.selection_revision == context.selection_revision
            and self._context_current(context)
        )

    def _apply_enabled(self) -> None:
        snapshot = self.controller.snapshot
        local_idle = snapshot.state in {RuntimeState.DISCONNECTED, RuntimeState.CONNECTED} and snapshot.active_task_id is None and not snapshot.shutdown_requested
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
        summary = self._summaries.get(target_key) if target_key else None
        cached = self.backend.prepared_ram_image_cache(target_key) if target_key else None
        valid = bool(summary is not None and cached is not None and cached[1] == summary)
        commands = getattr(profile, "command_set", None)
        self.page.set_ram_controls_enabled(
            cpu1_browse=local_idle,
            cpu2_browse=local_idle,
            load=clean and valid and all(getattr(commands, name, None) is not None for name in ("ram_load_begin", "ram_load_data", "ram_load_end")),
            check_crc=clean and valid and getattr(commands, "ram_check_crc", None) is not None,
            run=clean and valid and getattr(commands, "run_ram", None) is not None,
        )

    def _set_summary(self, target_key: str, summary: PreparedRamImageSummary | None) -> None:
        values = {
            "entry_point": f"0x{summary.entry_point:08X}" if summary else "—",
            "image_size": f"{summary.image_size_words} words" if summary else "—",
            "crc32": f"0x{summary.image_crc32:08X}" if summary else "—",
        }
        method = self.page.set_cpu1_ram_image_summary if target_key == "cpu1" else self.page.set_cpu2_ram_image_summary
        method(**values)

    def _edit(self, target_key: str):
        if target_key == "cpu1":
            return self.page.cpu1_ram_image_edit
        if target_key == "cpu2":
            return self.page.cpu2_ram_image_edit
        raise ValueError("invalid RAM target key")

    def _show(self, value: dict[str, object]) -> None:
        self.page.result_output.setPlainText(json.dumps(value, indent=2, sort_keys=True))


__all__ = ["AdvancedRamBinding"]
