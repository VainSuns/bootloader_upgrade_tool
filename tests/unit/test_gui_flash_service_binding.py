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
    RequestAdmission, RequestRejection, RequestRejectionCode, RuntimeSnapshot,
    RuntimeState, TaskFinalStatus,
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

    def request_task(self, request):
        self.requests.append(request)
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
    provider.error = AppResourceNotFoundError("missing service")
    binding._apply_enabled()
    state = backend.flash_service_resource_state
    assert state.status is FlashServiceResourceStatus.UNAVAILABLE
    assert settings.flash_service_status.value_label.text() == "Unavailable"
    assert json.loads(advanced.result_output.toPlainText())["error"]["message"] == "missing service"


def test_admission_rejection_preserves_ready_state(tmp_path) -> None:
    settings, _advanced, controller, backend, _provider, binding = _setup(tmp_path)
    first = binding.prepare()
    controller.taskFinished.emit(backend.execute(first.task_id, controller.requests[-1], None, None))
    ready = backend.flash_service_resource_state
    controller.accepted = False
    binding.prepare()
    assert backend.flash_service_resource_state is ready
    assert settings.flash_service_status.value_label.text() == "Ready"
