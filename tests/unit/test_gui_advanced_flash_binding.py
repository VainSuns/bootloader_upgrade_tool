from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_flash_binding import AdvancedFlashBinding
from bootloader_upgrade_tool.gui.advanced_flash_models import PreparedAdvancedFlashImageSummary
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.runtime_models import RequestAdmission, RuntimeSnapshot, TaskExecutionResult, TaskFinalStatus


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self):
        super().__init__(); self._snapshot = RuntimeSnapshot(); self.requests = []

    @property
    def snapshot(self): return self._snapshot

    def request_task(self, request):
        self.requests.append(request); return RequestAdmission(True, task_id=f"task-{len(self.requests)}")


class Backend:
    configuration_revision = 0
    def __init__(self): self.invalidations = []
    def invalidate_prepared_advanced_flash_image(self, target, revision): self.invalidations.append((target, revision))


def _summary(path: Path, target: str, revision: int) -> PreparedAdvancedFlashImageSummary:
    fingerprint = SourceFileFingerprint(str(path), path.stat().st_size, path.stat().st_mtime_ns)
    return PreparedAdvancedFlashImageSummary(target, str(path), revision, 0, ImageSourceKind.TXT, fingerprint, 0x82400, 8, 1, 0x82408, 2, 2, Hex2000Source.NOT_USED, None)


def test_paths_revisions_results_and_stale_task_are_independent(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    page, controller, backend = AdvancedPage(), Controller(), Backend()
    binding = AdvancedFlashBinding(page, controller, backend)
    one, two = tmp_path / "one.txt", tmp_path / "two.txt"
    one.write_text("one"); two.write_text("two")

    binding.select_image("cpu1", str(one)); binding.select_image("cpu2", str(two))
    assert backend.invalidations == [("cpu1", 1), ("cpu2", 1)]
    assert [request.target_key for request in controller.requests] == ["cpu1", "cpu2"]

    original = page.result_output.toPlainText()
    controller.taskFinished.emit(TaskExecutionResult("unknown", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=_summary(one, "cpu1", 1)))
    assert page.result_output.toPlainText() == original
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=_summary(one, "cpu1", 1)))
    assert page.cpu1_flash_entry_point_value.text() == "0x00082400"
    assert page.cpu2_flash_entry_point_value.text() == "—"

    page.cpu1_flash_image_edit.setText(str(tmp_path / "new.txt"))
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=_summary(two, "cpu2", 1)))
    assert page.cpu2_flash_entry_point_value.text() == "0x00082400"
