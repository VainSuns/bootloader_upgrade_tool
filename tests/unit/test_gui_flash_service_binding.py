import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.app_resources import AppResourceNotFoundError
from bootloader_upgrade_tool.gui import flash_service_binding as binding_module
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
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.gui.runtime_v2_events import SessionChanged


class Provider:
    def __init__(self, image: Path, map_file: Path, error=None):
        self.image, self.map_file, self.error = image.resolve(), map_file.resolve(), error

    def flash_service_image_path(self):
        if self.error:
            raise self.error
        return self.image

    def flash_service_map_path(self):
        if self.error:
            raise self.error
        return self.map_file


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self, *, accepted=True, emit_started=False):
        super().__init__()
        self.snapshot = RuntimeSnapshot()
        self.requests = []
        self.accepted = accepted
        self.emit_started = emit_started

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
    service_configuration_revision = 0

    def __init__(self):
        self.invalidations = []
        self.listeners = []

    def invalidate_prepared_service_image(self, revision):
        self.service_configuration_revision = revision
        self.invalidations.append(revision)

    def subscribe_runtime_v2(self, listener):
        self.listeners.append(listener)

    def unsubscribe_runtime_v2(self, listener):
        self.listeners.remove(listener)


@pytest.fixture(autouse=True)
def _qt_app():
    return QApplication.instance() or QApplication([])


def _setup(tmp_path, *, accepted=True, emit_started=False, error=None):
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image", encoding="utf-8")
    map_file.write_text("map", encoding="utf-8")
    settings, advanced = SettingsPage(), AdvancedPage()
    controller, backend = Controller(accepted=accepted, emit_started=emit_started), Backend()
    provider = Provider(image, map_file, error)
    binding = FlashServiceBinding(settings, advanced, controller, backend, provider)
    return settings, advanced, controller, backend, provider, binding


def _fingerprint(path: Path) -> SourceFileFingerprint:
    return SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)


def _summary(provider, request, address=0x9000):
    return PreparedFlashServiceSummary(
        "cpu1", str(provider.image), str(provider.map_file), "",
        request.configuration_revision, request.tool_configuration_revision,
        ImageSourceKind.TXT, _fingerprint(provider.image), _fingerprint(provider.map_file),
        address, 0x9010, 0x9020, 8, 1, Hex2000Source.NOT_USED, None,
    )


def test_provider_populates_read_only_rows_and_no_file_dialog_or_cpu2_state(tmp_path) -> None:
    settings, _advanced, _controller, _backend, provider, _binding = _setup(tmp_path)
    assert settings.flash_service_provider.value_label.text() == "Provider"
    assert settings.flash_service_image.value_label.text() == str(provider.image)
    assert settings.flash_service_map.value_label.text() == str(provider.map_file)
    assert settings.flash_service_descriptor_symbol.value_label.text() == "g_boot_flash_service_descriptor"
    assert not hasattr(binding_module, "QFileDialog")
    assert not hasattr(settings, "cpu2_service_image")


def test_prepare_button_submits_provider_paths_and_empty_symbol(tmp_path) -> None:
    settings, _advanced, controller, _backend, provider, _binding = _setup(tmp_path)
    settings.flash_service_prepare_button.click()
    request = controller.requests[0]
    assert (request.service_image_path, request.service_map_path) == (str(provider.image), str(provider.map_file))
    assert request.descriptor_symbol == ""


def test_provider_error_submits_no_task_and_shows_structured_unavailable_result(tmp_path) -> None:
    error = AppResourceNotFoundError("missing service")
    settings, advanced, controller, _backend, _provider, binding = _setup(tmp_path, error=error)
    assert not settings.flash_service_prepare_button.isEnabled()
    binding.prepare()
    result = json.loads(advanced.result_output.toPlainText())
    assert controller.requests == []
    assert settings.flash_service_status.value_label.text() == "Unavailable"
    assert result["error"]["code"] == "AppResourceNotFoundError"


def test_success_failure_and_stale_results_update_only_owned_current_task(tmp_path) -> None:
    settings, advanced, controller, _backend, provider, binding = _setup(tmp_path, emit_started=True)
    binding.prepare()
    request = controller.requests[0]
    summary = _summary(provider, request)
    original = advanced.result_output.toPlainText()
    controller.taskFinished.emit(TaskExecutionResult("other", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=summary))
    assert advanced.result_output.toPlainText() == original
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=summary))
    assert settings.flash_service_status.value_label.text() == "Ready"
    assert settings.flash_service_descriptor_address.value_label.text() == "0x00009000"

    binding.prepare()
    error = GuiRuntimeError("FAILED", "failed", "prepare", ErrorDisposition.SHOW_ONLY, "task-2")
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.FAILED, "failed", "failed", error=error))
    assert settings.flash_service_status.value_label.text() == "Failed"


def test_runtime_gate_tool_change_and_session_change_reset_without_task(tmp_path) -> None:
    settings, _advanced, controller, backend, _provider, binding = _setup(tmp_path)
    assert settings.flash_service_prepare_button.isEnabled()
    controller.snapshot = RuntimeSnapshot(RuntimeState.BUSY, active_task_id="busy")
    controller.runtimeStateChanged.emit(controller.snapshot)
    assert not settings.flash_service_prepare_button.isEnabled()
    controller.snapshot = RuntimeSnapshot()
    binding.tool_configuration_changed()
    assert settings.flash_service_status.value_label.text() == "Not prepared"
    before = len(controller.requests)
    backend.listeners[0](SimpleNamespace(source_event=SessionChanged()))
    assert len(controller.requests) == before
    assert backend.invalidations == [1]
    assert settings.flash_service_descriptor_address.value_label.text() == "Not prepared"


def test_binding_unsubscribes_runtime_listener(tmp_path) -> None:
    _settings, _advanced, _controller, backend, _provider, binding = _setup(tmp_path)
    assert backend.listeners
    binding.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert backend.listeners == []
