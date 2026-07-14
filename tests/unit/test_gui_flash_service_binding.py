from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.flash_service_binding import FlashServiceBinding
from bootloader_upgrade_tool.gui.flash_service_models import PreparedFlashServiceSummary
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.pages.settings_page import SettingsPage
from bootloader_upgrade_tool.gui.runtime_models import RequestAdmission, RuntimeSnapshot, TaskExecutionResult, TaskFinalStatus


class Controller(QObject):
    runtimeStateChanged = Signal(object); taskStarted = Signal(object); taskFinished = Signal(object)
    def __init__(self): super().__init__(); self._snapshot = RuntimeSnapshot(); self.requests = []
    @property
    def snapshot(self): return self._snapshot
    def request_task(self, request): self.requests.append(request); return RequestAdmission(True, task_id=f"task-{len(self.requests)}")


class Backend:
    configuration_revision = 0
    def __init__(self): self.invalidations = []
    def invalidate_prepared_service_image(self, revision): self.invalidations.append(revision)


def test_required_inputs_prepare_and_only_current_owned_result_updates_address(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    settings, advanced, controller, backend = SettingsPage(), AdvancedPage(), Controller(), Backend()
    binding = FlashServiceBinding(settings, advanced, controller, backend)
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image"); map_file.write_text("map")
    settings.cpu1_service_image.path_edit.setText(str(image))
    assert not controller.requests
    settings.cpu1_service_map.path_edit.setText(str(map_file))
    binding.prepare()
    request = controller.requests[0]
    assert request.descriptor_symbol == ""

    fingerprint = lambda path: SourceFileFingerprint(str(path), path.stat().st_size, path.stat().st_mtime_ns)
    summary = PreparedFlashServiceSummary("cpu1", str(image), str(map_file), "", request.configuration_revision, 0, ImageSourceKind.TXT, fingerprint(image), fingerprint(map_file), 0x9000, 0x9010, 0x9020, 8, 1, Hex2000Source.NOT_USED, None)
    original = advanced.result_output.toPlainText()
    controller.taskFinished.emit(TaskExecutionResult("other", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=summary))
    assert advanced.result_output.toPlainText() == original
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=summary))
    assert settings.cpu1_descriptor_address.value_label.text() == "0x00009000"
    assert not settings.cpu2_service_image.isEnabled()
