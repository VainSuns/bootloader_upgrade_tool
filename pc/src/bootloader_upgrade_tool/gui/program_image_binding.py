"""Generic Program-page binding for Backend-owned local image preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from .image_preparation_models import PreparedImageSummary, PrepareFlashImageRequest
from .pages.program_page import ProgramTargetPage
from .runtime_models import RuntimeSnapshot, RuntimeState, TaskFinalStatus
from .runtime_v2_models import ImageParseStatus, RuntimeCpuId


FilePicker = Callable[[QObject], str | Path | tuple[str | Path, ...] | None]


@dataclass(frozen=True, slots=True)
class _Submission:
    task_id: str | None
    selection_revision: int
    source_path: str


class ProgramImageBinding(QObject):
    _runtime_transition_received = Signal(object)

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
        self.page = program_page
        self.controller = controller
        self.backend = backend
        self.cpu_id = RuntimeCpuId.from_target_key(program_page.target)
        self.file_picker = file_picker
        self._pending_submission: _Submission | None = None
        self._active_request: _Submission | None = None
        self._completed_submission_ids: set[str] = set()
        self._request_in_progress = False
        self._updating_view = False
        self._details = ""
        self._details_correlation: tuple[int, str] | None = None
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
        self.controller.taskStarted.connect(self._on_task_started)
        self.controller.taskFinished.connect(self._on_task_finished)
        self._runtime_transition_received.connect(self._apply_runtime_transition)
        self._runtime_v2_listener = self._receive_runtime_transition_from_backend
        self.backend.subscribe_runtime_v2(self._runtime_v2_listener)
        self.destroyed.connect(
            lambda _object, backend=backend, listener=self._runtime_v2_listener: backend.unsubscribe_runtime_v2(
                listener
            )
        )
        self._render_resource()
        self.apply_snapshot(self.controller.snapshot)

    @property
    def selection_revision(self) -> int:
        return self.backend.program_image_revision(self.page.target)

    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        self._snapshot = snapshot
        enabled = self._preparation_allowed()
        if not enabled:
            self._edit_timer.stop()
        self.page.set_interactions_enabled(enabled)

    def apply_session_path(self, path: str) -> None:
        self._edit_timer.stop()
        self._clear_task_correlation()
        self._details = ""
        self.backend.set_program_image_path(self.page.target, path)

    def prepare_current(self, *, force: bool = True):
        return self._submit_current(force=force)

    def _on_path_changed(self, text: str) -> None:
        if self._updating_view:
            return
        self._edit_timer.stop()
        self._details = ""
        self._details_correlation = None
        try:
            self.backend.set_program_image_path(self.page.target, text)
        except Exception as exc:
            self._details = f"Code: IMAGE_SELECTION_NOT_UPDATED\n{exc}"
            self._render_resource()

    def _on_browse_requested(self, target: str) -> None:
        self._edit_timer.stop()
        if target != self.page.target or not self._preparation_allowed():
            return
        selected = self._pick_file()
        if selected:
            try:
                self.backend.set_program_image_path(self.page.target, str(selected))
            except Exception as exc:
                self._details = f"Code: IMAGE_SELECTION_NOT_UPDATED\n{exc}"
                self._details_correlation = None
                self._render_resource()
            else:
                self._submit_current(force=True)

    def _on_editing_finished(self) -> None:
        if self._preparation_allowed():
            self._edit_timer.start()
        else:
            self._edit_timer.stop()

    def _on_prepare_requested(self, target: str) -> None:
        if target == self.page.target and self._preparation_allowed():
            self._submit_current(force=True)

    def _submit_current(self, *, force: bool):
        self._edit_timer.stop()
        if not self._preparation_allowed():
            return None
        resource = self.backend.target_resources[self.cpu_id]
        if not resource.program_image_path.strip():
            return None
        if not force and resource.program_image_parse_status in {
            ImageParseStatus.PARSING,
            ImageParseStatus.READY,
        }:
            return None
        try:
            path = self._normalize_path(resource.program_image_path)
            revision = self.selection_revision
            self._details = ""
            self._details_correlation = None
            self.backend.begin_program_image_parse(self.page.target, path, revision)
        except Exception as exc:
            self._details = f"Code: IMAGE_PREPARATION_NOT_STARTED\n{exc}"
            self._render_resource()
            return None

        request = PrepareFlashImageRequest(self.page.target, path, revision)
        submission = _Submission(None, revision, path)
        self._pending_submission = submission
        self._request_in_progress = True
        try:
            admission = self.controller.request_task(request)
        except Exception as exc:
            self._request_in_progress = False
            self._pending_submission = None
            self._active_request = None
            self.backend.fail_program_image_parse(
                self.page.target, path, revision, "IMAGE_PREPARATION_NOT_STARTED", str(exc)
            )
            return None
        self._request_in_progress = False
        if admission.accepted:
            if admission.task_id in self._completed_submission_ids:
                self._completed_submission_ids.remove(admission.task_id)
                return admission
            if self._pending_submission is submission:
                self._pending_submission = None
                self._active_request = _Submission(admission.task_id, revision, path)
            return admission

        self._pending_submission = None
        self._active_request = None
        message = (
            admission.rejection.message
            if admission.rejection is not None
            else admission.error.message
            if admission.error is not None
            else "Image preparation was not accepted by the runtime"
        )
        self.backend.fail_program_image_parse(
            self.page.target, path, revision, "IMAGE_PREPARATION_NOT_STARTED", message
        )
        return admission

    def _on_task_started(self, state) -> None:
        pending = self._pending_submission
        if pending is not None:
            self._pending_submission = None
            self._active_request = _Submission(
                state.task_id, pending.selection_revision, pending.source_path
            )

    def _on_task_finished(self, result) -> None:
        active = self._active_request
        if active is None:
            pending = self._pending_submission
            if pending is None:
                return
            active = _Submission(result.task_id, pending.selection_revision, pending.source_path)
            self._pending_submission = None
        elif result.task_id != active.task_id:
            return
        if self._request_in_progress:
            self._completed_submission_ids.add(result.task_id)
        self._active_request = None
        if not self._request_is_current(active):
            return
        summary = result.payload
        if (
            result.status is TaskFinalStatus.SUCCEEDED
            and isinstance(summary, PreparedImageSummary)
            and summary.target_key == self.page.target
            and summary.selection_revision == active.selection_revision
            and summary.source_path == active.source_path
        ):
            self._details = self._details_text(summary)
            self._details_correlation = (active.selection_revision, active.source_path)
            self._render_resource()
        elif result.status is TaskFinalStatus.SUCCEEDED:
            self.backend.fail_program_image_parse(
                self.page.target,
                active.source_path,
                active.selection_revision,
                "IMAGE_PREPARATION_INVALID_RESULT",
                "Image preparation returned an invalid result",
            )

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self._runtime_transition_received.emit(result)

    @Slot(object)
    def _apply_runtime_transition(self, result) -> None:
        resource = result.snapshot.target_resources[self.cpu_id]
        if resource != self.backend.target_resources[self.cpu_id]:
            return
        if resource.program_image_parse_status is not ImageParseStatus.READY:
            self._details = ""
            self._details_correlation = None
        elif self._details_correlation != (
            self.selection_revision,
            self._normalized_path_or_empty(resource.program_image_path),
        ):
            self._details = ""
            self._details_correlation = None
        self._render_resource(resource)

    def _render_resource(self, resource=None) -> None:
        resource = resource or self.backend.target_resources[self.cpu_id]
        status = resource.program_image_parse_status
        summary = resource.program_image_summary
        values = {
            "entry_point": "—",
            "image_size": "—",
            "crc32": "—",
            "parse_status": "Not parsed",
            "parse_state": "unknown",
        }
        details = ""
        if status is ImageParseStatus.PARSING:
            values.update(parse_status="Parsing", parse_state="busy")
        elif status is ImageParseStatus.READY and summary is not None:
            details = self._details
            identity = summary.identity
            values.update(
                entry_point=f"0x{identity.entry_point:08X}",
                image_size=f"{identity.image_size_words} words",
                crc32=f"0x{identity.image_crc32:08X}",
                parse_status="Parsed",
                parse_state="success",
            )
        elif status is ImageParseStatus.ERROR:
            values.update(parse_status="Parse failed", parse_state="error")
            details = resource.program_image_parse_error or ""
        self._updating_view = True
        try:
            self.page.set_image_summary(path=resource.program_image_path, **values)
            self.page.set_details_text(details)
        finally:
            self._updating_view = False

    def _clear_task_correlation(self) -> None:
        self._pending_submission = None
        self._active_request = None
        self._completed_submission_ids.clear()
        self._details_correlation = None

    def _unsubscribe(self, *_args) -> None:
        self.backend.unsubscribe_runtime_v2(self._runtime_v2_listener)

    def _pick_file(self) -> str | Path | None:
        title = f"Select {self.page.target.upper()} App Image"
        picker = self.file_picker
        if picker is None:
            selected, _filter = QFileDialog.getOpenFileName(
                self.page, title, "", "App Images (*.out *.txt)"
            )
            return selected or None
        result = (
            picker.getOpenFileName(self.page, title, "", "App Images (*.out *.txt)")
            if hasattr(picker, "getOpenFileName")
            else picker(self.page)
        )
        return result[0] if isinstance(result, tuple) and result else result

    @staticmethod
    def _normalize_path(text: str) -> str:
        trimmed = text.strip()
        if not trimmed:
            raise ValueError("Image path must not be empty")
        return str(Path(trimmed).expanduser().resolve(strict=False))

    @classmethod
    def _normalized_path_or_empty(cls, text: str) -> str:
        try:
            return cls._normalize_path(text)
        except (OSError, RuntimeError, ValueError):
            return ""

    def _request_is_current(self, request: _Submission) -> bool:
        resource = self.backend.target_resources[self.cpu_id]
        try:
            current = self._normalize_path(resource.program_image_path)
        except (OSError, RuntimeError, ValueError):
            return False
        return request.selection_revision == self.selection_revision and request.source_path == current

    def _preparation_allowed(self) -> bool:
        snapshot = self._snapshot
        return (
            snapshot.state is RuntimeState.DISCONNECTED
            and not snapshot.cleanup_pending
            and not snapshot.shutdown_requested
            and snapshot.active_task_id is None
        )

    @staticmethod
    def _details_text(summary: PreparedImageSummary) -> str:
        sectors = ", ".join(chr(ord("A") + bit) for bit in summary.image_sector_bits)
        fingerprint = summary.source_fingerprint
        return "\n".join(
            (
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
        )


__all__ = ["ProgramImageBinding"]
