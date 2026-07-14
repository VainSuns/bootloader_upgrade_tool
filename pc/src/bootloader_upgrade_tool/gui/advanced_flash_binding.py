"""Advanced Flash image selection and preparation binding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog

from .advanced_flash_models import PrepareAdvancedFlashImageRequest, PreparedAdvancedFlashImageSummary
from .runtime_models import RuntimeState, TaskFinalStatus


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    target_key: str
    selection_revision: int
    configuration_revision: int
    source_path: str


class AdvancedFlashBinding(QObject):
    def __init__(self, page, controller, backend, parent: QObject | None = None) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self._revisions = {"cpu1": 0, "cpu2": 0}
        self._pending: _OwnedTask | None = None
        self._owned: dict[str, _OwnedTask] = {}
        self._pending_edit_target: str | None = None
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(0)
        self._edit_timer.timeout.connect(self._prepare_pending_edit)

        page.cpu1_flash_image_edit.textChanged.connect(lambda _text: self._selection_changed("cpu1"))
        page.cpu2_flash_image_edit.textChanged.connect(lambda _text: self._selection_changed("cpu2"))
        page.cpu1_flash_image_edit.editingFinished.connect(lambda: self._editing_finished("cpu1"))
        page.cpu2_flash_image_edit.editingFinished.connect(lambda: self._editing_finished("cpu2"))
        page.cpu1_flash_browse_button.pressed.connect(self._cancel_pending_edit)
        page.cpu2_flash_browse_button.pressed.connect(self._cancel_pending_edit)
        page.cpu1FlashBrowseRequested.connect(lambda: self._browse("cpu1"))
        page.cpu2FlashBrowseRequested.connect(lambda: self._browse("cpu2"))
        controller.runtimeStateChanged.connect(lambda _snapshot: self._apply_enabled())
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        self._apply_enabled()

    def select_image(self, target_key: str, path: str) -> None:
        edit = self._edit(target_key)
        if edit.text() != path:
            edit.setText(path)
        self.prepare(target_key)

    def prepare(self, target_key: str):
        path = self._edit(target_key).text().strip()
        if not path:
            return None
        try:
            normalized = self._normalize(path)
        except (OSError, RuntimeError, ValueError) as exc:
            self._show({"operation": "prepare_advanced_flash_image", "status": "FAILED", "error": str(exc)})
            return None
        context = _OwnedTask(
            target_key,
            self._revisions[target_key],
            self.backend.configuration_revision,
            normalized,
        )
        request = PrepareAdvancedFlashImageRequest(
            target_key,
            normalized,
            context.selection_revision,
            context.configuration_revision,
        )
        self._pending = context
        admission = self.controller.request_task(request)
        if admission.accepted:
            self._owned.setdefault(admission.task_id, context)
        self._pending = None
        if not admission.accepted and self._context_current(context):
            self._show({"operation": "prepare_advanced_flash_image", "status": "rejected"})
        return admission

    def configuration_changed(self) -> None:
        for target_key in ("cpu1", "cpu2"):
            self._set_summary(target_key, None)
        self._apply_enabled()

    def _browse(self, target_key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.page, f"Select {target_key.upper()} Flash App Image", "", "App images (*.out *.txt)"
        )
        if path:
            self.select_image(target_key, path)

    def _editing_finished(self, target_key: str) -> None:
        self._pending_edit_target = target_key
        self._edit_timer.start()

    def _cancel_pending_edit(self) -> None:
        self._edit_timer.stop()
        self._pending_edit_target = None

    def _prepare_pending_edit(self) -> None:
        target_key = self._pending_edit_target
        self._pending_edit_target = None
        if target_key is not None:
            self.prepare(target_key)

    def _selection_changed(self, target_key: str) -> None:
        self._revisions[target_key] += 1
        self.backend.invalidate_prepared_advanced_flash_image(target_key, self._revisions[target_key])

    def _task_started(self, state) -> None:
        if self._pending is not None:
            self._owned[state.task_id] = self._pending
            self._set_summary(self._pending.target_key, None)

    def _task_finished(self, result) -> None:
        context = self._owned.pop(result.task_id, None)
        if context is None or not self._context_current(context):
            return
        if result.status is TaskFinalStatus.SUCCEEDED:
            summary = result.payload
            if type(summary) is not PreparedAdvancedFlashImageSummary or not self._summary_current(context, summary):
                return
            self._set_summary(context.target_key, summary)
            self._show({
                "operation": "prepare_advanced_flash_image",
                "target_key": context.target_key,
                "selection_revision": context.selection_revision,
                "source_path": summary.source_path,
                "entry_point": f"0x{summary.entry_point:08X}",
                "image_size_words": summary.image_size_words,
                "image_crc32": f"0x{summary.image_crc32:08X}",
            })
        elif result.status is TaskFinalStatus.FAILED:
            self._show({
                "operation": "prepare_advanced_flash_image",
                "target_key": context.target_key,
                "status": "FAILED",
                "error": result.error.code if result.error else result.message,
            })

    def _context_current(self, context: _OwnedTask) -> bool:
        try:
            current_path = self._normalize(self._edit(context.target_key).text())
        except (OSError, RuntimeError, ValueError):
            return False
        return (
            context.selection_revision == self._revisions[context.target_key]
            and context.configuration_revision == self.backend.configuration_revision
            and context.source_path == current_path
        )

    @staticmethod
    def _summary_current(context: _OwnedTask, summary: PreparedAdvancedFlashImageSummary) -> bool:
        return (
            summary.target_key == context.target_key
            and summary.selection_revision == context.selection_revision
            and summary.configuration_revision == context.configuration_revision
            and summary.source_path == context.source_path
        )

    def _apply_enabled(self) -> None:
        snapshot = self.controller.snapshot
        enabled = (
            snapshot.state in {RuntimeState.DISCONNECTED, RuntimeState.CONNECTED}
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
        )
        self.page.set_flash_image_controls_enabled(cpu1=enabled, cpu2=enabled)

    def _set_summary(self, target_key: str, summary: PreparedAdvancedFlashImageSummary | None) -> None:
        values = {
            "entry_point": f"0x{summary.entry_point:08X}" if summary else "—",
            "image_size": f"{summary.image_size_words} words" if summary else "—",
            "crc32": f"0x{summary.image_crc32:08X}" if summary else "—",
        }
        method = self.page.set_cpu1_flash_image_summary if target_key == "cpu1" else self.page.set_cpu2_flash_image_summary
        method(**values)

    def _edit(self, target_key: str):
        if target_key == "cpu1":
            return self.page.cpu1_flash_image_edit
        if target_key == "cpu2":
            return self.page.cpu2_flash_image_edit
        raise ValueError("invalid Advanced Flash target key")

    @staticmethod
    def _normalize(path: str) -> str:
        return str(Path(path.strip()).expanduser().resolve(strict=False)) if path.strip() else ""

    def _show(self, value: dict[str, object]) -> None:
        self.page.result_output.setPlainText(json.dumps(value, indent=2, sort_keys=True))


__all__ = ["AdvancedFlashBinding"]
