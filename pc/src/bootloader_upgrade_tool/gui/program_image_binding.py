"""CPU1 Program-page binding for local image preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog

from .image_preparation_models import PreparedImageSummary, PrepareFlashImageRequest
from .pages.program_page import ProgramTargetPage
from .runtime_models import RuntimeSnapshot, RuntimeState, TaskFinalStatus


FilePicker = Callable[[QObject], str | Path | tuple[str | Path, ...] | None]


@dataclass(frozen=True, slots=True)
class _AcceptedRequest:
    task_id: str
    selection_revision: int
    source_path: str


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
        self._active_request: _AcceptedRequest | None = None
        self._updating_view = False
        self._snapshot = self.controller.snapshot
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(0)
        self._edit_timer.timeout.connect(lambda: self._submit_current(force=False))

        self.page.browseRequested.connect(self._on_browse_requested)
        self.page.prepareRequested.connect(self._on_prepare_requested)
        self.page.image_path_row.browse_button.pressed.connect(self._edit_timer.stop)
        self.page.image_path_row.path_edit.textChanged.connect(self._on_path_changed)
        self.page.image_path_row.path_edit.editingFinished.connect(self._on_editing_finished)
        self.controller.runtimeStateChanged.connect(self.apply_snapshot)
        self.controller.taskFinished.connect(self._on_task_finished)
        self.apply_snapshot(self.controller.snapshot)

    @property
    def selection_revision(self) -> int:
        return self._selection_revision

    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        clears_cache = (
            snapshot.state is RuntimeState.DISCONNECTING
            and self._snapshot.state is not RuntimeState.DISCONNECTING
        ) or (
            snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_target_key == "cpu2"
            and not (
                self._snapshot.state is RuntimeState.CONNECTED
                and self._snapshot.active_target_key == "cpu2"
            )
        )
        if clears_cache:
            self._reset_prepared_view()
        self._snapshot = snapshot
        enabled = (
            snapshot.state is RuntimeState.DISCONNECTED
            and not snapshot.cleanup_pending
            and snapshot.active_task_id is None
        )
        self.page.set_interactions_enabled(enabled)

    def _on_path_changed(self, text: str) -> None:
        if self._updating_view:
            return
        self._edit_timer.stop()
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
        self._edit_timer.stop()
        if target != "cpu1":
            return
        selected = self._pick_file()
        if selected:
            self.page.image_path_row.path_edit.setText(str(selected))
            self._submit_current(force=False)

    def _on_editing_finished(self) -> None:
        self._edit_timer.start()

    def _on_prepare_requested(self, target: str) -> None:
        if target == "cpu1":
            self._submit_current(force=True)

    def _submit_current(self, *, force: bool) -> None:
        text = self.page.image_path_row.path_edit.text().strip()
        if not text:
            return
        try:
            path = self._normalize_path(text)
        except (OSError, RuntimeError, ValueError) as exc:
            self._last_submitted = None
            self._show_failure("INVALID_IMAGE_PATH", str(exc))
            return
        key = (path, self._selection_revision)
        if not force and key == self._last_submitted:
            return
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
        if admission.accepted:
            self._last_submitted = key
            self._active_request = _AcceptedRequest(
                admission.task_id,
                self._selection_revision,
                path,
            )
            return
        self._last_submitted = None
        message = (
            admission.rejection.message
            if admission.rejection is not None
            else admission.error.message
            if admission.error is not None
            else "Image preparation was not accepted by the runtime"
        )
        self._show_failure("IMAGE_PREPARATION_NOT_STARTED", message)

    def _on_task_finished(self, result) -> None:
        active = self._active_request
        if active is None or result.task_id != active.task_id:
            return
        self._active_request = None
        try:
            is_current = self._request_is_current(active)
        except (OSError, RuntimeError, ValueError) as exc:
            if active.selection_revision == self._selection_revision:
                self._last_submitted = None
                self._show_failure("INVALID_IMAGE_PATH", str(exc))
            return
        if not is_current:
            return
        summary = result.payload
        if result.status is TaskFinalStatus.SUCCEEDED:
            if (
                isinstance(summary, PreparedImageSummary)
                and summary.selection_revision == active.selection_revision
                and summary.source_path == active.source_path
            ):
                self._show_success(summary)
                return
            self._last_submitted = None
            self.backend.invalidate_prepared_image_cache(active.selection_revision)
            self._show_failure(
                "IMAGE_PREPARATION_INVALID_RESULT",
                "Image preparation returned an invalid result",
            )
            return
        self._last_submitted = None
        error = result.error
        if result.status is TaskFinalStatus.FAILED:
            self._show_failure(
                error.code if error else "IMAGE_PREPARATION_FAILED",
                error.message if error else result.message,
            )
            return
        self._show_failure("IMAGE_PREPARATION_FAILED", result.message)

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

    def _reset_prepared_view(self) -> None:
        self._edit_timer.stop()
        self._last_submitted = None
        self._set_summary(
            self.page.image_path_row.path_edit.text(),
            entry_point="—",
            image_size="—",
            crc32="—",
            parse_status="Not parsed",
            parse_state="unknown",
            details="",
        )

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

    @staticmethod
    def _normalize_path(text: str) -> str:
        trimmed = text.strip()
        if not trimmed:
            raise ValueError("Image path must not be empty")
        return str(Path(trimmed).expanduser().resolve(strict=False))

    def _request_is_current(self, request: _AcceptedRequest) -> bool:
        current = self._normalize_path(self.page.image_path_row.path_edit.text())
        return (
            request.selection_revision == self._selection_revision
            and request.source_path == current
        )

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
