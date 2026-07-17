from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Thread

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_ram_binding import AdvancedRamBinding
from bootloader_upgrade_tool.gui.advanced_ram_models import (
    AdvancedRamOperationSnapshot,
    PreparedRamImageSummary,
)
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
    ErrorDisposition,
    GuiRuntimeError,
    RequestAdmission,
    RequestRejection,
    RequestRejectionCode,
    RuntimeSnapshot,
    RuntimeState,
    TaskCompletionAction,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.images import PreparedRamImage
from bootloader_upgrade_tool.images.models import RamImageIdentity
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE
from bootloader_upgrade_tool.gui.runtime_v2_events import RamImageChanged
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ImageParseStatus,
    RamImageSummary,
    RuntimeCpuId,
    RuntimeStateStore,
)
from bootloader_upgrade_tool.gui.runtime_v2_transition import DomainEventDispatcher


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self):
        super().__init__()
        self._snapshot = RuntimeSnapshot()
        self.requests = []
        self.admission = None
        self.request_error = None

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        if self.request_error is not None:
            raise self.request_error
        self.requests.append(request)
        return self.admission or RequestAdmission(True, task_id=f"task-{len(self.requests)}")


class Backend:
    def __init__(self):
        self.active_target = None
        self.cache = {}
        self._revisions = {cpu: 0 for cpu in RuntimeCpuId}
        self._dispatcher = DomainEventDispatcher(RuntimeStateStore())
        self.begin_calls = []
        self.fail_calls = []
        self.fail_error = None
        self.fail_returns_none = False

    @property
    def target_resources(self):
        return self._dispatcher._store.snapshot().target_resources

    def subscribe_runtime_v2(self, listener):
        self._dispatcher.subscribe(listener)

    def unsubscribe_runtime_v2(self, listener):
        self._dispatcher.unsubscribe(listener)

    def ram_image_revision(self, target):
        return self._revisions[RuntimeCpuId.from_target_key(target)]

    def set_ram_image_path(self, target, path):
        cpu = RuntimeCpuId.from_target_key(target)
        self._revisions[cpu] += 1
        self.cache.pop(target, None)
        self._dispatcher.dispatch(RamImageChanged(cpu, path, ImageParseStatus.EMPTY))
        return self._revisions[cpu]

    def begin_ram_image_parse(self, target, path, revision):
        self.begin_calls.append((target, path, revision))
        cpu = RuntimeCpuId.from_target_key(target)
        assert revision == self._revisions[cpu]
        resource = self.target_resources[cpu]
        return self._dispatcher.dispatch(
            RamImageChanged(cpu, resource.ram_image_path, ImageParseStatus.PARSING)
        )

    def fail_ram_image_parse(self, target, path, revision, code, message):
        self.fail_calls.append((target, path, revision, code, message))
        if self.fail_error is not None:
            raise self.fail_error
        if self.fail_returns_none:
            return None
        cpu = RuntimeCpuId.from_target_key(target)
        if revision != self._revisions[cpu]:
            return None
        resource = self.target_resources[cpu]
        return self._dispatcher.dispatch(
            RamImageChanged(
                cpu,
                resource.ram_image_path,
                ImageParseStatus.ERROR,
                parse_error=f"Code: {code}\n{message}",
            )
        )

    def ready(self, prepared_summary):
        cpu = RuntimeCpuId.from_target_key(prepared_summary.target_key)
        resource = self.target_resources[cpu]
        self._dispatcher.dispatch(
            RamImageChanged(
                cpu,
                resource.ram_image_path,
                ImageParseStatus.READY,
                RamImageSummary(
                    RamImageIdentity(
                        prepared_summary.entry_point,
                        prepared_summary.image_size_words,
                        prepared_summary.image_crc32,
                    )
                ),
            )
        )

    def prepared_ram_image_cache(self, target):
        return self.cache.get(target)


def connection(identity="connection", target="cpu1"):
    return ConnectionInfo(identity, "SCI", "COM3", datetime.now(timezone.utc), target)


def apply(controller, backend, snapshot, profile=None):
    controller._snapshot = snapshot
    backend.active_target = profile
    controller.runtimeStateChanged.emit(snapshot)


def summary(path: Path, target="cpu1", revision=1):
    fingerprint = SourceFileFingerprint(str(path), path.stat().st_size, path.stat().st_mtime_ns)
    return PreparedRamImageSummary(target, revision, str(path), ImageSourceKind.TXT, fingerprint, 0x8000, 3, 0x12345678, Hex2000Source.NOT_USED, None)


def setup(binding_type=AdvancedRamBinding):
    page = AdvancedPage()
    controller = Controller()
    backend = Backend()
    binding = binding_type(page, controller, backend)
    return page, controller, backend, binding


class ThreadRecordingBinding(AdvancedRamBinding):
    def __init__(self, *args, **kwargs):
        self.listener_threads = []
        self.render_threads = []
        super().__init__(*args, **kwargs)
        self.render_threads.clear()

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self.listener_threads.append(QThread.currentThread())
        super()._receive_runtime_transition_from_backend(result)

    def _render_resource(self, cpu_id, resource=None) -> None:
        self.render_threads.append(QThread.currentThread())
        super()._render_resource(cpu_id, resource)


def test_worker_thread_ram_transition_renders_on_gui_thread(app, tmp_path) -> None:
    page, _controller, backend, binding = setup(ThreadRecordingBinding)
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.cache["cpu1"] = (object(), prepared_summary)
    binding.listener_threads.clear()
    binding.render_threads.clear()

    worker = Thread(target=lambda: backend.ready(prepared_summary))
    worker.start()
    worker.join()
    assert page.cpu1_ram_entry_point_value.text() == "—"
    assert binding.listener_threads[-1] is not app.thread()
    assert binding.render_threads == []
    for _ in range(10):
        app.processEvents()
        if page.cpu1_ram_entry_point_value.text() == "0x00008000":
            break

    assert page.cpu1_ram_entry_point_value.text() == "0x00008000"
    assert page.cpu1_ram_image_size_value.text() == "3 words"
    assert binding.render_threads[-1] is app.thread()
    assert binding.render_threads[-1] is binding.thread()


def test_actual_destruction_unsubscribes_exact_runtime_listener(app) -> None:
    page = AdvancedPage()
    controller = Controller()
    backend = RuntimeBackend()
    binding = AdvancedRamBinding(page, controller, backend)
    listener = binding._runtime_v2_listener
    listeners = backend._runtime_v2_dispatcher._listeners
    assert listener in listeners

    binding.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()

    assert listener not in listeners
    backend.set_ram_image_path("cpu1", "later.txt")


def test_stale_queued_ram_transition_cannot_overwrite_newer_selection(app, tmp_path) -> None:
    page, _controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.cache["cpu1"] = (object(), prepared_summary)
    worker = Thread(target=lambda: backend.ready(prepared_summary))
    worker.start()
    worker.join()

    backend.set_ram_image_path("cpu1", "new.txt")
    app.processEvents()

    assert page.cpu1_ram_image_edit.text() == "new.txt"
    assert page.cpu1_ram_entry_point_value.text() == "—"


def test_editing_finished_automatically_submits_current_selection(app, tmp_path) -> None:
    page, controller, backend, _binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    page.cpu1_ram_image_edit.setText(str(path))

    page.cpu1_ram_image_edit.editingFinished.emit()
    app.processEvents()

    assert len(controller.requests) == 1
    assert controller.requests[0].target_key == "cpu1"
    assert backend.target_resources[RuntimeCpuId.CPU1].ram_image_parse_status is ImageParseStatus.PARSING


def _establish_ready(binding, backend, path):
    binding.apply_session_path("cpu1", str(path))
    revision = backend.ram_image_revision("cpu1")
    backend.begin_ram_image_parse("cpu1", str(path), revision)
    prepared_summary = summary(path, revision=revision)
    backend.cache["cpu1"] = (object(), prepared_summary)
    backend.ready(prepared_summary)
    return revision, prepared_summary


def test_busy_snapshot_cancels_queued_automatic_ram_parse(app, tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    revision, prepared_summary = _establish_ready(binding, backend, path)
    page.result_output.setPlainText("keep")
    begin_count = len(backend.begin_calls)
    page.cpu1_ram_image_edit.editingFinished.emit()

    apply(controller, backend, RuntimeSnapshot(RuntimeState.BUSY, active_task_id="other"))
    app.processEvents()

    resource = backend.target_resources[RuntimeCpuId.CPU1]
    assert controller.requests == []
    assert len(backend.begin_calls) == begin_count
    assert backend.ram_image_revision("cpu1") == revision
    assert resource.ram_image_parse_status is ImageParseStatus.READY
    assert resource.ram_image_summary is not None
    assert backend.cache["cpu1"][1] == prepared_summary
    assert page.result_output.toPlainText() == "keep"


def test_forced_prepare_while_busy_is_complete_noop(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    revision, prepared_summary = _establish_ready(binding, backend, path)
    page.result_output.setPlainText("keep")
    begin_count = len(backend.begin_calls)
    apply(controller, backend, RuntimeSnapshot(RuntimeState.BUSY, active_task_id="other"))

    assert binding.prepare("cpu1", force=True) is None

    assert controller.requests == []
    assert len(backend.begin_calls) == begin_count
    assert backend.ram_image_revision("cpu1") == revision
    assert backend.cache["cpu1"][1] == prepared_summary
    assert page.result_output.toPlainText() == "keep"


def test_admission_error_preserves_runtime_details(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    controller.admission = RequestAdmission(
        False,
        error=GuiRuntimeError(
            "WORKER_STARTUP_FAILED",
            "worker failed",
            "controller",
            ErrorDisposition.SHOW_ONLY,
            details={"generation": 7},
        ),
    )

    admission = binding.prepare("cpu1")

    assert admission is controller.admission
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    assert resource.ram_image_parse_error == "Code: WORKER_STARTUP_FAILED\nworker failed"
    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"] == {
        "code": "WORKER_STARTUP_FAILED",
        "stage": "controller",
        "message": "worker failed",
        "details": {"generation": 7},
    }


def test_ordinary_rejection_preserves_code_and_message(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    rejection = RequestRejection(
        RequestRejectionCode.TASK_ALREADY_ACTIVE, "another task is active"
    )
    controller.admission = RequestAdmission(False, rejection=rejection)

    binding.prepare("cpu1")

    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"]["code"] == "TASK_ALREADY_ACTIVE"
    assert shown["error"]["message"] == "another task is active"
    assert backend.target_resources[RuntimeCpuId.CPU1].ram_image_parse_error == (
        "Code: IMAGE_PREPARATION_NOT_STARTED\nanother task is active"
    )


def test_request_exception_is_primary_prepare_failure(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    controller.request_error = RuntimeError("request exploded")

    assert binding.prepare("cpu1") is None

    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"] == {
        "code": "IMAGE_PREPARATION_NOT_STARTED",
        "stage": "prepare_ram_image",
        "message": "request exploded",
    }


def test_failure_publication_exception_is_contained(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    controller.admission = RequestAdmission(
        False,
        error=GuiRuntimeError(
            "ADMISSION_FAILED", "primary failure", "controller", ErrorDisposition.SHOW_ONLY
        ),
    )
    backend.fail_error = RuntimeError("RuntimeBackend concurrent entry is not allowed")

    binding.prepare("cpu1")

    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"]["code"] == "ADMISSION_FAILED"
    assert shown["error"]["message"] == "primary failure"
    assert shown["state_update_error"] == {
        "exception_type": "RuntimeError",
        "message": "RuntimeBackend concurrent entry is not allowed",
    }


def test_stale_failure_publication_none_is_safe(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    controller.admission = RequestAdmission(
        False,
        rejection=RequestRejection(
            RequestRejectionCode.INVALID_RUNTIME_STATE, "not idle"
        ),
    )
    backend.fail_returns_none = True

    binding.prepare("cpu1")

    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"]["code"] == "INVALID_RUNTIME_STATE"
    assert "state_update_error" not in shown


def test_apply_session_path_invalidates_same_text_without_submitting() -> None:
    page, controller, backend, binding = setup()
    binding.apply_session_path("cpu1", "same.txt")
    binding.apply_session_path("cpu1", "same.txt")
    assert page.cpu1_ram_image_edit.text() == "same.txt"
    assert backend.ram_image_revision("cpu1") == 2
    assert not hasattr(binding, "_revisions")
    assert not hasattr(binding, "_summaries")
    assert controller.requests == []


def test_cpu1_and_cpu2_selections_are_independent_and_survive_disconnect(tmp_path) -> None:
    page, controller, backend, binding = setup()
    one, two = tmp_path / "one.txt", tmp_path / "two.txt"
    one.write_text("one")
    two.write_text("two")
    binding.select_image("cpu1", str(one))
    first_revision = backend.ram_image_revision("cpu1")
    binding.select_image("cpu2", str(two))

    assert page.cpu1_ram_image_edit.text() == str(one)
    assert page.cpu2_ram_image_edit.text() == str(two)
    assert backend.ram_image_revision("cpu1") == first_revision
    assert backend.ram_image_revision("cpu2") == 1

    apply(controller, backend, RuntimeSnapshot())
    assert page.cpu1_ram_image_edit.text() == str(one)
    assert page.cpu2_ram_image_edit.text() == str(two)


def test_prepared_summary_gates_current_target_capabilities(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.cache["cpu1"] = (object(), prepared_summary)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"), CPU1_PROFILE)

    assert page.ram_load_button.isEnabled()
    assert page.ram_crc_button.isEnabled()
    assert page.ram_run_button.isEnabled()

    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection("cpu2", "cpu2"), active_target_key="cpu2"), CPU2_PROFILE)
    assert not page.ram_load_button.isEnabled()
    assert not page.ram_crc_button.isEnabled()
    assert not page.ram_run_button.isEnabled()


def test_shared_result_rejects_stale_connection_target_revision_and_task(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.cache["cpu1"] = (object(), prepared_summary)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"), CPU1_PROFILE)
    binding.load()
    original = page.result_output.toPlainText()
    operation = OperationResult(True, "load_ram_image", CPU1_PROFILE.name, "RAM_LOAD_END", {})

    controller.taskFinished.emit(TaskExecutionResult("unknown", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=AdvancedRamOperationSnapshot("connection", "cpu1", 1, operation)))
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=AdvancedRamOperationSnapshot("old", "cpu1", 1, operation)))
    assert page.result_output.toPlainText() == original

    binding.load()
    page.cpu1_ram_image_edit.setText(str(path) + ".new")
    controller.taskFinished.emit(TaskExecutionResult("task-3", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=AdvancedRamOperationSnapshot("connection", "cpu1", 1, operation)))
    assert page.result_output.toPlainText() == original


def test_run_result_is_retained_after_controller_releases_connection(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.cache["cpu1"] = (object(), prepared_summary)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"), CPU1_PROFILE)
    binding.run()
    operation = OperationResult(True, "run_ram_image", CPU1_PROFILE.name, "RUN_RAM", {})

    apply(controller, backend, RuntimeSnapshot())
    controller.taskFinished.emit(TaskExecutionResult(
        "task-2",
        TaskFinalStatus.SUCCEEDED,
        "Run RAM Image",
        "RUN_RAM",
        payload=AdvancedRamOperationSnapshot("connection", "cpu1", 1, operation),
        completion_action=TaskCompletionAction.RELEASE_CONNECTION,
    ))

    assert '"operation": "run"' in page.result_output.toPlainText()
    assert '"connection_id": "connection"' in page.result_output.toPlainText()


def test_cleanup_failure_is_retained_after_disconnect_but_rejected_for_new_connection(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.cache["cpu1"] = (object(), prepared_summary)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    connected = RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1")
    apply(controller, backend, connected, CPU1_PROFILE)
    binding.load()
    error = GuiRuntimeError(
        "CANCELLATION_CLEANUP_FAILED",
        "cleanup failed",
        "RAM_LOAD_END",
        ErrorDisposition.ASK_DISCONNECT,
        "task-2",
        True,
        True,
    )
    failed = TaskExecutionResult("task-2", TaskFinalStatus.FAILED, "failed", "cleanup failed", error=error)

    apply(controller, backend, RuntimeSnapshot())
    controller.taskFinished.emit(failed)
    retained = page.result_output.toPlainText()
    assert "CANCELLATION_CLEANUP_FAILED" in retained

    apply(controller, backend, connected, CPU1_PROFILE)
    binding.load()
    apply(
        controller,
        backend,
        RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection("new"), active_target_key="cpu1"),
        CPU1_PROFILE,
    )
    controller.taskFinished.emit(TaskExecutionResult(
        "task-3",
        TaskFinalStatus.SUCCEEDED,
        "ok",
        "ok",
        payload=AdvancedRamOperationSnapshot(
            "connection",
            "cpu1",
            1,
            OperationResult(True, "load_ram_image", CPU1_PROFILE.name, "RAM_LOAD_END", {}),
        ),
    ))
    assert page.result_output.toPlainText() == retained


def test_source_change_invalidation_disables_ram_operations(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.cache["cpu1"] = (object(), prepared_summary)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"), CPU1_PROFILE)
    assert page.ram_load_button.isEnabled()
    binding.load()

    backend.cache.pop("cpu1")
    error = GuiRuntimeError("IMAGE_CHANGED", "changed", "load_ram_image", ErrorDisposition.SHOW_ONLY, "task-2")
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.FAILED, "failed", "changed", error=error))
    assert not page.ram_load_button.isEnabled()
    assert not page.ram_crc_button.isEnabled()
    assert not page.ram_run_button.isEnabled()
