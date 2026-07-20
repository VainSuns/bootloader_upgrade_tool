import inspect
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_flash_binding import AdvancedFlashBinding
from bootloader_upgrade_tool.gui.advanced_flash_operation_binding import AdvancedFlashOperationBinding
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, GuiTaskWarning, RuntimeSnapshot
from bootloader_upgrade_tool.gui.runtime_v2_events import (
    ConnectionClosed, ConnectionOpened, OperationSucceeded, ProgramImageChanged,
    RuntimeOperationType,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration,
    FlashImageSummary,
    ImageParseStatus,
    RuntimeCpuId,
    VerifyEvidence,
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


def test_advanced_flash_shared_result_refresh_fields_and_warning_details() -> None:
    source = inspect.getsource(AdvancedFlashOperationBinding._task_finished)
    assert all(
        f'"{field}"' in source
        for field in (
            "result", "metadata_refresh_result", "metadata_summary", "warning"
        )
    )
    warning = GuiTaskWarning(
        "METADATA_REFRESH_FAILED",
        "refresh failed",
        "GET_METADATA_SUMMARY",
        {
            "primary_operation": "program_flash_image",
            "refresh_error_code": "READ_FAILED",
            "metadata_freshness": "stale",
            "primary_retry_performed": False,
        },
    )
    assert AdvancedFlashOperationBinding._plain_warning(warning) == {
        "code": "METADATA_REFRESH_FAILED",
        "message": "refresh failed",
        "stage": "GET_METADATA_SUMMARY",
        "details": {
            "primary_operation": "program_flash_image",
            "refresh_error_code": "READ_FAILED",
            "metadata_freshness": "stale",
            "primary_retry_performed": False,
        },
    }


def test_controls_are_permanently_read_only() -> None:
    page, controller, _backend, _binding = _setup()
    assert page.cpu1_flash_image_edit.isReadOnly()
    assert page.cpu2_flash_image_edit.isReadOnly()
    assert page.cpu1_flash_browse_button.isEnabled()
    assert page.cpu2_flash_browse_button.isEnabled()
    assert "Program page" in page.cpu1_flash_browse_button.toolTip()
    assert "Program page" in page.cpu2_flash_browse_button.toolTip()
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
    assert page.cpu1_flash_app_end_value.text() == "—"
    assert page.cpu1_flash_image_size_value.text() == "—"
    assert page.cpu1_flash_crc32_value.text() == "—"
    assert page.cpu1_flash_verify_value.text() == "—"
    assert page.cpu1_flash_parse_status_value.text() == {
        ImageParseStatus.EMPTY: "Not parsed",
        ImageParseStatus.PARSING: "Parsing",
        ImageParseStatus.ERROR: "Error",
    }[status]


@pytest.mark.parametrize("cpu_id", tuple(RuntimeCpuId))
def test_verify_display_is_cpu_generic_and_connection_current(cpu_id, tmp_path) -> None:
    page, _controller, backend, _binding = _setup()
    identity = ImageIdentity(0x82400, 8, 0x12345678, 0x82408)
    info = ConnectionInfo(
        "connection", "SCI", "COM3", datetime.now(timezone.utc), cpu_id.value
    )
    backend._runtime_v2_dispatcher.dispatch(ConnectionOpened(info))
    backend._runtime_v2_dispatcher.dispatch(ProgramImageChanged(
        cpu_id, str(tmp_path / "app.txt"), ImageParseStatus.READY,
        FlashImageSummary(identity, 2),
    ))
    value = (
        page.cpu1_flash_verify_value
        if cpu_id is RuntimeCpuId.CPU1
        else page.cpu2_flash_verify_value
    )
    assert value.text() == "Not verified"
    backend._runtime_v2_dispatcher.dispatch(OperationSucceeded(
        "verify", RuntimeOperationType.VERIFY, cpu_id,
        backend.connection_generation, identity,
    ))
    assert value.text() == "Verified"
    connection = backend.runtime_v2_snapshot.connection
    backend._runtime_v2_dispatcher.dispatch(
        ConnectionClosed(connection.connection_id, connection.generation)
    )
    assert value.text() == "Not verified"


@pytest.mark.parametrize(
    "evidence",
    (
        VerifyEvidence(
            RuntimeCpuId.CPU2, ConnectionGeneration(1),
            ImageIdentity(0x82400, 8, 0x12345678, 0x82408), "wrong-cpu"
        ),
        VerifyEvidence(
            RuntimeCpuId.CPU1, ConnectionGeneration(2),
            ImageIdentity(0x82400, 8, 0x12345678, 0x82408), "stale"
        ),
        VerifyEvidence(
            RuntimeCpuId.CPU1, ConnectionGeneration(1),
            ImageIdentity(0x82400, 8, 0x9999, 0x82408), "mismatch"
        ),
    ),
)
def test_nonmatching_evidence_displays_not_verified(evidence, tmp_path) -> None:
    page, _controller, backend, binding = _setup()
    identity = ImageIdentity(0x82400, 8, 0x12345678, 0x82408)
    backend._runtime_v2_dispatcher.dispatch(ConnectionOpened(ConnectionInfo(
        "connection", "SCI", "COM3", datetime.now(timezone.utc), "cpu1"
    )))
    state = SimpleNamespace(
        program_image_path=str(tmp_path / "app.txt"),
        program_image_summary=FlashImageSummary(identity, 2),
        program_image_parse_status=ImageParseStatus.READY,
        verify_evidence=evidence,
    )
    binding._render({
        RuntimeCpuId.CPU1: state,
        RuntimeCpuId.CPU2: backend.target_resources[RuntimeCpuId.CPU2],
    })
    assert page.cpu1_flash_verify_value.text() == "Not verified"


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
    listener = binding._runtime_v2_listener
    binding.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert listener not in backend._runtime_v2_dispatcher._listeners
    binding._unsubscribe()


def test_advanced_runtime_transition_from_worker_is_queued_to_gui_thread(tmp_path) -> None:
    app = QApplication.instance()
    page, _controller, backend, binding = _setup()
    gui_thread = app.thread()
    listener_threads = []
    widget_threads = []
    backend.subscribe_runtime_v2(lambda _result: listener_threads.append(QThread.currentThread()))
    original = page.set_cpu1_flash_image_summary

    def record_widget_thread(**values):
        widget_threads.append(QThread.currentThread())
        original(**values)

    page.set_cpu1_flash_image_summary = record_widget_thread
    path = str(tmp_path / "worker.txt")
    worker = threading.Thread(target=lambda: backend.set_program_image_path("cpu1", path))
    worker.start()
    worker.join()

    assert listener_threads[-1] != gui_thread
    assert page.cpu1_flash_image_edit.text() == ""
    assert widget_threads == []
    app.processEvents()
    assert page.cpu1_flash_image_edit.text() == path
    assert widget_threads[-1] == gui_thread == binding.thread()
