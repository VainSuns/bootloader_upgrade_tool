from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Thread

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.advanced_ram_binding import AdvancedRamBinding
from bootloader_upgrade_tool.gui.advanced_ram_models import (
    AdvancedRamOperationSnapshot,
    AdvancedRamOperationType,
    CheckAdvancedRamCrcRequest,
    LoadAdvancedRamImageRequest,
    PreparedRamImageSummary,
    RunAdvancedRamImageRequest,
)
from bootloader_upgrade_tool.gui.image_preparation_models import Hex2000Source, ImageSourceKind, SourceFileFingerprint
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
    TaskCompletionAction,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.gui.runtime_backend import ActiveTargetContext, RuntimeBackend
from bootloader_upgrade_tool.images import PreparedRamImage
from bootloader_upgrade_tool.images.models import RamImageIdentity
from bootloader_upgrade_tool.operations import OperationResult
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE
from bootloader_upgrade_tool.gui.runtime_v2_events import (
    ConnectionClosed,
    ConnectionOpened,
    OperationStarted,
    OperationSucceeded,
    RamImageChanged,
    RuntimeOperationType,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration,
    ImageParseStatus,
    RamCrcEvidence,
    RamImageSummary,
    RuntimeCpuId,
    RuntimeStateStore,
)
from bootloader_upgrade_tool.gui.runtime_v2_transition import DomainEventDispatcher


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self):
        super().__init__()
        self._snapshot = RuntimeSnapshot()
        self.requests = []
        self.admission = None
        self.request_error = None

    @property
    def snapshot(self):
        return self._snapshot

    def request_task(self, request):
        if self.request_error is not None:
            raise self.request_error
        self.requests.append(request)
        return self.admission or RequestAdmission(True, task_id=f"task-{len(self.requests)}")


class Backend:
    def __init__(self):
        self.active_target = None
        self.configuration_revision = 0
        self._revisions = {cpu: 0 for cpu in RuntimeCpuId}
        self._dispatcher = DomainEventDispatcher(RuntimeStateStore())
        self.begin_calls = []
        self.fail_calls = []
        self.fail_error = None
        self.fail_returns_none = False

    @property
    def target_resources(self):
        return self._dispatcher._store.snapshot().target_resources

    @property
    def runtime_v2_snapshot(self):
        return self._dispatcher._store.snapshot()

    @property
    def active_target_context(self):
        connection = self.runtime_v2_snapshot.connection
        if connection is None or self.active_target is None:
            return None
        cpu_id = connection.cpu_id
        return ActiveTargetContext(
            cpu_id, cpu_id.value, connection, self.active_target,
            self.target_resources[cpu_id],
        )

    @property
    def connection_generation(self):
        return self.runtime_v2_snapshot.connection_generation

    def subscribe_runtime_v2(self, listener):
        self._dispatcher.subscribe(listener)

    def unsubscribe_runtime_v2(self, listener):
        self._dispatcher.unsubscribe(listener)

    def ram_image_revision(self, target):
        return self._revisions[RuntimeCpuId.from_target_key(target)]

    def set_ram_image_path(self, target, path):
        cpu = RuntimeCpuId.from_target_key(target)
        self._revisions[cpu] += 1
        self._dispatcher.dispatch(RamImageChanged(cpu, path, ImageParseStatus.EMPTY))
        return self._revisions[cpu]

    def begin_ram_image_parse(self, target, path, revision):
        self.begin_calls.append((target, path, revision))
        cpu = RuntimeCpuId.from_target_key(target)
        assert revision == self._revisions[cpu]
        resource = self.target_resources[cpu]
        return self._dispatcher.dispatch(
            RamImageChanged(cpu, resource.ram_image_path, ImageParseStatus.PARSING)
        )

    def fail_ram_image_parse(self, target, path, revision, code, message):
        self.fail_calls.append((target, path, revision, code, message))
        if self.fail_error is not None:
            raise self.fail_error
        if self.fail_returns_none:
            return None
        cpu = RuntimeCpuId.from_target_key(target)
        if revision != self._revisions[cpu]:
            return None
        resource = self.target_resources[cpu]
        return self._dispatcher.dispatch(
            RamImageChanged(
                cpu,
                resource.ram_image_path,
                ImageParseStatus.ERROR,
                parse_error=f"Code: {code}\n{message}",
            )
        )

    def ready(self, prepared_summary):
        cpu = RuntimeCpuId.from_target_key(prepared_summary.target_key)
        resource = self.target_resources[cpu]
        self._dispatcher.dispatch(
            RamImageChanged(
                cpu,
                resource.ram_image_path,
                ImageParseStatus.READY,
                RamImageSummary(
                    RamImageIdentity(
                        prepared_summary.entry_point,
                        prepared_summary.image_size_words,
                        prepared_summary.image_crc32,
                    )
                ),
            )
        )

def connection(identity="connection", target="cpu1"):
    return ConnectionInfo(identity, "SCI", "COM3", datetime.now(timezone.utc), target)


def apply(controller, backend, snapshot, profile=None):
    current = backend.runtime_v2_snapshot.connection
    info = snapshot.connection_info
    if info is None and current is not None:
        backend._dispatcher.dispatch(ConnectionClosed(current.connection_id, current.generation))
    elif info is not None and (
        current is None
        or current.connection_id != info.connection_id
        or current.cpu_id.value != info.target_key
    ):
        backend._dispatcher.dispatch(ConnectionOpened(info))
    controller._snapshot = snapshot
    backend.active_target = profile
    controller.runtimeStateChanged.emit(snapshot)


def summary(
    path: Path,
    target="cpu1",
    revision=1,
    *,
    entry_point=0x8000,
    image_size_words=3,
    image_crc32=0x12345678,
):
    fingerprint = SourceFileFingerprint(str(path), path.stat().st_size, path.stat().st_mtime_ns)
    return PreparedRamImageSummary(
        target,
        revision,
        str(path),
        ImageSourceKind.TXT,
        fingerprint,
        entry_point,
        image_size_words,
        image_crc32,
        Hex2000Source.NOT_USED,
        None,
    )


def operation_snapshot(
    connection_id,
    target,
    revision,
    result,
    operation_type=AdvancedRamOperationType.LOAD,
    identity=RamImageIdentity(0x8000, 3, 0x12345678),
    evidence=None,
):
    if operation_type is AdvancedRamOperationType.RUN and evidence is None:
        evidence = RamCrcEvidence(
            RuntimeCpuId.from_target_key(target),
            ConnectionGeneration(1),
            identity,
            identity.entry_point,
            identity.image_crc32,
            "crc",
        )
    return AdvancedRamOperationSnapshot(
        connection_id,
        target,
        revision,
        identity,
        operation_type,
        evidence,
        result,
    )


def grant_evidence(backend, target="cpu1", operation_id="crc"):
    cpu_id = RuntimeCpuId.from_target_key(target)
    identity = backend.target_resources[cpu_id].ram_image_summary.identity
    backend._dispatcher.dispatch(OperationSucceeded(
        operation_id,
        RuntimeOperationType.RAM_CRC,
        cpu_id,
        backend.connection_generation,
        identity,
    ))
    return backend.target_resources[cpu_id].ram_crc_evidence


def setup(binding_type=AdvancedRamBinding):
    page = AdvancedPage()
    controller = Controller()
    backend = Backend()
    binding = binding_type(page, controller, backend)
    return page, controller, backend, binding


class ThreadRecordingBinding(AdvancedRamBinding):
    def __init__(self, *args, **kwargs):
        self.listener_threads = []
        self.render_threads = []
        super().__init__(*args, **kwargs)
        self.render_threads.clear()

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self.listener_threads.append(QThread.currentThread())
        super()._receive_runtime_transition_from_backend(result)

    def _render_resource(self, cpu_id, resource=None) -> None:
        self.render_threads.append(QThread.currentThread())
        super()._render_resource(cpu_id, resource)


def test_worker_thread_ram_transition_renders_on_gui_thread(app, tmp_path) -> None:
    page, _controller, backend, binding = setup(ThreadRecordingBinding)
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    binding.listener_threads.clear()
    binding.render_threads.clear()

    worker = Thread(target=lambda: backend.ready(prepared_summary))
    worker.start()
    worker.join()
    assert page.cpu1_ram_entry_point_value.text() == "—"
    assert binding.listener_threads[-1] is not app.thread()
    assert binding.render_threads == []
    for _ in range(10):
        app.processEvents()
        if page.cpu1_ram_entry_point_value.text() == "0x00008000":
            break

    assert page.cpu1_ram_entry_point_value.text() == "0x00008000"
    assert page.cpu1_ram_image_size_value.text() == "3 words"
    assert binding.render_threads[-1] is app.thread()
    assert binding.render_threads[-1] is binding.thread()


def test_actual_destruction_unsubscribes_exact_runtime_listener(app) -> None:
    page = AdvancedPage()
    controller = Controller()
    backend = RuntimeBackend()
    binding = AdvancedRamBinding(page, controller, backend)
    listener = binding._runtime_v2_listener
    listeners = backend._runtime_v2_dispatcher._listeners
    assert listener in listeners

    binding.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()

    assert listener not in listeners
    backend.set_ram_image_path("cpu1", "later.txt")


def test_stale_queued_ram_transition_cannot_overwrite_newer_selection(app, tmp_path) -> None:
    page, _controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    worker = Thread(target=lambda: backend.ready(prepared_summary))
    worker.start()
    worker.join()

    backend.set_ram_image_path("cpu1", "new.txt")
    app.processEvents()

    assert page.cpu1_ram_image_edit.text() == "new.txt"
    assert page.cpu1_ram_entry_point_value.text() == "—"


def test_editing_finished_automatically_submits_current_selection(app, tmp_path) -> None:
    page, controller, backend, _binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    page.cpu1_ram_image_edit.setText(str(path))

    page.cpu1_ram_image_edit.editingFinished.emit()
    app.processEvents()

    assert len(controller.requests) == 1
    assert controller.requests[0].target_key == "cpu1"
    assert backend.target_resources[RuntimeCpuId.CPU1].ram_image_parse_status is ImageParseStatus.PARSING


def _establish_ready(binding, backend, path):
    binding.apply_session_path("cpu1", str(path))
    revision = backend.ram_image_revision("cpu1")
    backend.begin_ram_image_parse("cpu1", str(path), revision)
    prepared_summary = summary(path, revision=revision)
    backend.ready(prepared_summary)
    return revision, prepared_summary


def test_busy_snapshot_cancels_queued_automatic_ram_parse(app, tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    revision, prepared_summary = _establish_ready(binding, backend, path)
    page.result_output.setPlainText("keep")
    begin_count = len(backend.begin_calls)
    page.cpu1_ram_image_edit.editingFinished.emit()

    apply(controller, backend, RuntimeSnapshot(RuntimeState.BUSY, active_task_id="other"))
    app.processEvents()

    resource = backend.target_resources[RuntimeCpuId.CPU1]
    assert controller.requests == []
    assert len(backend.begin_calls) == begin_count
    assert backend.ram_image_revision("cpu1") == revision
    assert resource.ram_image_parse_status is ImageParseStatus.READY
    assert resource.ram_image_summary is not None
    assert resource.ram_image_summary.identity.entry_point == prepared_summary.entry_point
    assert page.result_output.toPlainText() == "keep"


def test_forced_prepare_while_busy_is_complete_noop(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    revision, prepared_summary = _establish_ready(binding, backend, path)
    page.result_output.setPlainText("keep")
    begin_count = len(backend.begin_calls)
    apply(controller, backend, RuntimeSnapshot(RuntimeState.BUSY, active_task_id="other"))

    assert binding.prepare("cpu1", force=True) is None

    assert controller.requests == []
    assert len(backend.begin_calls) == begin_count
    assert backend.ram_image_revision("cpu1") == revision
    assert backend.target_resources[RuntimeCpuId.CPU1].ram_image_summary.identity.entry_point == prepared_summary.entry_point
    assert page.result_output.toPlainText() == "keep"


def test_admission_error_preserves_runtime_details(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    controller.admission = RequestAdmission(
        False,
        error=GuiRuntimeError(
            "WORKER_STARTUP_FAILED",
            "worker failed",
            "controller",
            ErrorDisposition.SHOW_ONLY,
            details={"generation": 7},
        ),
    )

    admission = binding.prepare("cpu1")

    assert admission is controller.admission
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    assert resource.ram_image_parse_error == "Code: WORKER_STARTUP_FAILED\nworker failed"
    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"] == {
        "code": "WORKER_STARTUP_FAILED",
        "stage": "controller",
        "message": "worker failed",
        "details": {"generation": 7},
    }


def test_ordinary_rejection_preserves_code_and_message(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    rejection = RequestRejection(
        RequestRejectionCode.TASK_ALREADY_ACTIVE, "another task is active"
    )
    controller.admission = RequestAdmission(False, rejection=rejection)

    binding.prepare("cpu1")

    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"]["code"] == "TASK_ALREADY_ACTIVE"
    assert shown["error"]["message"] == "another task is active"
    assert backend.target_resources[RuntimeCpuId.CPU1].ram_image_parse_error == (
        "Code: IMAGE_PREPARATION_NOT_STARTED\nanother task is active"
    )


def test_request_exception_is_primary_prepare_failure(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    controller.request_error = RuntimeError("request exploded")

    assert binding.prepare("cpu1") is None

    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"] == {
        "code": "IMAGE_PREPARATION_NOT_STARTED",
        "stage": "prepare_ram_image",
        "message": "request exploded",
    }


def test_failure_publication_exception_is_contained(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    controller.admission = RequestAdmission(
        False,
        error=GuiRuntimeError(
            "ADMISSION_FAILED", "primary failure", "controller", ErrorDisposition.SHOW_ONLY
        ),
    )
    backend.fail_error = RuntimeError("RuntimeBackend concurrent entry is not allowed")

    binding.prepare("cpu1")

    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"]["code"] == "ADMISSION_FAILED"
    assert shown["error"]["message"] == "primary failure"
    assert shown["state_update_error"] == {
        "exception_type": "RuntimeError",
        "message": "RuntimeBackend concurrent entry is not allowed",
    }


def test_stale_failure_publication_none_is_safe(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu1", str(path))
    controller.admission = RequestAdmission(
        False,
        rejection=RequestRejection(
            RequestRejectionCode.INVALID_RUNTIME_STATE, "not idle"
        ),
    )
    backend.fail_returns_none = True

    binding.prepare("cpu1")

    shown = json.loads(page.result_output.toPlainText())
    assert shown["error"]["code"] == "INVALID_RUNTIME_STATE"
    assert "state_update_error" not in shown


def _operation_ready_setup(tmp_path):
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram", encoding="ascii")
    _establish_ready(binding, backend, path)
    apply(
        controller,
        backend,
        RuntimeSnapshot(
            RuntimeState.CONNECTED,
            connection_info=connection(),
            active_target_key="cpu1",
        ),
        CPU1_PROFILE,
    )
    grant_evidence(backend)
    return page, controller, backend, binding


def test_binding_captures_lightweight_current_ram_requests(tmp_path) -> None:
    _page, controller, backend, binding = _operation_ready_setup(tmp_path)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    identity = resource.ram_image_summary.identity

    binding.load()
    binding.check_crc()
    binding.run()

    load, check, run = controller.requests[-3:]
    assert isinstance(load, LoadAdvancedRamImageRequest)
    assert isinstance(check, CheckAdvancedRamCrcRequest)
    assert isinstance(run, RunAdvancedRamImageRequest)
    assert load.image_source_path == check.image_source_path == str(
        Path(resource.ram_image_path).resolve()
    )
    assert load.image_tool_configuration_revision == check.image_tool_configuration_revision == 0
    assert load.expected_image_identity is check.expected_image_identity is run.expected_image_identity is identity
    assert run.expected_ram_crc_evidence is resource.ram_crc_evidence
    assert binding._owned["task-3"].expected_ram_crc_evidence is resource.ram_crc_evidence
    assert [binding._owned[f"task-{index}"].operation_type for index in range(1, 4)] == [
        AdvancedRamOperationType.LOAD,
        AdvancedRamOperationType.CHECK_CRC,
        AdvancedRamOperationType.RUN,
    ]
    assert all(
        binding._owned[f"task-{index}"].expected_image_identity is identity
        for index in range(1, 4)
    )
    assert not hasattr(run, "image_source_path")
    assert not hasattr(run, "image_tool_configuration_revision")
    assert not hasattr(backend, "prepared_ram_image_cache")


@pytest.mark.parametrize(
    "snapshot",
    (
        RuntimeSnapshot(
            RuntimeState.BUSY,
            active_task_id="other",
            connection_info=connection(),
            active_target_key="cpu1",
        ),
        RuntimeSnapshot(
            RuntimeState.CONNECTED,
            connection_info=connection(),
            active_target_key="cpu1",
            connection_suspect=True,
        ),
        RuntimeSnapshot(
            RuntimeState.CONNECTED,
            connection_info=connection(),
            active_target_key="cpu1",
            shutdown_requested=True,
        ),
        RuntimeSnapshot(cleanup_pending=True),
    ),
)
def test_direct_ram_submissions_share_runtime_state_gate(tmp_path, snapshot) -> None:
    _page, controller, backend, binding = _operation_ready_setup(tmp_path)
    apply(controller, backend, snapshot, CPU1_PROFILE)

    assert binding.load() is binding.check_crc() is binding.run() is None
    assert controller.requests == []


def test_direct_ram_submissions_reject_controller_context_mismatch(tmp_path) -> None:
    _page, controller, _backend, binding = _operation_ready_setup(tmp_path)
    controller._snapshot = RuntimeSnapshot(
        RuntimeState.CONNECTED,
        connection_info=connection("other"),
        active_target_key="cpu1",
    )
    controller.runtimeStateChanged.emit(controller.snapshot)

    assert binding.load() is binding.check_crc() is binding.run() is None
    assert controller.requests == []


@pytest.mark.parametrize(
    ("operation", "missing_command"),
    (("load", "ram_load_begin"), ("check_crc", "ram_check_crc"), ("run", "run_ram")),
)
def test_direct_ram_submission_requires_profile_command(
    tmp_path, operation, missing_command
) -> None:
    page, controller, backend, binding = _operation_ready_setup(tmp_path)
    profile = replace(
        CPU1_PROFILE,
        name="Injected CPU1 capability gap",
        command_set=replace(CPU1_PROFILE.command_set, **{missing_command: None}),
    )
    apply(controller, backend, controller.snapshot, profile)

    assert getattr(binding, operation)() is None
    assert controller.requests == []
    button = {
        "load": page.ram_load_button,
        "check_crc": page.ram_crc_button,
        "run": page.ram_run_button,
    }[operation]
    assert not button.isEnabled()


@pytest.mark.parametrize(
    ("submit", "returned_type"),
    [
        ("load", AdvancedRamOperationType.RUN),
        ("run", AdvancedRamOperationType.LOAD),
    ],
)
def test_owned_ram_result_rejects_wrong_operation_type(
    tmp_path, submit, returned_type
) -> None:
    page, controller, _backend, binding = _operation_ready_setup(tmp_path)
    getattr(binding, submit)()
    original = page.result_output.toPlainText()
    operation = OperationResult(True, "ram", CPU1_PROFILE.name, "RAM", {})

    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=operation_snapshot(
                "connection", "cpu1", 1, operation, returned_type
            ),
        )
    )

    assert page.result_output.toPlainText() == original


def test_owned_ram_crc_result_rejects_wrong_image_identity(tmp_path) -> None:
    page, controller, _backend, binding = _operation_ready_setup(tmp_path)
    binding.check_crc()
    original = page.result_output.toPlainText()
    operation = OperationResult(True, "check_ram_crc", CPU1_PROFILE.name, "RAM_CHECK_CRC", {})

    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=operation_snapshot(
                "connection",
                "cpu1",
                1,
                operation,
                AdvancedRamOperationType.CHECK_CRC,
                RamImageIdentity(0x8000, 3, 0x87654321),
            ),
        )
    )

    assert page.result_output.toPlainText() == original


def test_owned_ram_result_rejects_changed_current_ready_identity(tmp_path) -> None:
    page, controller, backend, binding = _operation_ready_setup(tmp_path)
    binding.load()
    original = page.result_output.toPlainText()
    path = Path(backend.target_resources[RuntimeCpuId.CPU1].ram_image_path)
    backend.ready(summary(path, image_crc32=0x87654321))
    operation = OperationResult(True, "load_ram_image", CPU1_PROFILE.name, "RAM_LOAD_END", {})

    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=operation_snapshot("connection", "cpu1", 1, operation),
        )
    )

    assert page.result_output.toPlainText() == original


@pytest.mark.parametrize(
    ("submit", "operation_type", "operation", "stage"),
    [
        ("load", AdvancedRamOperationType.LOAD, "load_ram_image", "RAM_LOAD_END"),
        ("check_crc", AdvancedRamOperationType.CHECK_CRC, "check_ram_crc", "RAM_CHECK_CRC"),
        ("run", AdvancedRamOperationType.RUN, "run_ram_image", "RUN_RAM"),
    ],
)
def test_matching_owned_ram_results_render(
    tmp_path, submit, operation_type, operation, stage
) -> None:
    page, controller, _backend, binding = _operation_ready_setup(tmp_path)
    getattr(binding, submit)()
    result = OperationResult(True, operation, CPU1_PROFILE.name, stage, {})

    controller.taskFinished.emit(
        TaskExecutionResult(
            "task-1",
            TaskFinalStatus.SUCCEEDED,
            "ok",
            "ok",
            payload=operation_snapshot(
                "connection", "cpu1", 1, result, operation_type
            ),
        )
    )

    shown = json.loads(page.result_output.toPlainText())
    assert shown["operation"] == submit and shown["status"] == "SUCCEEDED"


def _assert_ram_state_unchanged(backend, resource, fail_count):
    assert backend.target_resources[RuntimeCpuId.CPU1] == resource
    assert len(backend.fail_calls) == fail_count


def test_load_admission_rejection_keeps_operation_identity(tmp_path) -> None:
    page, controller, backend, binding = _operation_ready_setup(tmp_path)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    fail_count = len(backend.fail_calls)
    controller.admission = RequestAdmission(
        False,
        rejection=RequestRejection(
            RequestRejectionCode.TASK_ALREADY_ACTIVE, "another task is active"
        ),
    )

    binding.load()

    shown = json.loads(page.result_output.toPlainText())
    assert shown == {
        "operation": "load",
        "status": "REJECTED",
        "error": {
            "code": "TASK_ALREADY_ACTIVE",
            "stage": "load",
            "message": "another task is active",
        },
    }
    _assert_ram_state_unchanged(backend, resource, fail_count)


def test_check_crc_admission_rejection_keeps_operation_identity(tmp_path) -> None:
    page, controller, backend, binding = _operation_ready_setup(tmp_path)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    fail_count = len(backend.fail_calls)
    controller.admission = RequestAdmission(
        False,
        rejection=RequestRejection(
            RequestRejectionCode.INVALID_RUNTIME_STATE, "CRC unavailable"
        ),
    )

    binding.check_crc()

    shown = json.loads(page.result_output.toPlainText())
    assert shown["operation"] == "check_crc"
    assert shown["status"] == "REJECTED"
    assert shown["error"] == {
        "code": "INVALID_RUNTIME_STATE",
        "stage": "check_crc",
        "message": "CRC unavailable",
    }
    _assert_ram_state_unchanged(backend, resource, fail_count)


def test_run_admission_rejection_keeps_operation_identity(tmp_path) -> None:
    page, controller, backend, binding = _operation_ready_setup(tmp_path)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    fail_count = len(backend.fail_calls)
    controller.admission = RequestAdmission(
        False,
        rejection=RequestRejection(
            RequestRejectionCode.ACTION_NOT_AVAILABLE, "Run unavailable"
        ),
    )

    binding.run()

    shown = json.loads(page.result_output.toPlainText())
    assert shown["operation"] == "run"
    assert shown["status"] == "REJECTED"
    assert shown["error"] == {
        "code": "ACTION_NOT_AVAILABLE",
        "stage": "run",
        "message": "Run unavailable",
    }
    _assert_ram_state_unchanged(backend, resource, fail_count)


def test_load_admission_error_keeps_operation_identity_and_details(tmp_path) -> None:
    page, controller, backend, binding = _operation_ready_setup(tmp_path)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    fail_count = len(backend.fail_calls)
    controller.admission = RequestAdmission(
        False,
        error=GuiRuntimeError(
            "WRONG_CONTROLLER_THREAD",
            "Controller called from the wrong thread",
            "controller",
            ErrorDisposition.SHOW_ONLY,
            details={"thread": "worker"},
        ),
    )

    binding.load()

    shown = json.loads(page.result_output.toPlainText())
    assert shown == {
        "operation": "load",
        "status": "FAILED",
        "error": {
            "code": "WRONG_CONTROLLER_THREAD",
            "stage": "controller",
            "message": "Controller called from the wrong thread",
            "details": {"thread": "worker"},
        },
    }
    assert "state_update_error" not in shown
    _assert_ram_state_unchanged(backend, resource, fail_count)


def test_run_request_exception_keeps_operation_identity(tmp_path) -> None:
    page, controller, backend, binding = _operation_ready_setup(tmp_path)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    fail_count = len(backend.fail_calls)
    controller.request_error = RuntimeError("Run submission exploded")

    assert binding.run() is None

    shown = json.loads(page.result_output.toPlainText())
    assert shown == {
        "operation": "run",
        "status": "FAILED",
        "error": {
            "code": "RAM_OPERATION_NOT_STARTED",
            "stage": "run",
            "message": "Run submission exploded",
        },
    }
    assert "state_update_error" not in shown
    _assert_ram_state_unchanged(backend, resource, fail_count)


def test_operation_empty_admission_uses_defensive_rejection(tmp_path) -> None:
    page, controller, backend, binding = _operation_ready_setup(tmp_path)
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    fail_count = len(backend.fail_calls)
    controller.admission = RequestAdmission(False)

    binding.check_crc()

    shown = json.loads(page.result_output.toPlainText())
    assert shown == {
        "operation": "check_crc",
        "status": "REJECTED",
        "error": {
            "code": "RAM_OPERATION_NOT_STARTED",
            "stage": "check_crc",
            "message": "Request rejected",
        },
    }
    _assert_ram_state_unchanged(backend, resource, fail_count)


def test_apply_session_path_invalidates_same_text_without_submitting() -> None:
    page, controller, backend, binding = setup()
    binding.apply_session_path("cpu1", "same.txt")
    binding.apply_session_path("cpu1", "same.txt")
    assert page.cpu1_ram_image_edit.text() == "same.txt"
    assert backend.ram_image_revision("cpu1") == 2
    assert not hasattr(binding, "_revisions")
    assert not hasattr(binding, "_summaries")
    assert controller.requests == []


def test_cpu1_and_cpu2_selections_are_independent_and_survive_disconnect(tmp_path) -> None:
    page, controller, backend, binding = setup()
    one, two = tmp_path / "one.txt", tmp_path / "two.txt"
    one.write_text("one")
    two.write_text("two")
    binding.select_image("cpu1", str(one))
    first_revision = backend.ram_image_revision("cpu1")
    binding.select_image("cpu2", str(two))

    assert page.cpu1_ram_image_edit.text() == str(one)
    assert page.cpu2_ram_image_edit.text() == str(two)
    assert backend.ram_image_revision("cpu1") == first_revision
    assert backend.ram_image_revision("cpu2") == 1

    apply(controller, backend, RuntimeSnapshot())
    assert page.cpu1_ram_image_edit.text() == str(one)
    assert page.cpu2_ram_image_edit.text() == str(two)


def test_prepared_summary_gates_current_target_capabilities(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"), CPU1_PROFILE)
    grant_evidence(backend)

    assert page.ram_load_button.isEnabled()
    assert page.ram_crc_button.isEnabled()
    assert page.ram_run_button.isEnabled()

    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection("cpu2", "cpu2"), active_target_key="cpu2"), CPU2_PROFILE)
    assert not page.ram_load_button.isEnabled()
    assert not page.ram_crc_button.isEnabled()
    assert not page.ram_run_button.isEnabled()


def test_cpu2_empty_command_set_blocks_all_direct_ram_submissions(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "cpu2-ram.txt"
    path.write_text("ram", encoding="ascii")
    binding.apply_session_path("cpu2", str(path))
    revision = backend.ram_image_revision("cpu2")
    backend.begin_ram_image_parse("cpu2", str(path), revision)
    backend.ready(summary(path, "cpu2", revision))
    apply(
        controller,
        backend,
        RuntimeSnapshot(
            RuntimeState.CONNECTED,
            connection_info=connection("cpu2", "cpu2"),
            active_target_key="cpu2",
        ),
        CPU2_PROFILE,
    )
    grant_evidence(backend, "cpu2")

    assert binding.load() is binding.check_crc() is binding.run() is None
    assert controller.requests == []
    assert not page.ram_load_button.isEnabled()
    assert not page.ram_crc_button.isEnabled()
    assert not page.ram_run_button.isEnabled()


def test_run_gate_tracks_current_crc_evidence(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    _establish_ready(binding, backend, path)
    apply(
        controller,
        backend,
        RuntimeSnapshot(
            RuntimeState.CONNECTED,
            connection_info=connection(),
            active_target_key="cpu1",
        ),
        CPU1_PROFILE,
    )
    assert page.ram_load_button.isEnabled() and page.ram_crc_button.isEnabled()
    assert not page.ram_run_button.isEnabled() and binding.run() is None

    evidence = grant_evidence(backend)
    assert page.ram_run_button.isEnabled()
    binding.run()
    assert controller.requests[-1].expected_ram_crc_evidence is evidence

    backend._dispatcher.dispatch(OperationStarted(
        "new-crc",
        RuntimeOperationType.RAM_CRC,
        RuntimeCpuId.CPU1,
        backend.connection_generation,
        evidence.ram_image_identity,
    ))
    assert not page.ram_run_button.isEnabled()


def test_shared_result_rejects_stale_connection_target_revision_and_task(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"), CPU1_PROFILE)
    binding.load()
    original = page.result_output.toPlainText()
    operation = OperationResult(True, "load_ram_image", CPU1_PROFILE.name, "RAM_LOAD_END", {})

    controller.taskFinished.emit(TaskExecutionResult("unknown", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=operation_snapshot("connection", "cpu1", 1, operation)))
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=operation_snapshot("old", "cpu1", 1, operation)))
    assert page.result_output.toPlainText() == original

    binding.load()
    page.cpu1_ram_image_edit.setText(str(path) + ".new")
    controller.taskFinished.emit(TaskExecutionResult("task-3", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=operation_snapshot("connection", "cpu1", 1, operation)))
    assert page.result_output.toPlainText() == original


def test_run_result_is_retained_after_controller_releases_connection(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    apply(controller, backend, RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1"), CPU1_PROFILE)
    grant_evidence(backend)
    binding.run()
    operation = OperationResult(True, "run_ram_image", CPU1_PROFILE.name, "RUN_RAM", {})

    apply(controller, backend, RuntimeSnapshot())
    controller.taskFinished.emit(TaskExecutionResult(
        "task-2",
        TaskFinalStatus.SUCCEEDED,
        "Run RAM Image",
        "RUN_RAM",
        payload=operation_snapshot("connection", "cpu1", 1, operation, AdvancedRamOperationType.RUN),
        completion_action=TaskCompletionAction.RELEASE_CONNECTION,
    ))

    assert '"operation": "run"' in page.result_output.toPlainText()
    assert '"connection_id": "connection"' in page.result_output.toPlainText()


def test_cleanup_failure_is_retained_after_disconnect_but_rejected_for_new_connection(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    connected = RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1")
    apply(controller, backend, connected, CPU1_PROFILE)
    binding.load()
    error = GuiRuntimeError(
        "CANCELLATION_CLEANUP_FAILED",
        "cleanup failed",
        "RAM_LOAD_END",
        ErrorDisposition.ASK_DISCONNECT,
        "task-2",
        True,
        True,
    )
    failed = TaskExecutionResult("task-2", TaskFinalStatus.FAILED, "failed", "cleanup failed", error=error)

    apply(controller, backend, RuntimeSnapshot())
    controller.taskFinished.emit(failed)
    retained = page.result_output.toPlainText()
    assert "CANCELLATION_CLEANUP_FAILED" in retained

    apply(controller, backend, connected, CPU1_PROFILE)
    binding.load()
    apply(
        controller,
        backend,
        RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection("new"), active_target_key="cpu1"),
        CPU1_PROFILE,
    )
    controller.taskFinished.emit(TaskExecutionResult(
        "task-3",
        TaskFinalStatus.SUCCEEDED,
        "ok",
        "ok",
        payload=operation_snapshot(
            "connection", "cpu1", 1,
            OperationResult(True, "load_ram_image", CPU1_PROFILE.name, "RAM_LOAD_END", {}),
        ),
    ))
    assert page.result_output.toPlainText() == retained


def test_owned_ram_materialization_failure_remains_visible_after_ready_to_error_transition(tmp_path) -> None:
    page, controller, backend, binding = setup()
    path = tmp_path / "ram.txt"
    path.write_text("ram")
    binding.select_image("cpu1", str(path))
    prepared_summary = summary(path)
    backend.ready(prepared_summary)
    controller.taskFinished.emit(TaskExecutionResult("task-1", TaskFinalStatus.SUCCEEDED, "ok", "ok", payload=prepared_summary))
    connected = RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=connection(), active_target_key="cpu1")
    apply(controller, backend, connected, CPU1_PROFILE)
    assert page.ram_load_button.isEnabled()
    binding.load()
    revision = backend.ram_image_revision("cpu1")

    backend.fail_ram_image_parse("cpu1", str(path), 1, "IMAGE_CHANGED", "changed")
    resource = backend.target_resources[RuntimeCpuId.CPU1]
    assert resource.ram_image_parse_status is ImageParseStatus.ERROR
    assert resource.ram_image_summary is None
    assert backend.ram_image_revision("cpu1") == revision
    apply(controller, backend, connected, CPU1_PROFILE)  # runtimeStateChanged before taskFinished
    error = GuiRuntimeError("IMAGE_CHANGED", "changed", "load_ram_image", ErrorDisposition.SHOW_ONLY, "task-2")
    controller.taskFinished.emit(TaskExecutionResult("task-2", TaskFinalStatus.FAILED, "failed", "changed", error=error))
    shown = json.loads(page.result_output.toPlainText())
    assert shown["operation"] == "load" and shown["status"] == "FAILED"
    assert shown["error"] == {
        "code": "IMAGE_CHANGED",
        "stage": "load_ram_image",
        "message": "changed",
    }
    assert not page.ram_load_button.isEnabled()
    assert not page.ram_crc_button.isEnabled()
    assert not page.ram_run_button.isEnabled()

    retained = page.result_output.toPlainText()
    controller.taskFinished.emit(
        TaskExecutionResult("foreign", TaskFinalStatus.SUCCEEDED, "foreign", "foreign")
    )
    assert page.result_output.toPlainText() == retained

    backend.ready(prepared_summary)
    binding.load()
    backend.set_ram_image_path("cpu1", str(path) + ".new")
    controller.taskFinished.emit(
        TaskExecutionResult("task-3", TaskFinalStatus.SUCCEEDED, "stale", "stale")
    )
    assert page.result_output.toPlainText() == retained
