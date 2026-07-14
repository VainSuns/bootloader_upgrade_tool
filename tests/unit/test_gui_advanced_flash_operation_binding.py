from dataclasses import replace
from datetime import datetime, timezone
import inspect
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.advanced_flash_models import PreparedAdvancedFlashImageSummary
from bootloader_upgrade_tool.gui.advanced_flash_operation_binding import AdvancedFlashOperationBinding
from bootloader_upgrade_tool.gui.advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    AdvancedFlashOperationSnapshot,
    AdvancedFlashOperationType,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
)
from bootloader_upgrade_tool.gui.flash_service_models import PreparedFlashServiceSummary
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, RequestAdmission, RuntimeSnapshot, RuntimeState, TaskExecutionResult, TaskFinalStatus
from bootloader_upgrade_tool.images import ImageIdentity, PreparedFlashImage, PreparedServiceImage
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self):
        super().__init__()
        self._snapshot = RuntimeSnapshot()
        self.requests = []

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        self.requests.append(request)
        return RequestAdmission(True, task_id=f"task-{len(self.requests)}")


class Backend:
    configuration_revision = 2
    service_configuration_revision = 3

    def __init__(self, image_cache, service_cache):
        self.image_cache = image_cache
        self.service_cache = service_cache
        self.active_target = CPU1_PROFILE
        self.image_revision = 1

    def prepared_advanced_flash_image_cache(self, target):
        return self.image_cache if target == "cpu1" else None

    @property
    def prepared_service_image_cache(self):
        return self.service_cache

    def advanced_flash_selection_revision(self, target):
        return self.image_revision


def caches(tmp_path: Path):
    app_path = tmp_path / "app.txt"
    service_path = tmp_path / "service.txt"
    map_path = tmp_path / "service.map"
    for path in (app_path, service_path, map_path):
        path.write_text(path.name)
    firmware = FirmwareImage(
        source_out_file=str(app_path),
        generated_hex_file=str(app_path),
        entry_point=0x082000,
        blocks=(FirmwareBlock(0x082000, tuple(range(8))),),
        file_checksum="sha",
        format_info={},
    )
    image = PreparedFlashImage(
        firmware, ImageIdentity(0x082000, 8, 0x1234, 0x082008), 0x2
    )
    fingerprint = lambda path: SourceFileFingerprint(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)
    image_summary = PreparedAdvancedFlashImageSummary(
        "cpu1", str(app_path), 1, 2, ImageSourceKind.TXT, fingerprint(app_path),
        0x082000, 8, 0x1234, 0x082008, 0x2, 0x2, Hex2000Source.NOT_USED, None,
    )
    service = PreparedServiceImage(firmware, 0x10000, 0x10020, 0x10030, 8, 0x5678, 0xF)
    service_summary = PreparedFlashServiceSummary(
        "cpu1", str(service_path), str(map_path), "descriptor", 3, 2,
        ImageSourceKind.TXT, fingerprint(service_path), fingerprint(map_path),
        0x10000, 0x10020, 0x10030, 8, 0x5678, Hex2000Source.NOT_USED, None,
    )
    return (image, image_summary), (service, service_summary)


def connected(target="cpu1"):
    info = ConnectionInfo("connection", "SCI", "COM3", datetime.now(timezone.utc), target)
    return RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=info, active_target_key=target)


def setup_binding(tmp_path):
    QApplication.instance() or QApplication([])
    page = AdvancedPage()
    controller = Controller()
    image_cache, service_cache = caches(tmp_path)
    backend = Backend(image_cache, service_cache)
    binding = AdvancedFlashOperationBinding(page, controller, backend)
    return page, controller, backend, binding


def apply(controller, backend, snapshot, profile):
    controller._snapshot = snapshot
    backend.active_target = profile
    controller.runtimeStateChanged.emit(snapshot)


def test_button_state_requires_connected_idle_cpu1_and_current_caches(tmp_path) -> None:
    page, controller, backend, _binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    assert page.erase_button.isEnabled()
    assert page.program_only_button.isEnabled()
    assert page.verify_only_button.isEnabled()

    page.erase_scope_combo.setCurrentText("Custom Sector Mask")
    assert not page.erase_button.isEnabled()
    assert page.program_only_button.isEnabled() and page.verify_only_button.isEnabled()
    page.custom_sector_selector.set_selected_sector_ids(("B", "C"))
    assert page.erase_button.isEnabled()

    apply(controller, backend, connected("cpu2"), CPU2_PROFILE)
    assert not any((page.erase_button.isEnabled(), page.program_only_button.isEnabled(), page.verify_only_button.isEnabled()))
    apply(controller, backend, RuntimeSnapshot(), None)
    assert not page.program_only_button.isEnabled()


def test_missing_ram_check_crc_disables_all_flash_operations(tmp_path) -> None:
    page, controller, backend, _binding = setup_binding(tmp_path)
    profile = replace(
        CPU1_PROFILE,
        command_set=replace(CPU1_PROFILE.command_set, ram_check_crc=None),
    )
    apply(controller, backend, connected(), profile)
    assert not any(
        button.isEnabled()
        for button in (page.erase_button, page.program_only_button, page.verify_only_button)
    )


def test_each_button_submits_one_current_cpu1_request(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    page.erase_button.click()
    apply(controller, backend, connected(), CPU1_PROFILE)
    page.program_only_button.click()
    apply(controller, backend, connected(), CPU1_PROFILE)
    page.verify_only_button.click()
    assert [type(item) for item in controller.requests] == [
        EraseAdvancedFlashRequest,
        ProgramAdvancedFlashRequest,
        VerifyAdvancedFlashRequest,
    ]
    assert all(item.target_key == "cpu1" and item.connection_id == "connection" for item in controller.requests)


def test_owned_result_is_retained_after_disconnect_and_stale_result_is_rejected(tmp_path) -> None:
    page, controller, backend, binding = setup_binding(tmp_path)
    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.program_only()
    operation = OperationResult(True, "program_flash_image", CPU1_PROFILE.name, "PROGRAM_END", {})
    payload = AdvancedFlashOperationSnapshot(
        "connection", "cpu1", 1, 2, 3, 2,
        AdvancedFlashOperationType.PROGRAM_ONLY, operation,
        {"operation": "backend_serialized_program", "summary": {}},
    )
    apply(controller, backend, RuntimeSnapshot(), None)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload))
    retained = page.result_output.toPlainText()
    assert "PROGRAM_ONLY" in retained and "backend_serialized_program" in retained

    apply(controller, backend, connected(), CPU1_PROFILE)
    binding.verify_only()
    apply(
        controller, backend,
        RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=ConnectionInfo("new", "SCI", "COM4", datetime.now(timezone.utc), "cpu1"), active_target_key="cpu1"),
        CPU1_PROFILE,
    )
    stale = AdvancedFlashOperationSnapshot(
        "connection", "cpu1", 1, 2, 3, 2,
        AdvancedFlashOperationType.VERIFY_ONLY, operation,
        {"operation": "backend_serialized_verify", "summary": {}},
    )
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=stale))
    assert page.result_output.toPlainText() == retained


def test_binding_source_has_no_operation_or_lower_layer_imports() -> None:
    import bootloader_upgrade_tool.gui.advanced_flash_operation_binding as module

    source = inspect.getsource(module)
    assert "operation_result_to_dict" not in source
    assert not any(
        token in source
        for token in ("..operations", "..protocol", "..session", "..transport", "..targets")
    )
