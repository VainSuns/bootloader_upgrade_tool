import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.app_resources import AppResourceNotFoundError
from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.flash_service_binding import FlashServiceBinding
from bootloader_upgrade_tool.gui.flash_service_models import FlashServiceResourceStatus
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.pages.settings_page import SettingsPage
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import (
    ErrorDisposition, GuiRuntimeError,
    RequestAdmission, RequestRejection, RequestRejectionCode, RuntimeSnapshot,
    RuntimeState, TaskExecutionResult, TaskFinalStatus,
)
from bootloader_upgrade_tool.images import PreparedServiceImage


class Provider:
    def __init__(self, image: Path, map_file: Path):
        self.image, self.map_file = image.resolve(), map_file.resolve()
        self.error = None

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

    def __init__(self):
        super().__init__()
        self.snapshot = RuntimeSnapshot()
        self.requests = []
        self.accepted = True
        self.admission_error = None
        self.exception = None

    def request_task(self, request):
        self.requests.append(request)
        if self.exception:
            raise self.exception
        if self.admission_error:
            return RequestAdmission(False, error=self.admission_error)
        if not self.accepted:
            return RequestAdmission(False, rejection=RequestRejection(RequestRejectionCode.TASK_ALREADY_ACTIVE, "busy"))
        task_id = f"task-{len(self.requests)}"
        self.taskStarted.emit(SimpleNamespace(task_id=task_id))
        return RequestAdmission(True, task_id=task_id)


@pytest.fixture(autouse=True)
def _qt_app():
    return QApplication.instance() or QApplication([])


def _setup(tmp_path):
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    image.write_text("image"); map_file.write_text("map")
    provider = Provider(image, map_file)
    firmware = FirmwareImage(
        source_out_file=str(image), generated_hex_file=str(image), entry_point=0x9000,
        blocks=(FirmwareBlock(0x9000, tuple(range(8))),), file_checksum="sum", format_info={},
    )
    prepared = PreparedServiceImage(firmware, 0x9000, 0x9010, 0x9020, 8, 1, 3)
    backend = RuntimeBackend(app_resource_provider=provider, prepare_service_operation=lambda *_a, **_kw: prepared)
    settings, advanced, controller = SettingsPage(), AdvancedPage(), Controller()
    binding = FlashServiceBinding(settings, advanced, controller, backend)
    return settings, advanced, controller, backend, provider, binding


def test_backend_state_populates_read_only_rows(tmp_path) -> None:
    settings, _advanced, _controller, backend, provider, binding = _setup(tmp_path)
    assert settings.flash_service_provider.value_label.text() == "Provider"
    assert settings.flash_service_image.value_label.text() == str(provider.image)
    assert settings.flash_service_map.value_label.text() == str(provider.map_file)
    assert settings.flash_service_descriptor_symbol.value_label.text() == "g_boot_flash_service_descriptor"
    assert not hasattr(binding, "app_resource_provider")
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.UNVALIDATED


def test_prepare_submits_revisions_only_and_renders_ready_summary(tmp_path) -> None:
    settings, advanced, controller, backend, _provider, binding = _setup(tmp_path)
    admission = binding.prepare()
    request = controller.requests[-1]
    assert admission.accepted
    assert not hasattr(request, "service_image_path")
    result = backend.execute(admission.task_id, request, None, None)
    controller.taskFinished.emit(result)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert settings.flash_service_status.value_label.text() == "Ready"
    assert settings.flash_service_descriptor_address.value_label.text() == "0x00009000"
    assert json.loads(advanced.result_output.toPlainText())["descriptor_symbol"] == "g_boot_flash_service_descriptor"


def test_provider_error_is_backend_owned_unavailable_state(tmp_path) -> None:
    settings, advanced, _controller, backend, provider, binding = _setup(tmp_path)
    advanced.result_output.setPlainText("keep")
    provider.error = AppResourceNotFoundError("missing service")
    binding._apply_enabled()
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.UNVALIDATED
    QApplication.processEvents()
    state = backend.flash_service_resource_state
    assert state.status is FlashServiceResourceStatus.UNAVAILABLE
    assert settings.flash_service_status.value_label.text() == "Unavailable"
    assert advanced.result_output.toPlainText() == "keep"


def test_owned_prepare_unavailable_failure_survives_signal_order(tmp_path) -> None:
    settings, advanced, controller, backend, _provider, binding = _setup(tmp_path)
    admission = binding.prepare()
    context = binding._owned[admission.task_id]
    current = backend.flash_service_resource_state
    backend._flash_service_resource_state = type(current)(
        context.resource_revision + 1, current.provider_name,
        current.image_path, current.map_path, FlashServiceResourceStatus.UNAVAILABLE,
        error_code="IMAGE_FILE_NOT_FOUND", error_message="missing during task",
    )
    failure_state = backend.flash_service_resource_state
    error = GuiRuntimeError(
        "IMAGE_FILE_NOT_FOUND", "missing during task", "prepare_flash_service",
        ErrorDisposition.SHOW_ONLY, admission.task_id,
    )
    result = TaskExecutionResult(
        admission.task_id, TaskFinalStatus.FAILED, "failed", error.message, error=error
    )

    controller.runtimeStateChanged.emit(controller.snapshot)
    assert backend.flash_service_resource_state is failure_state
    controller.taskFinished.emit(result)
    rendered = json.loads(advanced.result_output.toPlainText())
    assert rendered["operation"] == "prepare_flash_service"
    assert rendered["status"] == "FAILED"
    assert rendered["error"]["code"] == "IMAGE_FILE_NOT_FOUND"

    QApplication.processEvents()
    assert backend.flash_service_resource_state.revision == context.resource_revision + 2
    assert backend.flash_service_resource_state.status is FlashServiceResourceStatus.UNVALIDATED
    assert settings.flash_service_status.value_label.text() == "Not prepared"
    assert json.loads(advanced.result_output.toPlainText()) == rendered


def test_deferred_refresh_is_deduplicated_skips_busy_and_does_not_loop(
    tmp_path, monkeypatch
) -> None:
    _settings, advanced, controller, backend, provider, binding = _setup(tmp_path)
    calls = []
    refresh = backend.refresh_flash_service_resources
    monkeypatch.setattr(
        backend, "refresh_flash_service_resources",
        lambda: calls.append(True) or refresh(),
    )
    provider.error = AppResourceNotFoundError("still unavailable")
    advanced.result_output.setPlainText("keep")
    binding._apply_enabled()
    binding._apply_enabled()
    QApplication.processEvents()
    assert len(calls) == 1
    QApplication.processEvents()
    assert len(calls) == 1
    assert advanced.result_output.toPlainText() == "keep"

    binding._apply_enabled()
    controller.snapshot = RuntimeSnapshot(RuntimeState.BUSY, active_task_id="busy")
    QApplication.processEvents()
    assert len(calls) == 1

    controller.snapshot = RuntimeSnapshot()
    controller.runtimeStateChanged.emit(controller.snapshot)
    QApplication.processEvents()
    assert len(calls) == 2
    assert advanced.result_output.toPlainText() == "keep"


def test_admission_rejection_preserves_ready_state(tmp_path) -> None:
    settings, advanced, controller, backend, _provider, binding = _setup(tmp_path)
    first = binding.prepare()
    controller.taskFinished.emit(backend.execute(first.task_id, controller.requests[-1], None, None))
    ready = backend.flash_service_resource_state
    controller.accepted = False
    binding.prepare()
    assert backend.flash_service_resource_state is ready
    assert settings.flash_service_status.value_label.text() == "Ready"
    rendered = json.loads(advanced.result_output.toPlainText())
    assert rendered["status"] == "REJECTED"
    assert rendered["rejection"] == {"code": "TASK_ALREADY_ACTIVE", "message": "busy"}


def test_foreign_completion_refreshes_rows_without_overwriting_result(tmp_path) -> None:
    settings, advanced, controller, backend, _provider, binding = _setup(tmp_path)
    advanced.result_output.setPlainText("keep exactly")
    state = backend.flash_service_resource_state
    backend._flash_service_resource_state = type(state)(
        state.revision + 1, state.provider_name, state.image_path, state.map_path,
        FlashServiceResourceStatus.STALE, error_code="SERVICE_RESOURCE_CHANGED",
        error_message="changed",
    )
    error = GuiRuntimeError(
        "SERVICE_RESOURCE_CHANGED", "changed", "program_only", ErrorDisposition.SHOW_ONLY
    )
    controller.taskFinished.emit(
        SimpleNamespace(task_id="foreign", status=TaskFinalStatus.FAILED, error=error)
    )
    assert settings.flash_service_status.value_label.text() == "Reload required"
    assert advanced.result_output.toPlainText() == "keep exactly"


def test_owned_current_prepare_failure_renders_structured_error(tmp_path) -> None:
    _settings, advanced, controller, backend, _provider, binding = _setup(tmp_path)
    backend._prepare_service_operation = lambda *_a, **_kw: (_ for _ in ()).throw(
        ValueError("invalid service")
    )
    admission = binding.prepare()
    result = backend.execute(admission.task_id, controller.requests[-1], None, None)
    controller.taskFinished.emit(result)
    rendered = json.loads(advanced.result_output.toPlainText())
    assert rendered["status"] == "FAILED"
    assert rendered["error"]["code"] == "SERVICE_VALIDATION_FAILED"


def test_stale_owned_failure_does_not_overwrite_newer_result(tmp_path) -> None:
    _settings, advanced, controller, backend, _provider, binding = _setup(tmp_path)
    admission = binding.prepare()
    backend.refresh_flash_service_resources()
    backend._flash_service_resource_state = type(backend.flash_service_resource_state)(
        backend.service_configuration_revision + 2, "Provider", "new.txt", "new.map",
        FlashServiceResourceStatus.STALE, error_code="SERVICE_RESOURCE_CHANGED",
        error_message="later change",
    )
    advanced.result_output.setPlainText("newer result")
    error = GuiRuntimeError(
        "SERVICE_RESOURCE_CHANGED", "old change", "prepare_flash_service",
        ErrorDisposition.SHOW_ONLY, admission.task_id,
    )
    controller.taskFinished.emit(SimpleNamespace(
        task_id=admission.task_id, status=TaskFinalStatus.FAILED, error=error
    ))
    assert advanced.result_output.toPlainText() == "newer result"


def test_admission_error_and_exception_preserve_ready_state(tmp_path) -> None:
    _settings, advanced, controller, backend, _provider, binding = _setup(tmp_path)
    first = binding.prepare()
    controller.taskFinished.emit(backend.execute(first.task_id, controller.requests[-1], None, None))
    ready = backend.flash_service_resource_state
    controller.admission_error = GuiRuntimeError(
        "ADMISSION_FAILED", "bad admission", "controller", ErrorDisposition.SHOW_ONLY
    )
    binding.prepare()
    rendered = json.loads(advanced.result_output.toPlainText())
    assert rendered["error"] == {
        "code": "ADMISSION_FAILED", "message": "bad admission", "stage": "controller"
    }
    assert backend.flash_service_resource_state is ready

    controller.admission_error = None
    controller.exception = RuntimeError("boom")
    assert binding.prepare() is None
    rendered = json.loads(advanced.result_output.toPlainText())
    assert rendered["error"]["code"] == "REQUEST_TASK_FAILED"
    assert rendered["error"]["exception_type"] == "RuntimeError"
    assert binding._pending is None
    assert backend.flash_service_resource_state is ready
