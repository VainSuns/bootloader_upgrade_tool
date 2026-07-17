import inspect

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_flash_binding import AdvancedFlashBinding
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import RuntimeSnapshot
from bootloader_upgrade_tool.gui.runtime_v2_events import ProgramImageChanged
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    FlashImageSummary,
    ImageParseStatus,
    RuntimeCpuId,
)
from bootloader_upgrade_tool.images import ImageIdentity


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self):
        super().__init__()
        self.snapshot = RuntimeSnapshot()
        self.requests = []

    def request_task(self, request):
        self.requests.append(request)
        raise AssertionError("Advanced adapter must not submit tasks")


@pytest.fixture(scope="module", autouse=True)
def _qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _setup():
    page, controller, backend = AdvancedPage(), Controller(), RuntimeBackend()
    return page, controller, backend, AdvancedFlashBinding(page, controller, backend)


def test_adapter_has_no_picker_timer_or_task_route() -> None:
    source = inspect.getsource(AdvancedFlashBinding)
    assert "QFileDialog" not in source
    assert "QTimer" not in source
    assert "request_task" not in source
    assert "_revisions" not in source


def test_controls_are_permanently_read_only() -> None:
    page, controller, _backend, _binding = _setup()
    assert page.cpu1_flash_image_edit.isReadOnly()
    assert page.cpu2_flash_image_edit.isReadOnly()
    assert not page.cpu1_flash_browse_button.isEnabled()
    assert not page.cpu2_flash_browse_button.isEnabled()
    assert controller.requests == []


@pytest.mark.parametrize("cpu_id", tuple(RuntimeCpuId))
def test_ready_resource_renders_only_matching_target(cpu_id, tmp_path) -> None:
    page, _controller, backend, _binding = _setup()
    path = str(tmp_path / f"{cpu_id.value}.txt")
    backend._runtime_v2_dispatcher.dispatch(
        ProgramImageChanged(
            cpu_id,
            path,
            ImageParseStatus.READY,
            FlashImageSummary(ImageIdentity(0x82400, 8, 0x12345678, 0x82408), 2),
        )
    )
    edit = page.cpu1_flash_image_edit if cpu_id is RuntimeCpuId.CPU1 else page.cpu2_flash_image_edit
    other = page.cpu2_flash_image_edit if cpu_id is RuntimeCpuId.CPU1 else page.cpu1_flash_image_edit
    entry = page.cpu1_flash_entry_point_value if cpu_id is RuntimeCpuId.CPU1 else page.cpu2_flash_entry_point_value
    assert edit.text() == path and other.text() == ""
    assert entry.text() == "0x00082400"


@pytest.mark.parametrize("status", (ImageParseStatus.EMPTY, ImageParseStatus.PARSING, ImageParseStatus.ERROR))
def test_non_ready_states_clear_legacy_summary(status, tmp_path) -> None:
    page, _controller, backend, _binding = _setup()
    path = "" if status is ImageParseStatus.EMPTY else str(tmp_path / "app.txt")
    backend._runtime_v2_dispatcher.dispatch(
        ProgramImageChanged(
            RuntimeCpuId.CPU1,
            path,
            status,
            parse_error="failed" if status is ImageParseStatus.ERROR else None,
        )
    )
    assert page.cpu1_flash_entry_point_value.text() == "—"
    assert page.cpu1_flash_image_size_value.text() == "—"
    assert page.cpu1_flash_crc32_value.text() == "—"


def test_configuration_change_only_rerenders_backend_state(tmp_path) -> None:
    page, controller, backend, binding = _setup()
    path = str(tmp_path / "app.txt")
    backend.set_program_image_path("cpu1", path)
    page.cpu1_flash_image_edit.clear()
    binding.configuration_changed()
    assert page.cpu1_flash_image_edit.text() == path
    assert controller.requests == []


def test_session_change_clears_both_displays(tmp_path) -> None:
    page, _controller, backend, _binding = _setup()
    backend.set_program_image_path("cpu1", str(tmp_path / "one.txt"))
    backend.set_program_image_path("cpu2", str(tmp_path / "two.txt"))
    backend.apply_session_change()
    assert page.cpu1_flash_image_edit.text() == ""
    assert page.cpu2_flash_image_edit.text() == ""


def test_listener_unsubscribes() -> None:
    _page, _controller, backend, binding = _setup()
    listener = binding._runtime_transitioned
    binding._unsubscribe()
    assert listener not in backend._runtime_v2_dispatcher._listeners
