"""CPU1 Program-page binding for local image preparation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog

from .image_preparation_models import PreparedImageSummary, PrepareFlashImageRequest
from .pages.program_page import ProgramTargetPage
from .runtime_models import RuntimeSnapshot, RuntimeState, TaskFinalStatus, TaskState


FilePicker = Callable[[QObject], str | Path | tuple[str | Path, ...] | None]


class ProgramImageBinding(QObject):
    """Binds only the CPU1 image controls to the existing runtime controller."""

    def __init__(
        self,
        program_page: ProgramTargetPage,
        controller,
        backend,
        *,
        file_picker: FilePicker | object | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or program_page)
        if program_page.target != "cpu1":
            raise ValueError("ProgramImageBinding only supports the CPU1 Program page")
        self.page = program_page
        self.controller = controller
        self.backend = backend
        self.file_picker = file_picker
        self._selection_revision = 0
        self._last_submitted: tuple[str, int] | None = None
        self._active_task_id: str | None = None
        self._updating_view = False

        self.page.browseRequested.connect(self._on_browse_requested)
        self.page.prepareRequested.connect(self._on_prepare_requested)
        self.page.image_path_row.path_edit.textChanged.connect(self._on_path_changed)
        self.page.image_path_row.path_edit.editingFinished.connect(self._on_editing_finished)
        self.controller.runtimeStateChanged.connect(self.apply_snapshot)
        self.controller.taskStarted.connect(self._on_task_started)
        self.controller.taskFinished.connect(self._on_task_finished)
        self.apply_snapshot(self.controller.snapshot)

    @property
    def selection_revision(self) -> int:
        return self._selection_revision

    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        enabled = (
            snapshot.state is RuntimeState.DISCONNECTED
            and not snapshot.cleanup_pending
            and snapshot.active_task_id is None
        )
        self.page.set_interactions_enabled(enabled)

    def _on_path_changed(self, text: str) -> None:
        if self._updating_view:
            return
        self._selection_revision += 1
        self._last_submitted = None
        self.backend.invalidate_prepared_image_cache(self._selection_revision)
        self._set_summary(
            text,
            entry_point="—",
            image_size="—",
            crc32="—",
            parse_status="Not parsed",
            parse_state="unknown",
            details="",
        )

    def _on_browse_requested(self, target: str) -> None:
        if target != "cpu1":
            return
        selected = self._pick_file()
        if selected:
            self.page.image_path_row.path_edit.setText(str(selected))
            self._submit_current(force=False)

    def _on_editing_finished(self) -> None:
        self._submit_current(force=False)

    def _on_prepare_requested(self, target: str) -> None:
        if target == "cpu1":
            self._submit_current(force=True)

    def _submit_current(self, *, force: bool) -> None:
        text = self.page.image_path_row.path_edit.text().strip()
        if not text:
            return
        path = str(Path(text).expanduser().resolve(strict=False))
        key = (path, self._selection_revision)
        if not force and key == self._last_submitted:
            return
        self._last_submitted = key
        self._set_summary(
            text,
            entry_point="—",
            image_size="—",
            crc32="—",
            parse_status="Parsing",
            parse_state="busy",
            details=f"Parsing: {path}",
        )
        request = PrepareFlashImageRequest("cpu1", path, self._selection_revision)
        admission = self.controller.request_task(request)
        if getattr(admission, "accepted", False):
            self._active_task_id = admission.task_id
        elif self._active_task_id is None:
            self._show_failure(
                "IMAGE_PREPARATION_NOT_STARTED",
                "Image preparation was not accepted by the runtime",
            )

    def _on_task_started(self, state: TaskState) -> None:
        if state.plan.title == "Prepare CPU1 App Image":
            self._active_task_id = state.task_id

    def _on_task_finished(self, result) -> None:
        if result.task_id != self._active_task_id:
            return
        self._active_task_id = None
        summary = result.payload
        if isinstance(summary, PreparedImageSummary):
            if not self._is_current(summary.selection_revision, summary.source_path):
                return
            if result.status is TaskFinalStatus.SUCCEEDED:
                self._show_success(summary)
                return
        error = result.error
        request_revision = error.details.get("selection_revision") if error else None
        if request_revision is not None and request_revision != self._selection_revision:
            return
        if result.status is TaskFinalStatus.FAILED:
            self._show_failure(
                error.code if error else "IMAGE_PREPARATION_FAILED",
                error.message if error else result.message,
            )

    def _show_success(self, summary: PreparedImageSummary) -> None:
        current_path = self.page.image_path_row.path_edit.text()
        self._set_summary(
            current_path,
            entry_point=f"0x{summary.entry_point:08X}",
            image_size=f"{summary.image_size_words} words",
            crc32=f"0x{summary.image_crc32:08X}",
            parse_status="Parsed",
            parse_state="success",
            details=self._details_text(summary),
        )

    def _show_failure(self, code: str, message: str) -> None:
        current_path = self.page.image_path_row.path_edit.text()
        self._set_summary(
            current_path,
            entry_point="—",
            image_size="—",
            crc32="—",
            parse_status="Parse failed",
            parse_state="error",
            details=f"Code: {code}\n{message}",
        )

    def _set_summary(self, path: str, **values: str) -> None:
        self._updating_view = True
        try:
            details = values.pop("details", "")
            self.page.set_image_summary(path=path, **values)
            self.page.set_details_text(details)
        finally:
            self._updating_view = False

    def _pick_file(self) -> str | Path | None:
        picker = self.file_picker
        if picker is None:
            selected, _filter = QFileDialog.getOpenFileName(
                self.page,
                "Select CPU1 App Image",
                "",
                "App Images (*.out *.txt)",
            )
            return selected or None
        if hasattr(picker, "getOpenFileName"):
            result = picker.getOpenFileName(self.page, "Select CPU1 App Image", "", "App Images (*.out *.txt)")
        else:
            result = picker(self.page)  # type: ignore[operator]
        if isinstance(result, tuple):
            return result[0] if result else None
        return result

    def _is_current(self, revision: int, source_path: str) -> bool:
        current = str(Path(self.page.image_path_row.path_edit.text()).expanduser().resolve(strict=False))
        return revision == self._selection_revision and source_path == current

    @staticmethod
    def _details_text(summary: PreparedImageSummary) -> str:
        sectors = ", ".join(chr(ord("A") + bit) for bit in summary.image_sector_bits)
        fingerprint = summary.source_fingerprint
        lines = (
            f"Source path: {summary.source_path}",
            f"Source type: {summary.source_kind.value}",
            f"File size: {fingerprint.size_bytes} bytes",
            f"mtime_ns: {fingerprint.mtime_ns}",
            f"Entry point: 0x{summary.entry_point:08X}",
            f"App end: 0x{summary.app_end:08X}",
            f"Image sector mask: 0x{summary.image_sector_mask:08X}",
            f"Effective sector mask: 0x{summary.effective_sector_mask:08X}",
            f"Touched sectors: {sectors or '—'}",
            f"hex2000 source: {summary.hex2000_source.value}",
            f"hex2000 executable: {summary.hex2000_executable or '—'}",
        )
        return "\n".join(lines)


__all__ = ["ProgramImageBinding"]
