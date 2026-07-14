from datetime import datetime, timezone
from pathlib import Path

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
    RequestAdmission,
    RuntimeSnapshot,
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.images import PreparedRamImage
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


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
        self.invalidations = []
        self.cache = {}

    def invalidate_prepared_ram_image(self, target, revision):
        self.invalidations.append((target, revision))
        self.cache.pop(target, None)

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
    QApplication.instance() or QApplication([])
    page = AdvancedPage()
    controller = Controller()
    backend = Backend()
    binding = AdvancedRamBinding(page, controller, backend)
    return page, controller, backend, binding


def test_cpu1_and_cpu2_selections_are_independent_and_survive_disconnect(tmp_path) -> None:
    page, controller, backend, binding = setup()
    one, two = tmp_path / "one.txt", tmp_path / "two.txt"
    one.write_text("one")
    two.write_text("two")
    binding.select_image("cpu1", str(one))
    first_revision = binding._revisions["cpu1"]
    binding.select_image("cpu2", str(two))

    assert page.cpu1_ram_image_edit.text() == str(one)
    assert page.cpu2_ram_image_edit.text() == str(two)
    assert binding._revisions == {"cpu1": first_revision, "cpu2": 1}
    assert backend.invalidations == [("cpu1", 1), ("cpu2", 1)]

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
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"), CPU1_PROFILE)
    binding.load()
    original = page.result_output.toPlainText()
    operation = OperationResult(True, "load_ram_image", CPU1_PROFILE.name, "RAM_LOAD_END", {})

    controller.taskFinished.emit(TaskExecutionResult("unknown", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=AdvancedRamOperationSnapshot("connection", "cpu1", 1, operation)))
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=AdvancedRamOperationSnapshot("old", "cpu1", 1, operation)))
    assert page.result_output.toPlainText() == original

    binding.load()
    binding._selection_changed("cpu1")
    controller.taskFinished.emit(TaskExecutionResult("task-3", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=AdvancedRamOperationSnapshot("connection", "cpu1", 1, operation)))
    assert page.result_output.toPlainText() == original
