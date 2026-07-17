from __future__ import annotations

import os
import threading
from pathlib import Path
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.image_preparation_models import (
    Hex2000Source,
    ImageSourceKind,
    PreparedImageSummary,
    SourceFileFingerprint,
)
from bootloader_upgrade_tool.gui.pages.program_page import ProgramTargetPage
from bootloader_upgrade_tool.gui.program_image_binding import ProgramImageBinding
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import (
    RequestAdmission,
    ConnectionInfo,
    RequestRejection,
    RequestRejectionCode,
    RuntimeSnapshot,
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.gui.runtime_v2_events import ProgramImageChanged
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    FlashImageSummary,
    ImageParseStatus,
    RuntimeCpuId,
)
from bootloader_upgrade_tool.images import ImageIdentity


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module", autouse=True)
def _module_qapplication():
    app = qt_app()
    yield app


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


def _binding(target: str, *, picker=None):
    page = ProgramTargetPage(target)
    controller = _Controller()
    backend = RuntimeBackend()
    binding = ProgramImageBinding(page, controller, backend, file_picker=picker)
    return page, controller, backend, binding


def _summary(target: str, path: str, revision: int) -> PreparedImageSummary:
    return PreparedImageSummary(
        target,
        revision,
        path,
        ImageSourceKind.TXT,
        SourceFileFingerprint(path, 10, 20),
        0x82400,
        8,
        0x12345678,
        0x82408,
        2,
        2,
        (1,),
        Hex2000Source.NOT_USED,
        None,
    )


@pytest.mark.parametrize("target", ("cpu1", "cpu2"))
def test_binding_is_generic_and_revision_is_backend_owned(target) -> None:
    page, _controller, backend, binding = _binding(target)
    assert page.target == target
    assert "_selection_revision" not in vars(binding)
    assert binding.selection_revision == backend.program_image_revision(target) == 0


@pytest.mark.parametrize("target", ("cpu1", "cpu2"))
def test_path_edit_and_same_path_session_apply_use_backend(target, tmp_path) -> None:
    app = qt_app()
    page, _controller, backend, binding = _binding(target)
    path = str(tmp_path / f"{target}.txt")
    page.image_path_row.path_edit.setText(path)
    app.processEvents()
    first = backend.program_image_revision(target)
    binding.apply_session_path(path)
    state = backend.target_resources[RuntimeCpuId.from_target_key(target)]
    assert first == 1 and binding.selection_revision == 2
    assert state.program_image_path == path
    assert state.program_image_parse_status is ImageParseStatus.EMPTY


@pytest.mark.parametrize("target", ("cpu1", "cpu2"))
def test_editing_finished_submits_target_specific_parse(target, tmp_path) -> None:
    app = qt_app()
    page, controller, backend, _binding_value = _binding(target)
    path = tmp_path / f"{target}.txt"
    page.image_path_row.path_edit.setText(str(path))
    page.image_path_row.path_edit.editingFinished.emit()
    app.processEvents()
    request = controller.requests[0]
    assert request.target_key == target
    assert request.selection_revision == backend.program_image_revision(target)
    assert backend.target_resources[RuntimeCpuId.from_target_key(target)].program_image_parse_status is ImageParseStatus.PARSING


@pytest.mark.parametrize("target", ("cpu1", "cpu2"))
def test_browse_parses_selected_path_and_cancel_submits_nothing(target, tmp_path) -> None:
    selected = tmp_path / f"{target}.txt"
    page, controller, backend, _ = _binding(target, picker=lambda _parent: selected)
    page.browseRequested.emit(target)
    assert controller.requests[0].source_path == str(selected.resolve())
    assert backend.target_resources[RuntimeCpuId.from_target_key(target)].program_image_path == str(selected)

    cancelled_page, cancelled_controller, _backend, _ = _binding(target, picker=lambda _parent: None)
    cancelled_page.browseRequested.emit(target)
    assert cancelled_controller.requests == []


@pytest.mark.parametrize("target", ("cpu1", "cpu2"))
def test_prepare_forces_reparse_from_ready(target, tmp_path) -> None:
    page, controller, backend, binding = _binding(target)
    path = str((tmp_path / f"{target}.txt").resolve())
    revision = backend.set_program_image_path(target, path)
    cpu_id = RuntimeCpuId.from_target_key(target)
    backend._runtime_v2_dispatcher.dispatch(
        ProgramImageChanged(
            cpu_id,
            path,
            ImageParseStatus.READY,
            FlashImageSummary(ImageIdentity(0x82400, 8, 1, 0x82408), 2),
        )
    )
    assert binding.prepare_current(force=False) is None
    admission = binding.prepare_current(force=True)
    assert admission.accepted and len(controller.requests) == 1
    assert controller.requests[0].selection_revision == revision


@pytest.mark.parametrize("target", ("cpu1", "cpu2"))
def test_admission_rejection_commits_backend_error_and_is_retryable(target, tmp_path) -> None:
    app = qt_app()
    page, controller, backend, _ = _binding(target)
    controller.admissions.append(
        RequestAdmission(
            False,
            rejection=RequestRejection(RequestRejectionCode.TASK_ALREADY_ACTIVE, "busy"),
        )
    )
    page.image_path_row.path_edit.setText(str(tmp_path / f"{target}.txt"))
    page.image_path_row.path_edit.editingFinished.emit()
    app.processEvents()
    state = backend.target_resources[RuntimeCpuId.from_target_key(target)]
    assert state.program_image_parse_status is ImageParseStatus.ERROR
    assert state.program_image_parse_error == "Code: IMAGE_PREPARATION_NOT_STARTED\nbusy"
    page.image_path_row.path_edit.editingFinished.emit()
    app.processEvents()
    assert len(controller.requests) == 2


@pytest.mark.parametrize(
    ("status", "label", "ui_state"),
    (
        (ImageParseStatus.EMPTY, "Not parsed", "unknown"),
        (ImageParseStatus.PARSING, "Parsing", "busy"),
        (ImageParseStatus.READY, "Parsed", "success"),
        (ImageParseStatus.ERROR, "Parse failed", "error"),
    ),
)
def test_backend_states_render_without_view_owned_summary(status, label, ui_state, tmp_path) -> None:
    page, _controller, backend, _ = _binding("cpu1")
    path = str(tmp_path / "app.txt")
    summary = FlashImageSummary(ImageIdentity(0x82400, 8, 0x12345678, 0x82408), 2)
    backend._runtime_v2_dispatcher.dispatch(
        ProgramImageChanged(
            RuntimeCpuId.CPU1,
            "" if status is ImageParseStatus.EMPTY else path,
            status,
            summary if status is ImageParseStatus.READY else None,
            "Code: BAD\nfailed" if status is ImageParseStatus.ERROR else None,
        )
    )
    assert page.parse_status_row.badge.text() == label
    assert page.parse_status_row.badge.property("state") == ui_state
    assert page.entry_point_row.value_label.text() == ("0x00082400" if status is ImageParseStatus.READY else "—")
    assert page.details_edit.toPlainText() == (
        "Code: BAD\nfailed" if status is ImageParseStatus.ERROR else ""
    )


def test_cpu_resources_and_pages_remain_independent(tmp_path) -> None:
    page1, controller, backend, _ = _binding("cpu1")
    page2 = ProgramTargetPage("cpu2")
    ProgramImageBinding(page2, controller, backend)
    path = str(tmp_path / "cpu1.txt")
    backend.set_program_image_path("cpu1", path)
    assert page1.image_path_row.path_edit.text() == path
    assert page2.image_path_row.path_edit.text() == ""


def test_connection_changes_preserve_program_presentation(tmp_path) -> None:
    page, controller, backend, _ = _binding("cpu1")
    path = str(tmp_path / "app.txt")
    backend.set_program_image_path("cpu1", path)
    backend._runtime_v2_dispatcher.dispatch(
        ProgramImageChanged(
            RuntimeCpuId.CPU1,
            path,
            ImageParseStatus.READY,
            FlashImageSummary(ImageIdentity(0x82400, 8, 1, 0x82408), 2),
        )
    )
    for snapshot in (
        RuntimeSnapshot(RuntimeState.CONNECTING),
        RuntimeSnapshot(
            RuntimeState.CONNECTED,
            connection_info=ConnectionInfo("id", "SCI", "COM3", datetime.now(timezone.utc), "cpu2"),
            active_target_key="cpu2",
        ),
        RuntimeSnapshot(RuntimeState.DISCONNECTING, active_task_id="disconnect"),
        RuntimeSnapshot(),
    ):
        controller.snapshot = snapshot
        controller.runtimeStateChanged.emit(snapshot)
    assert page.image_path_row.path_edit.text() == path
    assert page.parse_status_row.badge.text() == "Parsed"


@pytest.mark.parametrize(
    "snapshot",
    (
        RuntimeSnapshot(RuntimeState.CONNECTING),
        RuntimeSnapshot(RuntimeState.BUSY, active_task_id="task"),
        RuntimeSnapshot(cleanup_pending=True),
        RuntimeSnapshot(shutdown_requested=True),
    ),
)
def test_runtime_gate_disables_local_controls(snapshot) -> None:
    page, controller, _backend, _ = _binding("cpu2")
    controller.snapshot = snapshot
    controller.runtimeStateChanged.emit(snapshot)
    assert not page.image_path_row.path_edit.isEnabled()
    assert not page.force_load_checkbox.isEnabled()
    assert not page.auto_run_checkbox.isEnabled()
    assert not page.confirm_app_checkbox.isEnabled()


def test_owned_success_shows_details_without_retaining_task_summary(tmp_path) -> None:
    app = qt_app()
    page, controller, backend, binding = _binding("cpu1")
    path = str((tmp_path / "app.txt").resolve())
    page.image_path_row.path_edit.setText(path)
    page.image_path_row.path_edit.editingFinished.emit()
    app.processEvents()
    revision = binding.selection_revision
    backend._runtime_v2_dispatcher.dispatch(
        ProgramImageChanged(
            RuntimeCpuId.CPU1,
            path,
            ImageParseStatus.READY,
            FlashImageSummary(ImageIdentity(0x82400, 8, 0x12345678, 0x82408), 2),
        )
    )
    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=_summary("cpu1", path, revision),
        )
    )
    assert "Source path:" in page.details_edit.toPlainText()
    assert not any(isinstance(value, PreparedImageSummary) for value in vars(binding).values())


def test_program_runtime_transition_from_worker_is_queued_to_gui_thread(tmp_path) -> None:
    app = qt_app()
    page, controller, backend, binding = _binding("cpu1")
    gui_thread = app.thread()
    listener_threads = []
    widget_threads = []
    backend.subscribe_runtime_v2(lambda _result: listener_threads.append(QThread.currentThread()))
    original = page.set_image_summary

    def record_widget_thread(**values):
        widget_threads.append(QThread.currentThread())
        original(**values)

    page.set_image_summary = record_widget_thread
    path = str((tmp_path / "worker.txt").resolve())
    worker = threading.Thread(target=lambda: backend.set_program_image_path("cpu1", path))
    worker.start()
    worker.join()

    assert listener_threads[-1] != gui_thread
    assert page.image_path_row.path_edit.text() == ""
    assert widget_threads == []
    app.processEvents()
    assert page.image_path_row.path_edit.text() == path
    assert widget_threads[-1] == gui_thread == binding.thread()

    page.image_path_row.path_edit.editingFinished.emit()
    app.processEvents()
    revision = binding.selection_revision
    worker = threading.Thread(
        target=lambda: backend._runtime_v2_dispatcher.dispatch(
            ProgramImageChanged(
                RuntimeCpuId.CPU1,
                path,
                ImageParseStatus.READY,
                FlashImageSummary(ImageIdentity(0x82400, 8, 0x1234, 0x82408), 2),
            )
        )
    )
    worker.start()
    worker.join()
    assert page.parse_status_row.badge.text() == "Parsing"
    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok",
            payload=_summary("cpu1", path, revision),
        )
    )
    assert f"Source path: {path}" in page.details_edit.toPlainText()
    app.processEvents()
    assert f"Source path: {path}" in page.details_edit.toPlainText()

    stale_path = str((tmp_path / "stale.txt").resolve())
    current_path = str((tmp_path / "current.txt").resolve())
    worker = threading.Thread(
        target=lambda: backend.set_program_image_path("cpu1", stale_path)
    )
    worker.start()
    worker.join()
    backend.set_program_image_path("cpu1", current_path)
    assert page.image_path_row.path_edit.text() == current_path
    app.processEvents()
    assert page.image_path_row.path_edit.text() == current_path


def test_details_follow_current_program_state_and_owned_task(tmp_path) -> None:
    app = qt_app()
    page, controller, backend, binding = _binding("cpu1")
    path_a = str((tmp_path / "a.txt").resolve())
    page.image_path_row.path_edit.setText(path_a)
    page.image_path_row.path_edit.editingFinished.emit()
    app.processEvents()
    revision_a = binding.selection_revision
    backend._runtime_v2_dispatcher.dispatch(
        ProgramImageChanged(
            RuntimeCpuId.CPU1,
            path_a,
            ImageParseStatus.READY,
            FlashImageSummary(ImageIdentity(0x82400, 8, 0xAAAA, 0x82408), 2),
        )
    )
    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok",
            payload=_summary("cpu1", path_a, revision_a),
        )
    )
    assert f"Source path: {path_a}" in page.details_edit.toPlainText()

    binding.prepare_current(force=True)
    assert backend.target_resources[RuntimeCpuId.CPU1].program_image_parse_status is ImageParseStatus.PARSING
    assert page.details_edit.toPlainText() == ""

    path_b = str((tmp_path / "b.txt").resolve())
    page.image_path_row.path_edit.setText(path_b)
    assert page.details_edit.toPlainText() == ""
    page.image_path_row.path_edit.editingFinished.emit()
    app.processEvents()
    revision_b = binding.selection_revision
    backend.fail_program_image_parse("cpu1", path_b, revision_b, "BAD_B", "failed B")
    assert page.details_edit.toPlainText() == "Code: BAD_B\nfailed B"

    page.image_path_row.path_edit.editingFinished.emit()
    app.processEvents()
    backend._runtime_v2_dispatcher.dispatch(
        ProgramImageChanged(
            RuntimeCpuId.CPU1,
            path_b,
            ImageParseStatus.READY,
            FlashImageSummary(ImageIdentity(0x82400, 8, 0xBBBB, 0x82408), 2),
        )
    )
    assert page.details_edit.toPlainText() == ""
    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1", TaskFinalStatus.SUCCEEDED, "stale", "stale",
            payload=_summary("cpu1", path_a, revision_a),
        )
    )
    assert page.details_edit.toPlainText() == ""
    controller.taskFinished.emit(
        TaskExecutionResult(
            binding._active_request.task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok",
            payload=_summary("cpu1", path_b, revision_b),
        )
    )
    assert f"Source path: {path_b}" in page.details_edit.toPlainText()
    assert path_a not in page.details_edit.toPlainText()


def test_out_tool_change_clears_only_each_affected_cpu_details(tmp_path) -> None:
    app = qt_app()
    page1, controller, backend, binding1 = _binding("cpu1")
    page2 = ProgramTargetPage("cpu2")
    binding2 = ProgramImageBinding(page2, controller, backend)
    for page, binding, cpu_id in (
        (page1, binding1, RuntimeCpuId.CPU1),
        (page2, binding2, RuntimeCpuId.CPU2),
    ):
        path = str((tmp_path / f"{cpu_id.value}.out").resolve())
        page.image_path_row.path_edit.setText(path)
        page.image_path_row.path_edit.editingFinished.emit()
        app.processEvents()
        revision = binding.selection_revision
        task_id = binding._active_request.task_id
        backend._runtime_v2_dispatcher.dispatch(
            ProgramImageChanged(
                cpu_id, path, ImageParseStatus.READY,
                FlashImageSummary(ImageIdentity(0x82400, 8, 1, 0x82408), 2),
            )
        )
        controller.taskFinished.emit(
            TaskExecutionResult(
                task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok",
                payload=_summary(cpu_id.value, path, revision),
            )
        )
    assert page1.details_edit.toPlainText()
    assert page2.details_edit.toPlainText()

    backend.set_program_image_path("cpu1", str(tmp_path / "cpu1-next.out"))
    assert page1.details_edit.toPlainText() == ""
    assert page2.details_edit.toPlainText()
    backend.set_image_tool_paths("new-hex2000.exe", "new-temp")
    assert page2.details_edit.toPlainText() == ""


def test_listener_unsubscribes_when_binding_is_destroyed() -> None:
    _page, _controller, backend, binding = _binding("cpu1")
    listener = binding._runtime_v2_listener
    assert listener in backend._runtime_v2_dispatcher._listeners
    binding.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert listener not in backend._runtime_v2_dispatcher._listeners
    binding._unsubscribe()
