from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.app import GuiLaunchOptions, create_main_window
from bootloader_upgrade_tool.gui.image_preparation_models import (
    Hex2000Source,
    ImageSourceKind,
    PreparedImageSummary,
    SourceFileFingerprint,
)
from bootloader_upgrade_tool.gui.pages.program_page import ProgramTargetPage
from bootloader_upgrade_tool.gui.program_image_binding import ProgramImageBinding
from bootloader_upgrade_tool.gui.runtime_models import (
    ErrorDisposition,
    GuiRuntimeError,
    RequestAdmission,
    RuntimeSnapshot,
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Backend:
    def __init__(self) -> None:
        self.invalidations: list[int] = []

    def invalidate_prepared_image_cache(self, revision: int) -> None:
        self.invalidations.append(revision)


class _Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.snapshot = RuntimeSnapshot()
        self.requests = []

    def request_task(self, request):
        self.requests.append(request)
        return RequestAdmission(True, task_id=f"task-{len(self.requests)}")


def _summary(path: Path, revision: int) -> PreparedImageSummary:
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


def test_browse_editing_finished_duplicate_and_force_triggers(tmp_path: Path) -> None:
    app = qt_app()
    page = ProgramTargetPage("cpu1")
    controller = _Controller()
    backend = _Backend()
    binding = ProgramImageBinding(page, controller, backend, file_picker=lambda _parent: tmp_path / "app.txt")

    page.image_path_row.browse_button.click()
    page.image_path_row.path_edit.editingFinished.emit()
    page.prepare_image_button.click()

    assert len(controller.requests) == 2
    assert controller.requests[0].selection_revision == controller.requests[1].selection_revision
    assert page.parse_status_row.badge.text() == "Parsing"
    assert binding.selection_revision == 1

    page.close()
    app.processEvents()


def test_path_change_clears_summary_and_stale_result_is_ignored(tmp_path: Path) -> None:
    app = qt_app()
    page = ProgramTargetPage("cpu1")
    controller = _Controller()
    backend = _Backend()
    binding = ProgramImageBinding(page, controller, backend)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    page.image_path_row.path_edit.setText(str(first))
    page.image_path_row.path_edit.editingFinished.emit()
    old_revision = binding.selection_revision
    page.image_path_row.path_edit.setText(str(second))

    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=_summary(first, old_revision),
        )
    )

    assert page.parse_status_row.badge.text() == "Not parsed"
    assert page.details_edit.toPlainText() == ""
    assert backend.invalidations == [1, 2]

    page.close()
    app.processEvents()


def test_parsed_and_failed_results_update_cpu1_only(tmp_path: Path) -> None:
    app = qt_app()
    page = ProgramTargetPage("cpu1")
    controller = _Controller()
    binding = ProgramImageBinding(page, controller, _Backend())
    path = tmp_path / "app.txt"
    page.image_path_row.path_edit.setText(str(path))
    page.image_path_row.path_edit.editingFinished.emit()
    summary = _summary(path, binding.selection_revision)

    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=summary))
    assert page.parse_status_row.badge.text() == "Parsed"
    assert page.entry_point_row.value_label.text() == "0x00082400"
    assert "Touched sectors: B" in page.details_edit.toPlainText()

    page.prepare_image_button.click()
    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-2",
            TaskFinalStatus.FAILED,
            "failed",
            "failed",
            error=GuiRuntimeError(
                "IMAGE_PARSE_FAILED",
                "bad SCI8",
                "prepare_flash_image",
                ErrorDisposition.SHOW_ONLY,
                "task-2",
                True,
                details={"selection_revision": binding.selection_revision},
            ),
        )
    )
    assert page.parse_status_row.badge.text() == "Parse failed"
    assert "IMAGE_PARSE_FAILED" in page.details_edit.toPlainText()
    assert not page.force_load_checkbox.isEnabled()
    assert not page.auto_run_checkbox.isEnabled()
    assert not page.confirm_app_checkbox.isEnabled()

    page.close()
    app.processEvents()


def test_image_controls_follow_disconnected_cleanup_and_task_state() -> None:
    app = qt_app()
    page = ProgramTargetPage("cpu1")
    controller = _Controller()
    binding = ProgramImageBinding(page, controller, _Backend())
    assert page.image_path_row.path_edit.isEnabled()

    controller.snapshot = RuntimeSnapshot(RuntimeState.BUSY, active_task_id="task")
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert not page.image_path_row.path_edit.isEnabled()

    controller.snapshot = RuntimeSnapshot(RuntimeState.DISCONNECTED, cleanup_pending=True)
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert not page.image_path_row.browse_button.isEnabled()

    page.close()
    app.processEvents()


def test_binding_rejects_cpu2_and_layout_preview_does_not_load_settings(monkeypatch) -> None:
    app = qt_app()
    with pytest.raises(ValueError, match="CPU1"):
        ProgramImageBinding(ProgramTargetPage("cpu2"), _Controller(), _Backend())

    import bootloader_upgrade_tool.gui.app as app_module

    monkeypatch.setattr(app_module, "load_global_settings", lambda: (_ for _ in ()).throw(AssertionError("loaded")))
    window = create_main_window(GuiLaunchOptions(layout_preview=True))
    assert not hasattr(window, "program_image_binding")
    window.close()
    app.processEvents()
