from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.image_preparation_models import (
    Hex2000Source,
    ImageSourceKind,
    PreparedImageSummary,
    SourceFileFingerprint,
)
from bootloader_upgrade_tool.gui.pages.program_page import ProgramTargetPage
from bootloader_upgrade_tool.gui.program_image_binding import ProgramImageBinding
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
    ErrorDisposition,
    GuiRuntimeError,
    RequestAdmission,
    RequestRejection,
    RequestRejectionCode,
    RuntimeSnapshot,
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Backend:
    def __init__(self) -> None:
        self.invalidations: list[int | None] = []

    def invalidate_prepared_image_cache(self, revision: int | None = None) -> None:
        self.invalidations.append(revision)


class _Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.snapshot = RuntimeSnapshot()
        self.requests = []
        self.admissions: list[RequestAdmission] = []

    def request_task(self, request):
        self.requests.append(request)
        if self.admissions:
            return self.admissions.pop(0)
        return RequestAdmission(True, task_id=f"task-{len(self.requests)}")


def _summary(path: Path | str, revision: int) -> PreparedImageSummary:
    return PreparedImageSummary(
        target_key="cpu1",
        selection_revision=revision,
        source_path=str(path),
        source_kind=ImageSourceKind.TXT,
        source_fingerprint=SourceFileFingerprint(str(path), 10, 20),
        entry_point=0x082400,
        image_size_words=8,
        image_crc32=0x12345678,
        app_end=0x082408,
        image_sector_mask=0x2,
        effective_sector_mask=0x2,
        image_sector_bits=(1,),
        hex2000_source=Hex2000Source.NOT_USED,
        hex2000_executable=None,
    )


def _submit(page: ProgramTargetPage, app: QApplication) -> None:
    page.image_path_row.path_edit.editingFinished.emit()
    app.processEvents()


def _failure(task_id: str, revision: int, *, fatal: bool = False) -> TaskExecutionResult:
    error = GuiRuntimeError(
        "WORKER_RUNTIME_FATAL" if fatal else "IMAGE_PARSE_FAILED",
        "failed",
        "worker" if fatal else "prepare_flash_image",
        ErrorDisposition.RUNTIME_FATAL if fatal else ErrorDisposition.SHOW_ONLY,
        task_id,
        not fatal,
        details={} if fatal else {"selection_revision": revision},
    )
    return TaskExecutionResult(task_id, TaskFinalStatus.FAILED, "failed", "failed", error=error)


def _connected(target: str) -> RuntimeSnapshot:
    info = ConnectionInfo(
        "id",
        "SCI",
        "COM3",
        datetime.now(timezone.utc),
        target,
    )
    return RuntimeSnapshot(
        RuntimeState.CONNECTED,
        connection_info=info,
        active_target_key=target,
    )


def test_browse_focus_order_submits_only_selected_new_path(tmp_path: Path) -> None:
    app = qt_app()
    old, new = tmp_path / "old.txt", tmp_path / "new.txt"
    page, controller, backend = ProgramTargetPage("cpu1"), _Controller(), _Backend()
    binding = ProgramImageBinding(page, controller, backend, file_picker=lambda _parent: new)
    page.image_path_row.path_edit.setText(str(old))

    page.image_path_row.path_edit.editingFinished.emit()
    page.image_path_row.browse_button.click()
    app.processEvents()

    assert [request.source_path for request in controller.requests] == [str(new.resolve())]
    assert binding.selection_revision == 2


def test_browse_cancellation_does_not_submit_old_path(tmp_path: Path) -> None:
    app = qt_app()
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    ProgramImageBinding(page, controller, _Backend(), file_picker=lambda _parent: None)
    page.image_path_row.path_edit.setText(str(tmp_path / "old.txt"))

    page.image_path_row.path_edit.editingFinished.emit()
    page.image_path_row.browse_button.click()
    app.processEvents()

    assert controller.requests == []
    assert page.parse_status_row.badge.text() == "Not parsed"


def test_rejected_admission_is_retryable_and_not_left_parsing(tmp_path: Path) -> None:
    app = qt_app()
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    binding = ProgramImageBinding(page, controller, _Backend())
    controller.admissions.append(
        RequestAdmission(
            False,
            rejection=RequestRejection(
                RequestRejectionCode.TASK_ALREADY_ACTIVE,
                "busy",
            ),
        )
    )
    page.image_path_row.path_edit.setText(str(tmp_path / "app.txt"))

    _submit(page, app)
    assert page.parse_status_row.badge.text() == "Parse failed"
    _submit(page, app)

    assert len(controller.requests) == 2
    assert binding._last_submitted is not None


def test_parse_failure_retries_and_prepare_forces_reparse(tmp_path: Path) -> None:
    app = qt_app()
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    binding = ProgramImageBinding(page, controller, _Backend())
    path = tmp_path / "app.txt"
    page.image_path_row.path_edit.setText(str(path))
    _submit(page, app)
    controller.taskFinished.emit(_failure("task-1", binding.selection_revision))

    assert page.image_path_row.path_edit.text() == str(path)
    assert page.entry_point_row.value_label.text() == "—"
    assert page.image_size_row.value_label.text() == "—"
    assert page.crc32_row.value_label.text() == "—"
    assert page.parse_status_row.badge.text() == "Parse failed"
    assert page.details_edit.toPlainText() == "Code: IMAGE_PARSE_FAILED\nfailed"

    _submit(page, app)
    assert len(controller.requests) == 2
    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-2",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=_summary(path, binding.selection_revision),
        )
    )
    _submit(page, app)
    assert len(controller.requests) == 2
    page.prepare_image_button.click()
    assert len(controller.requests) == 3


def test_whitespace_path_and_normalization_failure_are_safe(tmp_path: Path, monkeypatch) -> None:
    app = qt_app()
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    binding = ProgramImageBinding(page, controller, _Backend())
    path = tmp_path / "app.txt"
    page.image_path_row.path_edit.setText(f"  {path}  ")
    _submit(page, app)
    assert controller.requests[0].source_path == str(path.resolve())

    page.image_path_row.path_edit.setText("bad")
    monkeypatch.setattr(binding, "_normalize_path", lambda _text: (_ for _ in ()).throw(OSError("bad path")))
    _submit(page, app)
    assert page.parse_status_row.badge.text() == "Parse failed"
    assert "INVALID_IMAGE_PATH" in page.details_edit.toPlainText()


def test_result_time_normalization_failure_does_not_leave_parsing(tmp_path: Path, monkeypatch) -> None:
    app = qt_app()
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    binding = ProgramImageBinding(page, controller, _Backend())
    page.image_path_row.path_edit.setText(str(tmp_path / "app.txt"))
    _submit(page, app)
    monkeypatch.setattr(
        binding,
        "_normalize_path",
        lambda _text: (_ for _ in ()).throw(OSError("bad path")),
    )

    controller.taskFinished.emit(_failure("task-1", binding.selection_revision))

    assert page.parse_status_row.badge.text() == "Parse failed"
    assert "INVALID_IMAGE_PATH" in page.details_edit.toPlainText()


@pytest.mark.parametrize(
    "result_factory",
    (
        lambda path, revision: TaskExecutionResult(
            "task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=_summary(path, revision)
        ),
        lambda _path, revision: _failure("task-1", revision),
        lambda _path, revision: _failure("task-1", revision, fatal=True),
    ),
)
def test_all_stale_results_are_ignored(tmp_path: Path, result_factory) -> None:
    app = qt_app()
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    binding = ProgramImageBinding(page, controller, _Backend())
    page.image_path_row.path_edit.setText(str(first))
    _submit(page, app)
    old_revision = binding.selection_revision
    page.image_path_row.path_edit.setText(str(second))

    controller.taskFinished.emit(result_factory(first, old_revision))

    assert page.parse_status_row.badge.text() == "Not parsed"
    assert page.details_edit.toPlainText() == ""


@pytest.mark.parametrize("payload", (None, {"bad": "payload"}))
def test_success_without_matching_summary_invalidates_and_retries(tmp_path: Path, payload) -> None:
    app = qt_app()
    page, controller, backend = ProgramTargetPage("cpu1"), _Controller(), _Backend()
    binding = ProgramImageBinding(page, controller, backend)
    path = tmp_path / "app.txt"
    page.image_path_row.path_edit.setText(str(path))
    _submit(page, app)

    controller.taskFinished.emit(
        TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload)
    )

    assert backend.invalidations[-1] == binding.selection_revision
    assert page.parse_status_row.badge.text() == "Parse failed"
    assert "IMAGE_PREPARATION_INVALID_RESULT" in page.details_edit.toPlainText()
    _submit(page, app)
    assert len(controller.requests) == 2


def test_success_with_mismatched_summary_is_invalid_result(tmp_path: Path) -> None:
    app = qt_app()
    path = tmp_path / "app.txt"
    page, controller, backend = ProgramTargetPage("cpu1"), _Controller(), _Backend()
    binding = ProgramImageBinding(page, controller, backend)
    page.image_path_row.path_edit.setText(str(path))
    _submit(page, app)

    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=_summary(tmp_path / "other.txt", binding.selection_revision),
        )
    )

    assert page.parse_status_row.badge.text() == "Parse failed"
    assert backend.invalidations[-1] == binding.selection_revision


def test_unexpected_non_success_status_is_stable_and_retryable(tmp_path: Path) -> None:
    app = qt_app()
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    ProgramImageBinding(page, controller, _Backend())
    page.image_path_row.path_edit.setText(str(tmp_path / "app.txt"))
    _submit(page, app)

    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            TaskFinalStatus.CANCELLED,
            "cancelled",
            "cancelled",
            cancel_requested=True,
        )
    )

    assert page.parse_status_row.badge.text() == "Parse failed"
    _submit(page, app)
    assert len(controller.requests) == 2


def test_cpu1_connect_preserves_but_disconnect_and_cpu2_reset(tmp_path: Path) -> None:
    app = qt_app()
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    binding = ProgramImageBinding(page, controller, _Backend())
    path = tmp_path / "app.txt"
    page.image_path_row.path_edit.setText(str(path))
    _submit(page, app)
    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=_summary(path, binding.selection_revision),
        )
    )

    controller.snapshot = RuntimeSnapshot(RuntimeState.CONNECTING)
    controller.runtimeStateChanged.emit(controller.snapshot)
    controller.snapshot = RuntimeSnapshot()
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert page.parse_status_row.badge.text() == "Parsed"

    controller.snapshot = RuntimeSnapshot(RuntimeState.CONNECTING)
    controller.runtimeStateChanged.emit(controller.snapshot)
    controller.snapshot = _connected("cpu1")
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert page.parse_status_row.badge.text() == "Parsed"

    info = controller.snapshot.connection_info
    controller.snapshot = RuntimeSnapshot(
        RuntimeState.DISCONNECTING,
        active_task_id="disconnect",
        connection_info=info,
        active_target_key="cpu1",
    )
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert page.parse_status_row.badge.text() == "Not parsed"
    assert page.image_path_row.path_edit.text() == str(path)

    controller.snapshot = RuntimeSnapshot()
    controller.runtimeStateChanged.emit(controller.snapshot)
    _submit(page, app)
    assert len(controller.requests) == 2

    controller.snapshot = _connected("cpu2")
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert page.parse_status_row.badge.text() == "Not parsed"


def test_controls_and_options_remain_bounded() -> None:
    qt_app()
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    ProgramImageBinding(page, controller, _Backend())
    assert page.image_path_row.path_edit.isEnabled()

    controller.snapshot = RuntimeSnapshot(RuntimeState.BUSY, active_task_id="task")
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert not page.image_path_row.path_edit.isEnabled()
    assert not page.force_load_checkbox.isEnabled()
    assert not page.auto_run_checkbox.isEnabled()
    assert not page.confirm_app_checkbox.isEnabled()


@pytest.mark.parametrize(
    "snapshot",
    (
        RuntimeSnapshot(RuntimeState.CONNECTING),
        RuntimeSnapshot(RuntimeState.BUSY, active_task_id="task"),
        RuntimeSnapshot(RuntimeState.DISCONNECTING, active_task_id="task"),
        RuntimeSnapshot(cleanup_pending=True),
        RuntimeSnapshot(active_task_id="task"),
    ),
)
def test_all_submission_entries_require_clean_disconnected(tmp_path, snapshot) -> None:
    app = qt_app()
    picker_calls = []
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    ProgramImageBinding(page, controller, _Backend(), file_picker=lambda _parent: picker_calls.append(1))
    page.image_path_row.path_edit.setText(str(tmp_path / "app.txt"))
    controller.snapshot = snapshot
    controller.runtimeStateChanged.emit(snapshot)

    page.image_path_row.path_edit.editingFinished.emit()
    page.prepareRequested.emit("cpu1")
    page.browseRequested.emit("cpu1")
    app.processEvents()

    assert controller.requests == []
    assert picker_calls == []
    assert page.parse_status_row.badge.text() == "Not parsed"


def test_queued_edit_is_cancelled_when_runtime_starts_connecting(tmp_path) -> None:
    app = qt_app()
    page, controller = ProgramTargetPage("cpu1"), _Controller()
    ProgramImageBinding(page, controller, _Backend())
    page.image_path_row.path_edit.setText(str(tmp_path / "app.txt"))
    page.image_path_row.path_edit.editingFinished.emit()
    controller.snapshot = RuntimeSnapshot(RuntimeState.CONNECTING)
    controller.runtimeStateChanged.emit(controller.snapshot)
    app.processEvents()
    assert controller.requests == []
    assert page.parse_status_row.badge.text() == "Not parsed"


def test_synchronous_finish_inside_request_is_handled_and_retryable(tmp_path) -> None:
    app = qt_app()

    class SyncController(_Controller):
        def request_task(self, request):
            self.requests.append(request)
            task_id = f"task-{len(self.requests)}"
            self.taskFinished.emit(_failure(task_id, request.selection_revision))
            return RequestAdmission(True, task_id=task_id)

    page, controller, backend = ProgramTargetPage("cpu1"), SyncController(), _Backend()
    binding = ProgramImageBinding(page, controller, backend)
    page.image_path_row.path_edit.setText(str(tmp_path / "app.txt"))
    _submit(page, app)

    assert page.parse_status_row.badge.text() == "Parse failed"
    assert binding._active_request is None
    assert backend.invalidations[-1] == binding.selection_revision
    _submit(page, app)
    assert len(controller.requests) == 2


def test_browse_same_path_forces_reprepare_and_cancel_preserves_success(tmp_path) -> None:
    app = qt_app()
    path = tmp_path / "app.txt"
    selections = iter((path, None))
    page, controller, backend = ProgramTargetPage("cpu1"), _Controller(), _Backend()
    binding = ProgramImageBinding(page, controller, backend, file_picker=lambda _parent: next(selections))
    page.image_path_row.path_edit.setText(str(path))
    _submit(page, app)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=_summary(path, binding.selection_revision)))

    page.browseRequested.emit("cpu1")
    assert len(controller.requests) == 2
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=_summary(path, binding.selection_revision)))
    page.browseRequested.emit("cpu1")

    assert len(controller.requests) == 2
    assert page.parse_status_row.badge.text() == "Parsed"
    assert backend.invalidations[-1] == binding.selection_revision


def test_binding_rejects_cpu2() -> None:
    qt_app()
    with pytest.raises(ValueError, match="CPU1"):
        ProgramImageBinding(ProgramTargetPage("cpu2"), _Controller(), _Backend())
