from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

import pytest
from PySide6.QtCore import QObject, Signal
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
    RuntimeSnapshot,
    RuntimeState,
    TaskCompletionAction,
    TaskExecutionResult,
    TaskFinalStatus,
)
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

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        self.requests.append(request)
        return RequestAdmission(True, task_id=f"task-{len(self.requests)}")


class Backend:
    def __init__(self):
        self.active_target = None
        self.cache = {}
        self._revisions = {cpu: 0 for cpu in RuntimeCpuId}
        self._dispatcher = DomainEventDispatcher(RuntimeStateStore())

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
        cpu = RuntimeCpuId.from_target_key(target)
        assert revision == self._revisions[cpu]
        resource = self.target_resources[cpu]
        return self._dispatcher.dispatch(
            RamImageChanged(cpu, resource.ram_image_path, ImageParseStatus.PARSING)
        )

    def fail_ram_image_parse(self, target, path, revision, code, message):
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


def setup():
    page = AdvancedPage()
    controller = Controller()
    backend = Backend()
    binding = AdvancedRamBinding(page, controller, backend)
    return page, controller, backend, binding


def test_worker_thread_ram_transition_renders_on_gui_thread(app, tmp_path) -> None:
    page, _controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.cache["cpu1"] = (object(), prepared_summary)

    worker = Thread(target=lambda: backend.ready(prepared_summary))
    worker.start()
    worker.join()
    for _ in range(10):
        app.processEvents()
        if page.cpu1_ram_entry_point_value.text() == "0x00008000":
            break

    assert page.cpu1_ram_entry_point_value.text() == "0x00008000"
    assert page.cpu1_ram_image_size_value.text() == "3 words"


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
