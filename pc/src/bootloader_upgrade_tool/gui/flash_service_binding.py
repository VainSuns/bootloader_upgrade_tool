"""CPU1 Flash Service preparation binding for existing Settings controls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog

from .flash_service_models import PrepareFlashServiceRequest, PreparedFlashServiceSummary
from .runtime_models import RuntimeState, TaskFinalStatus


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    configuration_revision: int
    tool_configuration_revision: int
    image_path: str
    map_path: str
    descriptor_symbol: str


class FlashServiceBinding(QObject):
    def __init__(self, page, advanced_page, controller, backend, parent: QObject | None = None) -> None:
        super().__init__(parent or page)
        self.page = page
        self.advanced_page = advanced_page
        self.controller = controller
        self.backend = backend
        self._configuration_revision = 0
        self._pending: _OwnedTask | None = None
        self._owned: dict[str, _OwnedTask] = {}
        self._browse_in_progress = False

        for edit in (
            page.cpu1_service_image.path_edit,
            page.cpu1_service_map.path_edit,
            page.cpu1_descriptor_symbol,
        ):
            edit.textChanged.connect(self._configuration_changed)
            edit.editingFinished.connect(self._editing_finished)
        page.cpu1_service_image.browse_button.pressed.connect(self._begin_browse)
        page.cpu1_service_map.browse_button.pressed.connect(self._begin_browse)
        page.cpu1_service_image.browseRequested.connect(lambda: self._browse("image"))
        page.cpu1_service_map.browseRequested.connect(lambda: self._browse("map"))
        controller.runtimeStateChanged.connect(lambda _snapshot: self._apply_enabled())
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        self._apply_enabled()

    def prepare(self):
        image_path = self.page.cpu1_service_image.path_edit.text().strip()
        map_path = self.page.cpu1_service_map.path_edit.text().strip()
        if not image_path or not map_path:
            return None
        try:
            context = _OwnedTask(
                self._configuration_revision,
                self.backend.configuration_revision,
                self._normalize(image_path),
                self._normalize(map_path),
                self.page.cpu1_descriptor_symbol.text().strip(),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._show({"operation": "prepare_flash_service", "status": "FAILED", "error": str(exc)})
            return None
        request = PrepareFlashServiceRequest(
            context.image_path,
            context.map_path,
            context.descriptor_symbol,
            context.configuration_revision,
            context.tool_configuration_revision,
        )
        self._pending = context
        admission = self.controller.request_task(request)
        if admission.accepted:
            self._owned.setdefault(admission.task_id, context)
        self._pending = None
        if not admission.accepted and self._context_current(context):
            self._show({"operation": "prepare_flash_service", "status": "rejected"})
        return admission

    def tool_configuration_changed(self) -> None:
        self.page.cpu1_descriptor_address.set_value("Resolved from map/symbol; never hardcoded")
        self._apply_enabled()

    def _browse(self, kind: str) -> None:
        title = "Select CPU1 Flash Service Image" if kind == "image" else "Select CPU1 Flash Service Map"
        file_filter = "Service images (*.out *.txt)" if kind == "image" else "Map files (*.map)"
        try:
            path, _ = QFileDialog.getOpenFileName(self.page, title, "", file_filter)
        finally:
            self._browse_in_progress = False
        if path:
            row = self.page.cpu1_service_image if kind == "image" else self.page.cpu1_service_map
            row.path_edit.setText(path)
            self.prepare()

    def _begin_browse(self) -> None:
        self._browse_in_progress = True

    def _editing_finished(self) -> None:
        if not self._browse_in_progress:
            self.prepare()

    def _configuration_changed(self, _text: str) -> None:
        self._configuration_revision += 1
        self.backend.invalidate_prepared_service_image(self._configuration_revision)

    def _task_started(self, state) -> None:
        if self._pending is not None:
            self._owned[state.task_id] = self._pending
            self.page.cpu1_descriptor_address.set_value("Resolved from map/symbol; never hardcoded")

    def _task_finished(self, result) -> None:
        context = self._owned.pop(result.task_id, None)
        if context is None or not self._context_current(context):
            return
        if result.status is TaskFinalStatus.SUCCEEDED:
            summary = result.payload
            if type(summary) is not PreparedFlashServiceSummary or not self._summary_current(context, summary):
                return
            self.page.cpu1_descriptor_address.set_value(f"0x{summary.descriptor_address:08X}")
            self._show({
                "operation": "prepare_flash_service",
                "target_key": "cpu1",
                "configuration_revision": context.configuration_revision,
                "service_image_path": summary.service_image_path,
                "service_map_path": summary.service_map_path,
                "descriptor_symbol": summary.descriptor_symbol or "default",
                "descriptor_address": f"0x{summary.descriptor_address:08X}",
                "api_table_address": f"0x{summary.api_table_address:08X}",
                "crc_patch_address": f"0x{summary.crc_patch_address:08X}",
            })
        elif result.status is TaskFinalStatus.FAILED:
            self._show({
                "operation": "prepare_flash_service",
                "target_key": "cpu1",
                "status": "FAILED",
                "error": result.error.code if result.error else result.message,
            })

    def _context_current(self, context: _OwnedTask) -> bool:
        try:
            image_path = self._normalize(self.page.cpu1_service_image.path_edit.text())
            map_path = self._normalize(self.page.cpu1_service_map.path_edit.text())
        except (OSError, RuntimeError, ValueError):
            return False
        return (
            context.configuration_revision == self._configuration_revision
            and context.tool_configuration_revision == self.backend.configuration_revision
            and context.image_path == image_path
            and context.map_path == map_path
            and context.descriptor_symbol == self.page.cpu1_descriptor_symbol.text().strip()
        )

    @staticmethod
    def _summary_current(context: _OwnedTask, summary: PreparedFlashServiceSummary) -> bool:
        return (
            summary.target_key == "cpu1"
            and summary.configuration_revision == context.configuration_revision
            and summary.tool_configuration_revision == context.tool_configuration_revision
            and summary.service_image_path == context.image_path
            and summary.service_map_path == context.map_path
            and summary.descriptor_symbol == context.descriptor_symbol
        )

    def _apply_enabled(self) -> None:
        snapshot = self.controller.snapshot
        enabled = (
            snapshot.state in {RuntimeState.DISCONNECTED, RuntimeState.CONNECTED}
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
        )
        self.page.set_flash_service_controls_enabled(cpu1=enabled)

    @staticmethod
    def _normalize(path: str) -> str:
        return str(Path(path.strip()).expanduser().resolve(strict=False)) if path.strip() else ""

    def _show(self, value: dict[str, object]) -> None:
        self.advanced_page.result_output.setPlainText(json.dumps(value, indent=2, sort_keys=True))


__all__ = ["FlashServiceBinding"]
