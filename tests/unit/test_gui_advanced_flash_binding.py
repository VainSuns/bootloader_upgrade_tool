from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_flash_binding import AdvancedFlashBinding
from bootloader_upgrade_tool.gui.advanced_flash_models import PreparedAdvancedFlashImageSummary
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
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

    def invalidate_prepared_advanced_flash_image(self, target, revision):
        self.invalidations.append((target, revision))


@pytest.fixture(autouse=True)
def _qt_app():
    return QApplication.instance() or QApplication([])


def _setup(*, accepted=True, emit_started=False):
    page, controller, backend = AdvancedPage(), Controller(accepted=accepted, emit_started=emit_started), Backend()
    return page, controller, backend, AdvancedFlashBinding(page, controller, backend)


def _summary(path: Path, target: str, revision: int) -> PreparedAdvancedFlashImageSummary:
    fingerprint = SourceFileFingerprint(str(path), path.stat().st_size, path.stat().st_mtime_ns)
    return PreparedAdvancedFlashImageSummary(target, str(path), revision, 0, ImageSourceKind.TXT, fingerprint, 0x82400, 8, 1, 0x82408, 2, 2, Hex2000Source.NOT_USED, None)


@pytest.mark.parametrize("target", ("cpu1", "cpu2"))
def test_browse_submits_only_selected_new_path(tmp_path, monkeypatch, target) -> None:
    page, controller, _backend, _binding = _setup()
    edit = page.cpu1_flash_image_edit if target == "cpu1" else page.cpu2_flash_image_edit
    button = page.cpu1_flash_browse_button if target == "cpu1" else page.cpu2_flash_browse_button
    old, selected = tmp_path / f"old-{target}.txt", tmp_path / f"new-{target}.txt"
    edit.setText(str(old))

    def pick(*_args):
        return str(selected), ""

    monkeypatch.setattr("bootloader_upgrade_tool.gui.advanced_flash_binding.QFileDialog.getOpenFileName", pick)
    edit.editingFinished.emit()
    button.click()
    QApplication.processEvents()

    assert len(controller.requests) == 1
    assert controller.requests[0].target_key == target
    assert controller.requests[0].source_path == str(selected.resolve())


def test_cancelled_browse_submits_nothing(tmp_path, monkeypatch) -> None:
    page, controller, _backend, _binding = _setup()
    page.cpu1_flash_image_edit.setText(str(tmp_path / "old.txt"))

    def cancel(*_args):
        return "", ""

    monkeypatch.setattr("bootloader_upgrade_tool.gui.advanced_flash_binding.QFileDialog.getOpenFileName", cancel)
    page.cpu1_flash_image_edit.editingFinished.emit()
    page.cpu1_flash_browse_button.click()
    QApplication.processEvents()
    assert controller.requests == []


def test_manual_editing_finished_still_prepares(tmp_path) -> None:
    page, controller, _backend, _binding = _setup()
    path = tmp_path / "manual.txt"
    page.cpu1_flash_image_edit.setText(str(path))
    page.cpu1_flash_image_edit.editingFinished.emit()
    QApplication.processEvents()
    assert controller.requests[0].source_path == str(path.resolve())


def test_started_flash_task_clears_only_matching_summary_and_failure_keeps_it_cleared(tmp_path) -> None:
    page, controller, _backend, binding = _setup(emit_started=True)
    page.set_cpu1_flash_image_summary(entry_point="CPU1", image_size="8 words", crc32="CRC1")
    page.set_cpu2_flash_image_summary(entry_point="CPU2", image_size="16 words", crc32="CRC2")
    path = tmp_path / "cpu1.txt"

    binding.select_image("cpu1", str(path))
    assert page.cpu1_flash_entry_point_value.text() == "—"
    assert page.cpu1_flash_image_size_value.text() == "—"
    assert page.cpu1_flash_crc32_value.text() == "—"
    assert page.cpu2_flash_entry_point_value.text() == "CPU2"
    assert page.cpu2_flash_image_size_value.text() == "16 words"
    assert page.cpu2_flash_crc32_value.text() == "CRC2"

    error = GuiRuntimeError("FAILED", "failed", "prepare", ErrorDisposition.SHOW_ONLY, "task-1")
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.FAILED, "failed", "failed", error=error))
    assert page.cpu1_flash_entry_point_value.text() == "—"
    assert page.cpu1_flash_image_size_value.text() == "—"
    assert page.cpu1_flash_crc32_value.text() == "—"


def test_rejected_flash_preparation_keeps_existing_summary(tmp_path) -> None:
    page, controller, _backend, binding = _setup(accepted=False)
    page.set_cpu1_flash_image_summary(entry_point="VALID", image_size="8 words", crc32="CRC")
    binding.select_image("cpu1", str(tmp_path / "new.txt"))
    assert len(controller.requests) == 1
    assert page.cpu1_flash_entry_point_value.text() == "VALID"
    assert page.cpu1_flash_image_size_value.text() == "8 words"
    assert page.cpu1_flash_crc32_value.text() == "CRC"


def test_owned_success_and_stale_task_handling_remain_independent(tmp_path) -> None:
    page, controller, _backend, binding = _setup()
    one, two = tmp_path / "one.txt", tmp_path / "two.txt"
    one.write_text("one"); two.write_text("two")
    binding.select_image("cpu1", str(one)); binding.select_image("cpu2", str(two))
    original = page.result_output.toPlainText()
    controller.taskFinished.emit(TaskExecutionResult("unknown", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=_summary(one, "cpu1", 1)))
    assert page.result_output.toPlainText() == original
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=_summary(one, "cpu1", 1)))
    assert page.cpu1_flash_entry_point_value.text() == "0x00082400"
