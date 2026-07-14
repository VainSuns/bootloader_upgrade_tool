from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.flash_service_binding import FlashServiceBinding
from bootloader_upgrade_tool.gui.flash_service_models import PreparedFlashServiceSummary
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.pages.settings_page import SettingsPage
from bootloader_upgrade_tool.gui.runtime_models import (
    ErrorDisposition,
    GuiRuntimeError,
    RequestAdmission,
    RequestRejection,
    RequestRejectionCode,
    RuntimeSnapshot,
    TaskExecutionResult,
    TaskFinalStatus,
)


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self, *, accepted=True, emit_started=False):
        super().__init__()
        self._snapshot = RuntimeSnapshot()
        self.requests = []
        self.accepted = accepted
        self.emit_started = emit_started

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        self.requests.append(request)
        task_id = f"task-{len(self.requests)}"
        if not self.accepted:
            return RequestAdmission(False, rejection=RequestRejection(RequestRejectionCode.TASK_ALREADY_ACTIVE, "busy"))
        if self.emit_started:
            self.taskStarted.emit(SimpleNamespace(task_id=task_id))
        return RequestAdmission(True, task_id=task_id)


class Backend:
    configuration_revision = 0

    def __init__(self):
        self.invalidations = []

    def invalidate_prepared_service_image(self, revision):
        self.invalidations.append(revision)


@pytest.fixture(autouse=True)
def _qt_app():
    return QApplication.instance() or QApplication([])


def _setup(*, accepted=True, emit_started=False):
    settings, advanced = SettingsPage(), AdvancedPage()
    controller, backend = Controller(accepted=accepted, emit_started=emit_started), Backend()
    return settings, advanced, controller, backend, FlashServiceBinding(settings, advanced, controller, backend)


def _set_paths(settings, image: Path, map_file: Path) -> None:
    settings.cpu1_service_image.path_edit.setText(str(image))
    settings.cpu1_service_map.path_edit.setText(str(map_file))


@pytest.mark.parametrize("kind", ("image", "map"))
def test_service_browse_submits_only_selected_new_path(tmp_path, monkeypatch, kind) -> None:
    settings, _advanced, controller, _backend, _binding = _setup()
    old_image, old_map = tmp_path / "old.txt", tmp_path / "old.map"
    selected = tmp_path / ("new.txt" if kind == "image" else "new.map")
    _set_paths(settings, old_image, old_map)
    row = settings.cpu1_service_image if kind == "image" else settings.cpu1_service_map

    def pick(*_args):
        row.path_edit.editingFinished.emit()
        return str(selected), ""

    monkeypatch.setattr("bootloader_upgrade_tool.gui.flash_service_binding.QFileDialog.getOpenFileName", pick)
    row.browse_button.click()

    assert len(controller.requests) == 1
    request = controller.requests[0]
    assert request.service_image_path == str((selected if kind == "image" else old_image).resolve())
    assert request.service_map_path == str((selected if kind == "map" else old_map).resolve())


@pytest.mark.parametrize("kind", ("image", "map"))
def test_cancelled_service_browse_submits_nothing(tmp_path, monkeypatch, kind) -> None:
    settings, _advanced, controller, _backend, _binding = _setup()
    _set_paths(settings, tmp_path / "old.txt", tmp_path / "old.map")
    row = settings.cpu1_service_image if kind == "image" else settings.cpu1_service_map

    def cancel(*_args):
        row.path_edit.editingFinished.emit()
        return "", ""

    monkeypatch.setattr("bootloader_upgrade_tool.gui.flash_service_binding.QFileDialog.getOpenFileName", cancel)
    row.browse_button.click()
    assert controller.requests == []


def test_manual_editing_finished_still_prepares(tmp_path) -> None:
    settings, _advanced, controller, _backend, _binding = _setup()
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    _set_paths(settings, image, map_file)
    settings.cpu1_service_map.path_edit.editingFinished.emit()
    assert len(controller.requests) == 1


def test_service_start_clears_address_and_failure_keeps_it_unresolved(tmp_path) -> None:
    settings, _advanced, controller, _backend, binding = _setup(emit_started=True)
    settings.cpu1_descriptor_address.set_value("0x00009000")
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    _set_paths(settings, image, map_file)

    binding.prepare()
    unresolved = "Resolved from map/symbol; never hardcoded"
    assert settings.cpu1_descriptor_address.value_label.text() == unresolved
    error = GuiRuntimeError("FAILED", "failed", "prepare", ErrorDisposition.SHOW_ONLY, "task-1")
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.FAILED, "failed", "failed", error=error))
    assert settings.cpu1_descriptor_address.value_label.text() == unresolved


def test_rejected_service_preparation_keeps_existing_address(tmp_path) -> None:
    settings, _advanced, controller, _backend, binding = _setup(accepted=False)
    settings.cpu1_descriptor_address.set_value("0x00009000")
    _set_paths(settings, tmp_path / "new.txt", tmp_path / "new.map")
    binding.prepare()
    assert len(controller.requests) == 1
    assert settings.cpu1_descriptor_address.value_label.text() == "0x00009000"


def test_owned_success_still_updates_descriptor_address(tmp_path) -> None:
    settings, advanced, controller, _backend, binding = _setup()
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image"); map_file.write_text("map")
    _set_paths(settings, image, map_file)
    binding.prepare()
    request = controller.requests[0]
    fingerprint = lambda path: SourceFileFingerprint(str(path), path.stat().st_size, path.stat().st_mtime_ns)
    summary = PreparedFlashServiceSummary("cpu1", str(image), str(map_file), "", request.configuration_revision, 0, ImageSourceKind.TXT, fingerprint(image), fingerprint(map_file), 0x9000, 0x9010, 0x9020, 8, 1, Hex2000Source.NOT_USED, None)
    original = advanced.result_output.toPlainText()
    controller.taskFinished.emit(TaskExecutionResult("other", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=summary))
    assert advanced.result_output.toPlainText() == original
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=summary))
    assert settings.cpu1_descriptor_address.value_label.text() == "0x00009000"
