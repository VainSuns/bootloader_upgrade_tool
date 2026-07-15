from dataclasses import asdict, replace
from datetime import datetime, timezone
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_read_binding import AdvancedReadOnlyBinding
from bootloader_upgrade_tool.gui.pages.advanced_page import AdvancedPage
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
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
from bootloader_upgrade_tool.gui.status_models import (
    DeviceInfoRequest,
    DeviceInfoStatusSnapshot,
    LastErrorRequest,
    LastErrorStatusSnapshot,
    LoadedImageMatch,
    MetadataRefreshRequest,
    MetadataStatusSnapshot,
    ProtocolInfoRequest,
    ProtocolInfoStatusSnapshot,
)
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.protocol.boot_protocol_client import ProtocolInfo
from bootloader_upgrade_tool.protocol.models import DeviceInfo, ErrorDetail, MetadataSummary
from bootloader_upgrade_tool.targets import CPU1_PROFILE


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self):
        super().__init__()
        self._snapshot = RuntimeSnapshot()
        self.requests = []
        self.reject = False

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        self.requests.append(request)
        if self.reject:
            return RequestAdmission(False, rejection=RequestRejection(RequestRejectionCode.TASK_ALREADY_ACTIVE, "busy"))
        return RequestAdmission(True, task_id=f"task-{len(self.requests)}")


def connection(connection_id="connection", target="cpu1"):
    return ConnectionInfo(
        connection_id,
        "SCI",
        "COM3",
        datetime.now(timezone.utc),
        target,
        {"device_id": 0x377D, "cpu_id": 1 if target == "cpu1" else 2, "protocol_ver": 1},
    )


def metadata():
    return MetadataSummary(1, 1, 1, 1, 1, 3, 1, 0, 0, 0, 0x082400, 0x12345678, 1, 1, 0, 0, 1, 1, 8, 0x377D, 1)


def metadata_snapshot(*, automatic=False, connection_id="connection", target="cpu1"):
    raw = metadata()
    result = OperationResult(True, "get_metadata_summary", target, "GET_METADATA_SUMMARY", asdict(raw))
    return MetadataStatusSnapshot(
        connection_id, target, result, raw, True, True, True, True, True, True,
        LoadedImageMatch.NO_PREPARED_IMAGE, automatic,
    )


def device_info_snapshot(*, connection_id="connection", target="cpu1", protocol_ver=2):
    info = DeviceInfo(0x377D, 1 if target == "cpu1" else 2, 1, 0, 0, protocol_ver, 0, 64, 56, 0, 0)
    result = OperationResult(True, "get_device_info", target, "GET_DEVICE_INFO", asdict(info))
    return DeviceInfoStatusSnapshot(connection_id, target, result, info)


def protocol_info_snapshot(*, connection_id="connection", target="cpu1", protocol_ver=3):
    info = ProtocolInfo(protocol_ver, 1, 3, 10, 1, 1, 64, 0)
    result = OperationResult(True, "get_protocol_info", target, "GET_PROTOCOL_INFO", asdict(info))
    return ProtocolInfoStatusSnapshot(connection_id, target, result, info)


def last_error_snapshot(*, connection_id="connection", target="cpu1"):
    detail = ErrorDetail(2, 3, 0x082400, 8, 0, 0, 0, 0)
    result = OperationResult(True, "get_last_error", target, "GET_LAST_ERROR", asdict(detail))
    return LastErrorStatusSnapshot(connection_id, target, result, detail)


def setup_binding(profile=CPU1_PROFILE):
    QApplication.instance() or QApplication([])
    page = AdvancedPage()
    controller = Controller()
    consumed = []
    cleared = []
    binding = AdvancedReadOnlyBinding(
        page,
        controller,
        lambda: profile,
        manual_read_started=lambda: consumed.append(True),
        manual_metadata_failed=cleared.append,
    )
    return page, controller, binding, consumed, cleared


def apply(controller, snapshot):
    controller._snapshot = snapshot
    controller.runtimeStateChanged.emit(snapshot)


def page_state(page):
    diagnostics = tuple(
        getattr(page, f"diagnostics_{name}_value").text()
        for name in ("target", "device", "device_id", "cpu_id", "protocol_version", "last_error")
    )
    metadata_values = tuple(widget.text() for widget in page.metadata_summary_values.values())
    return diagnostics, metadata_values, page.result_output.toPlainText()


def test_identity_and_capabilities_are_initialized_without_diagnostic_reads() -> None:
    page, controller, _binding, _consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))
    assert controller.requests == []
    assert page.diagnostics_target_value.text() == "CPU1"
    assert page.diagnostics_device_id_value.text() == "0x377D"
    assert page.diagnostics_cpu_id_value.text() == "CPU1"
    assert page.diagnostics_protocol_version_value.text() == "1"
    assert page.diagnostics_last_error_value.text() == "Unknown"
    assert all(button.isEnabled() for button in (
        page.read_device_info_button, page.read_protocol_info_button,
        page.get_last_error_button, page.refresh_status_button,
    ))
    assert not page.erase_button.isEnabled() and not page.run_flash_app_button.isEnabled()


def test_cpu2_connection_replaces_cpu1_identity_without_extra_reads() -> None:
    page, controller, _binding, _consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection("one"), active_target_key="cpu1"))
    page.set_diagnostic_value("last_error", "old")
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection("two", "cpu2"), active_target_key="cpu2"))
    assert controller.requests == []
    assert page.diagnostics_target_value.text() == "CPU2"
    assert page.diagnostics_cpu_id_value.text() == "CPU2"
    assert page.diagnostics_last_error_value.text() == "Unknown"


def test_explicit_signals_submit_exact_connection_bound_requests() -> None:
    page, controller, _binding, consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))
    for button in (
        page.read_device_info_button,
        page.read_protocol_info_button,
        page.get_last_error_button,
        page.refresh_status_button,
    ):
        button.click()
    assert [type(request) for request in controller.requests] == [
        DeviceInfoRequest, ProtocolInfoRequest, LastErrorRequest, MetadataRefreshRequest,
    ]
    assert all(request.connection_id == "connection" for request in controller.requests)
    assert len(consumed) == 4
    assert not hasattr(page, "statusRequested")


def test_independent_capability_gating_and_dirty_runtime_disable_reads() -> None:
    command_set = replace(CPU1_PROFILE.command_set, get_last_error=None)
    profile = replace(CPU1_PROFILE, command_set=command_set)
    page, controller, _binding, _consumed, _cleared = setup_binding(profile)
    connected = RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1")
    apply(controller, connected)
    assert page.read_device_info_button.isEnabled()
    assert page.read_protocol_info_button.isEnabled()
    assert not page.get_last_error_button.isEnabled()
    assert page.refresh_status_button.isEnabled()
    apply(controller, replace(connected, state=RuntimeState.BUSY, active_task_id="task"))
    assert not any(button.isEnabled() for button in (
        page.read_device_info_button, page.read_protocol_info_button,
        page.get_last_error_button, page.refresh_status_button,
    ))

    for dirty in (
        replace(connected, connection_suspect=True),
        replace(
            connected,
            state=RuntimeState.BUSY,
            active_task_id="task",
            connection_suspect=True,
            disconnect_decision_pending=True,
        ),
        replace(connected, shutdown_requested=True),
        RuntimeSnapshot(),
    ):
        apply(controller, dirty)
        assert not any(button.isEnabled() for button in (
            page.read_device_info_button, page.read_protocol_info_button,
            page.get_last_error_button, page.refresh_status_button,
        ))


def test_automatic_metadata_updates_fields_without_shared_result() -> None:
    page, controller, _binding, _consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))
    page.result_output.setPlainText("keep")
    snapshot = metadata_snapshot(automatic=True)
    controller.taskFinished.emit(TaskExecutionResult("auto", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot))
    assert page.metadata_summary_values["metadata_valid"].text() == "Valid"
    assert page.result_output.toPlainText() == "keep"


def test_unowned_results_accept_only_current_automatic_metadata() -> None:
    page, controller, _binding, _consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))
    page.set_metadata_summary({"metadata_valid": "Seed"})
    page.result_output.setPlainText("keep")
    for task_id, payload in (
        ("manual", metadata_snapshot()),
        ("wrong-connection", metadata_snapshot(automatic=True, connection_id="old")),
        ("wrong-target", metadata_snapshot(automatic=True, target="cpu2")),
        ("diagnostics", device_info_snapshot()),
    ):
        controller.taskFinished.emit(
            TaskExecutionResult(task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload)
        )
        assert page.metadata_summary_values["metadata_valid"].text() == "Seed"
        assert page.result_output.toPlainText() == "keep"

    controller.taskFinished.emit(
        TaskExecutionResult(
            "automatic",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=metadata_snapshot(automatic=True),
        )
    )
    assert page.metadata_summary_values["metadata_valid"].text() == "Valid"
    assert page.result_output.toPlainText() == "keep"


def test_manual_metadata_success_and_failure_are_owned_and_structured() -> None:
    page, controller, binding, _consumed, cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))
    admission = binding.refresh_metadata()
    snapshot = metadata_snapshot()
    controller.taskFinished.emit(TaskExecutionResult(admission.task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=snapshot))
    data = json.loads(page.result_output.toPlainText())
    assert data["source"] == "MANUAL_REFRESH"
    assert data["result"]["confirmed_bootable"] is True

    admission = binding.refresh_metadata()
    error = GuiRuntimeError("DSP_STATUS_ERROR", "failed", "GET_METADATA_SUMMARY", ErrorDisposition.SHOW_ONLY, admission.task_id)
    controller.taskFinished.emit(TaskExecutionResult(admission.task_id, TaskFinalStatus.FAILED, "failed", "failed", error=error))
    failure = json.loads(page.result_output.toPlainText())
    assert failure["error"]["code"] == "DSP_STATUS_ERROR"
    assert page.metadata_summary_values["metadata_valid"].text() == "Unknown"
    assert cleared == ["cpu1"]


def test_admission_rejection_is_structured_and_preserves_existing_fields() -> None:
    page, controller, binding, consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))
    page.set_metadata_summary({"metadata_valid": "Valid"})
    controller.reject = True
    admission = binding.refresh_metadata()
    assert not admission.accepted
    assert consumed == [True]
    assert page.metadata_summary_values["metadata_valid"].text() == "Valid"
    result = json.loads(page.result_output.toPlainText())
    assert result["rejection"]["code"] == "TASK_ALREADY_ACTIVE"


def test_only_owned_current_diagnostics_success_can_render() -> None:
    page, controller, binding, _consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))
    info = DeviceInfo(0x377D, 1, 1, 0, 0, 2, 0, 64, 56, 0, 0)
    operation = OperationResult(True, "get_device_info", "cpu1", "GET_DEVICE_INFO", asdict(info))
    payload = DeviceInfoStatusSnapshot("connection", "cpu1", operation, info)
    controller.taskFinished.emit(TaskExecutionResult("unknown", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload))
    assert page.diagnostics_protocol_version_value.text() == "1"
    assert page.result_output.toPlainText() == ""

    admission = binding.read_device_info()
    controller.taskFinished.emit(TaskExecutionResult(admission.task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload))
    assert page.diagnostics_protocol_version_value.text() == "2"
    assert json.loads(page.result_output.toPlainText())["source"] == "MANUAL"


def test_owned_success_payload_mismatches_are_ignored_and_consumed() -> None:
    cases = (
        ("read_device_info", device_info_snapshot(connection_id="old"), device_info_snapshot()),
        ("read_device_info", device_info_snapshot(target="cpu2"), device_info_snapshot()),
        ("read_protocol_info", protocol_info_snapshot(connection_id="old"), protocol_info_snapshot()),
        ("read_last_error", last_error_snapshot(target="cpu2"), last_error_snapshot()),
        ("refresh_metadata", metadata_snapshot(connection_id="old"), metadata_snapshot()),
        ("refresh_metadata", metadata_snapshot(target="cpu2"), metadata_snapshot()),
        ("refresh_metadata", metadata_snapshot(automatic=True), metadata_snapshot()),
        ("read_device_info", metadata_snapshot(), device_info_snapshot()),
        ("refresh_metadata", device_info_snapshot(), metadata_snapshot()),
    )
    for submit_name, mismatched_payload, matching_payload in cases:
        page, controller, binding, _consumed, cleared = setup_binding()
        apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))
        page.set_metadata_summary({"metadata_valid": "Seed"})
        page.set_diagnostic_value("last_error", "kept")
        page.result_output.setPlainText("keep")
        before = page_state(page)
        admission = getattr(binding, submit_name)()

        controller.taskFinished.emit(
            TaskExecutionResult(
                admission.task_id,
                TaskFinalStatus.SUCCEEDED,
                "ok",
                "ok",
                payload=mismatched_payload,
            )
        )
        assert page_state(page) == before
        assert cleared == []

        controller.taskFinished.emit(
            TaskExecutionResult(
                admission.task_id,
                TaskFinalStatus.SUCCEEDED,
                "ok",
                "ok",
                payload=matching_payload,
            )
        )
        assert page_state(page) == before


def test_matching_owned_diagnostics_and_manual_metadata_still_render() -> None:
    page, controller, binding, _consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))

    for submit, payload in (
        (binding.read_device_info, device_info_snapshot()),
        (binding.read_protocol_info, protocol_info_snapshot()),
        (binding.read_last_error, last_error_snapshot()),
    ):
        admission = submit()
        controller.taskFinished.emit(
            TaskExecutionResult(admission.task_id, TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=payload)
        )
        assert json.loads(page.result_output.toPlainText())["source"] == "MANUAL"

    assert page.diagnostics_protocol_version_value.text() == "3"
    assert page.diagnostics_last_error_value.text() == "operation=2, stage=3"

    admission = binding.refresh_metadata()
    controller.taskFinished.emit(
        TaskExecutionResult(
            admission.task_id,
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=metadata_snapshot(),
        )
    )
    assert page.metadata_summary_values["metadata_valid"].text() == "Valid"
    assert json.loads(page.result_output.toPlainText())["source"] == "MANUAL_REFRESH"


def test_external_metadata_snapshot_updates_summary_without_shared_result() -> None:
    page, controller, binding, _consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"))
    page.result_output.setPlainText("keep")
    assert binding.apply_external_metadata_snapshot(metadata_snapshot())
    assert page.metadata_summary_values["metadata_valid"].text() == "Valid"
    assert page.result_output.toPlainText() == "keep"
    assert not binding.apply_external_metadata_snapshot(metadata_snapshot(connection_id="old"))
    assert not binding.apply_external_metadata_snapshot(object())


def test_stale_result_and_disconnect_do_not_leak_connection_state() -> None:
    page, controller, _binding, _consumed, _cleared = setup_binding()
    apply(controller, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection("new"), active_target_key="cpu1"))
    page.result_output.setPlainText("new")
    controller.taskFinished.emit(TaskExecutionResult("old", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=metadata_snapshot(automatic=True, connection_id="old")))
    assert page.metadata_summary_values["metadata_valid"].text() == "Unknown"
    assert page.result_output.toPlainText() == "new"
    apply(controller, RuntimeSnapshot(RuntimeState.DISCONNECTING, connection_info=connection("new"), active_target_key="cpu1"))
    assert page.diagnostics_target_value.text() == "Not connected"
    assert page.result_output.toPlainText() == ""
