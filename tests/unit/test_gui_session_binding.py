from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.main_window import BootloaderMainWindow
from bootloader_upgrade_tool.gui.persistence_models import (
    DocumentLoadResult,
    RuntimeCacheDocument,
    SessionDocument,
    TargetSessionSettings,
)
from bootloader_upgrade_tool.gui.persistence_stores import PersistenceFormatError
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
    RequestAdmission,
    RequestRejection,
    RequestRejectionCode,
    RuntimeSnapshot,
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import RuntimeCpuId, TargetResourceState
from bootloader_upgrade_tool.gui.session_application_service import (
    SessionApplicationService,
    SessionSwitchCandidate,
)
from bootloader_upgrade_tool.gui.session_gui_binding import DirtySessionDecision, SessionGuiBinding


def qt_app():
    return QApplication.instance() or QApplication([])


class SessionStore:
    def __init__(self):
        self.documents = {}
        self.saved = []

    def load(self, path):
        key = str(Path(path).resolve())
        if key not in self.documents:
            raise OSError("missing Session")
        return DocumentLoadResult(self.documents[key], 1)

    def save(self, path, document):
        key = str(Path(path).resolve())
        self.documents[key] = document
        self.saved.append((key, document))


class CacheStore:
    def __init__(self, load_error=None):
        self.document = RuntimeCacheDocument()
        self.load_error = load_error
        self.save_calls = 0

    def load(self):
        if self.load_error:
            raise self.load_error
        return DocumentLoadResult(self.document, 1)

    def save(self, document):
        self.save_calls += 1
        self.document = document


class Controller(QObject):
    runtimeStateChanged = Signal(object)
    taskStarted = Signal(object)
    taskFinished = Signal(object)

    def __init__(self):
        super().__init__()
        self.snapshot = RuntimeSnapshot()

    def apply(self, snapshot):
        self.snapshot = snapshot
        self.runtimeStateChanged.emit(snapshot)


class Backend:
    def __init__(self):
        self.active_session = None
        self.active_transport = None
        self.connection_info = None
        self.pending_close = None
        self.runtime_v2_snapshot = SimpleNamespace(connection=None)
        self.target_resources = {
            cpu: TargetResourceState(cpu) for cpu in RuntimeCpuId
        }
        self.changes = 0
        self.error = None
        self.on_change = None

    def apply_session_change(self):
        if self.on_change:
            self.on_change()
        if self.error:
            raise self.error
        self.changes += 1
        return object()


class ProgramBinding:
    def __init__(self, backend, cpu_id, page):
        self.backend = backend
        self.cpu_id = cpu_id
        self.page = page
        self.paths = []
        self.prepares = 0
        self.admissions = []
        page.image_path_row.path_edit.textChanged.connect(self._path_changed)

    def _path_changed(self, path):
        self.backend.target_resources[self.cpu_id] = TargetResourceState(
            self.cpu_id, program_image_path=path
        )

    def apply_session_path(self, path):
        self.paths.append(path)
        self.page.image_path_row.path_edit.setText(path)

    def prepare_current(self, *, force=True):
        self.prepares += 1
        if self.admissions:
            return self.admissions.pop(0)
        return RequestAdmission(True, task_id=f"program-{self.cpu_id.value}-{self.prepares}")


class RamBinding:
    def __init__(self, backend):
        self.backend = backend
        self.paths = []
        self.prepares = []
        self.admissions = []

    def apply_session_path(self, target, path):
        self.paths.append((target, path))
        cpu = RuntimeCpuId.from_target_key(target)
        self.backend.target_resources[cpu] = replace(
            self.backend.target_resources[cpu], ram_image_path=path
        )

    def prepare(self, target):
        self.prepares.append(target)
        if self.admissions:
            return self.admissions.pop(0)
        return RequestAdmission(True, task_id=f"ram-{target}-{len(self.prepares)}")


class ReadBinding:
    def __init__(self):
        self.clears = 0

    def clear_connection_state(self):
        self.clears += 1


class Dialogs:
    def __init__(self):
        self.open_path = None
        self.save_path = None
        self.decision = DirtySessionDecision.DISCARD
        self.errors = []
        self.warnings = []
        self.information = []

    def choose_open_session(self, _parent):
        return self.open_path

    def choose_save_session(self, _parent, _current):
        return self.save_path

    def confirm_dirty_session(self, _parent, _display):
        return self.decision

    def show_error(self, _parent, title, message):
        self.errors.append((title, message))

    def show_warning(self, _parent, title, message):
        self.warnings.append((title, message))

    def show_information(self, _parent, title, message):
        self.information.append((title, message))


def setup_binding(cache=None):
    qt_app()
    window = BootloaderMainWindow()
    controller, backend = Controller(), Backend()
    store, cache = SessionStore(), cache or CacheStore()
    service = SessionApplicationService(store, cache, lambda: datetime.now(timezone.utc))
    program = ProgramBinding(backend, RuntimeCpuId.CPU1, window.program_cpu1_page)
    program_cpu2 = ProgramBinding(backend, RuntimeCpuId.CPU2, window.program_cpu2_page)
    programs = {RuntimeCpuId.CPU1: program, RuntimeCpuId.CPU2: program_cpu2}
    ram, read, dialogs = RamBinding(backend), ReadBinding(), Dialogs()
    binding = SessionGuiBinding(
        window,
        window.session_ribbon,
        controller,
        backend,
        service,
        window.program_cpu1_page,
        window.program_cpu2_page,
        window.advanced_page,
        programs,
        ram,
        read,
        dialogs,
    )
    return window, controller, backend, store, service, program, ram, read, dialogs, binding


def document_with_paths():
    targets = {
        RuntimeCpuId.CPU1: TargetSessionSettings(RuntimeCpuId.CPU1, "cpu1.out", "cpu1-ram.txt"),
        RuntimeCpuId.CPU2: TargetSessionSettings(RuntimeCpuId.CPU2, "cpu2.out", "cpu2-ram.txt"),
    }
    return SessionDocument(
        transport_configs={
            "sci_rs232": {
                "port": "COM7",
                "baudrate": 115200,
                "tx_timeout_ms": 11,
                "rx_timeout_ms": 22,
                "autobaud_timeout_ms": 33,
                "unknown": "preserved",
            },
            "future": {"host": "example"},
        },
        target_settings=targets,
    )


def document_with_sci(**overrides):
    sci = {
        "port": "COM7",
        "baudrate": 115200,
        "tx_timeout_ms": 11,
        "rx_timeout_ms": 22,
        "autobaud_timeout_ms": 33,
    }
    sci.update(overrides)
    return SessionDocument(transport_configs={"sci_rs232": sci})


def test_initial_untitled_applies_without_transition_or_parse():
    window, _, backend, _, service, program, ram, read, _, _ = setup_binding()
    assert service.state.display_name == "Untitled" and not service.state.is_dirty
    assert window.session_ribbon.current_value.text() == "Untitled"
    assert backend.changes == 0 and program.prepares == 0 and ram.prepares == []
    assert read.clears == 0


def test_open_applies_all_paths_and_reparses_supported_paths_sequentially(tmp_path):
    app = qt_app()
    window, controller, backend, store, _, program, ram, read, dialogs, binding = setup_binding()
    path = str((tmp_path / "session.json").resolve())
    store.documents[path] = document_with_paths()
    dialogs.open_path = path
    assert binding.open()
    app.processEvents()
    assert backend.changes == 1 and read.clears == 1
    assert program.paths[-1] == "cpu1.out"
    assert window.program_cpu2_page.image_path_row.path_edit.text() == "cpu2.out"
    assert window.program_cpu2_page.parse_status_row.badge.text() == "Not parsed"
    assert program.prepares == 1 and ram.prepares == []
    controller.taskFinished.emit(TaskExecutionResult("program-cpu1-1", TaskFinalStatus.SUCCEEDED, "ok", "ok"))
    app.processEvents()
    assert binding.program_bindings[RuntimeCpuId.CPU2].prepares == 1
    controller.taskFinished.emit(TaskExecutionResult("program-cpu2-1", TaskFinalStatus.SUCCEEDED, "ok", "ok"))
    app.processEvents()
    assert ram.prepares == ["cpu1"]
    controller.taskFinished.emit(TaskExecutionResult("ram-cpu1-1", TaskFinalStatus.CANCELLED, "bad", "bad", cancel_requested=True))
    app.processEvents()
    assert ram.prepares == ["cpu1", "cpu2"]


def test_user_edits_mark_dirty_and_save_preserves_unrepresented_fields(tmp_path):
    window, _, backend, store, service, _, _, _, dialogs, binding = setup_binding()
    original = document_with_paths()
    candidate = service.commit_switch(SessionSwitchCandidate(original, None, "Untitled"))
    assert not candidate.is_dirty
    materialized = binding._materialize_candidate(
        SessionSwitchCandidate(original, None, "Untitled")
    )
    binding._apply_materialization(materialized, queue_parses=False)
    window.operate_ribbon.sci_port_combo.setEditText("COM9")
    window.program_cpu1_page.image_path_row.path_edit.setText("new.out")
    assert service.state.is_dirty
    dialogs.save_path = str(tmp_path / "saved.json")
    assert binding.save_as()
    saved = store.saved[-1][1]
    assert saved.transport_configs["sci_rs232"]["unknown"] == "preserved"
    assert saved.transport_configs["future"]["host"] == "example"
    assert saved.target_settings[RuntimeCpuId.CPU1].program_image_path == "new.out"
    assert saved.target_settings[RuntimeCpuId.CPU1].erase_scope == original.target_settings[RuntimeCpuId.CPU1].erase_scope
    assert backend.changes == 0


def test_session_capture_reads_ram_paths_from_backend_resources() -> None:
    window, _, backend, _, _, _, _, _, _, binding = setup_binding()
    backend.target_resources[RuntimeCpuId.CPU1] = replace(
        backend.target_resources[RuntimeCpuId.CPU1], ram_image_path="backend-cpu1.txt"
    )
    backend.target_resources[RuntimeCpuId.CPU2] = replace(
        backend.target_resources[RuntimeCpuId.CPU2], ram_image_path="backend-cpu2.txt"
    )
    window.advanced_page.cpu1_ram_image_edit.setText("widget-cpu1.txt")
    window.advanced_page.cpu2_ram_image_edit.setText("widget-cpu2.txt")

    captured = binding._capture_document()

    assert captured.target_settings[RuntimeCpuId.CPU1].ram_image_path == "backend-cpu1.txt"
    assert captured.target_settings[RuntimeCpuId.CPU2].ram_image_path == "backend-cpu2.txt"


def test_dirty_cancel_discard_and_save_as_cancel_abort_transition(tmp_path):
    window, _, backend, store, service, _, _, _, dialogs, binding = setup_binding()
    window.program_cpu1_page.image_path_row.path_edit.setText("dirty.out")
    dialogs.decision = DirtySessionDecision.CANCEL
    assert not binding.new() and service.state.is_dirty and backend.changes == 0
    dialogs.decision = DirtySessionDecision.SAVE
    dialogs.save_path = None
    assert not binding.new() and service.state.is_dirty and backend.changes == 0
    dialogs.decision = DirtySessionDecision.DISCARD
    assert binding.new() and service.state.display_name == "Untitled" and backend.changes == 1


def test_failed_open_preserves_service_gui_and_runtime(tmp_path):
    window, _, backend, _, service, program, _, _, dialogs, binding = setup_binding()
    before = service.state
    dialogs.open_path = str(tmp_path / "missing.json")
    assert not binding.open()
    assert service.state == before and backend.changes == 0
    assert program.paths == [""] and dialogs.errors


def test_connected_and_active_task_gate_session_switching():
    window, controller, backend, _, service, _, _, _, dialogs, binding = setup_binding()
    info = ConnectionInfo("id", "SCI", "COM3", datetime.now(timezone.utc), "cpu1")
    controller.apply(RuntimeSnapshot(RuntimeState.CONNECTED, connection_info=info, active_target_key="cpu1"))
    assert not binding.new() and "Disconnect" in dialogs.information[-1][1]
    controller.apply(RuntimeSnapshot(RuntimeState.BUSY, active_task_id="task"))
    assert not binding.new() and "Wait" in dialogs.information[-1][1]
    assert service.state.display_name == "Untitled" and backend.changes == 0


def test_dirty_close_decisions():
    window, _, _, _, _, _, _, _, dialogs, binding = setup_binding()
    window.program_cpu1_page.image_path_row.path_edit.setText("dirty.out")
    dialogs.decision = DirtySessionDecision.CANCEL
    assert not binding.request_close()
    dialogs.decision = DirtySessionDecision.DISCARD
    assert binding.request_close()


def test_new_candidate_preparation_failure_changes_nothing(monkeypatch):
    window, _, backend, _, service, _, _, _, dialogs, binding = setup_binding()
    before = service.state
    binding._parse_queue = ["old"]
    monkeypatch.setattr(service, "prepare_new_untitled", lambda: (_ for _ in ()).throw(ValueError("candidate failed")))
    assert not binding.new()
    assert service.state is before and backend.changes == 0
    assert binding._parse_queue == ["old"] and dialogs.errors[-1][1] == "candidate failed"


def test_backend_failure_preserves_service_gui_and_parse_queue(tmp_path):
    window, _, backend, store, service, _, _, _, dialogs, binding = setup_binding()
    path = str((tmp_path / "new.session").resolve())
    store.documents[path] = document_with_paths()
    dialogs.open_path = path
    binding._parse_queue = ["old"]
    before_state = service.state
    before_gui = (
        window.operate_ribbon.sci_port_combo.currentText(),
        window.program_cpu1_page.image_path_row.path_edit.text(),
        window.advanced_page.cpu1_ram_image_edit.text(),
    )
    backend.error = RuntimeError("backend busy")
    assert not binding.open()
    assert service.state is before_state and backend.changes == 0
    assert binding._parse_queue == ["old"]
    assert before_gui == (
        window.operate_ribbon.sci_port_combo.currentText(),
        window.program_cpu1_page.image_path_row.path_edit.text(),
        window.advanced_page.cpu1_ram_image_edit.text(),
    )


def test_valid_open_commits_only_after_backend_transition(tmp_path):
    _, _, backend, store, service, _, _, _, dialogs, binding = setup_binding()
    path = str((tmp_path / "new.session").resolve())
    store.documents[path] = document_with_paths()
    dialogs.open_path = path
    old_state = service.state
    seen = []
    backend.on_change = lambda: seen.append(service.state)
    assert binding.open()
    assert seen == [old_state]
    assert service.state.path == Path(path) and backend.changes == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("port", 3, "sci_rs232.port"),
        ("baudrate", True, "sci_rs232.baudrate"),
        ("baudrate", "115200", "sci_rs232.baudrate"),
        ("baudrate", 12345, "not supported"),
        ("tx_timeout_ms", True, "sci_rs232.tx_timeout_ms"),
        ("rx_timeout_ms", "22", "sci_rs232.rx_timeout_ms"),
        ("autobaud_timeout_ms", -1, "sci_rs232.autobaud_timeout_ms"),
        ("tx_timeout_ms", 600001, "sci_rs232.tx_timeout_ms"),
    ),
)
def test_invalid_sci_values_fail_before_runtime_invalidation(
    tmp_path, field, value, message
):
    window, _, backend, store, service, program, ram, _, dialogs, binding = setup_binding()
    path = str((tmp_path / f"{field}.session").resolve())
    store.documents[path] = document_with_sci(**{field: value})
    dialogs.open_path = path
    before = service.state
    before_paths = (list(program.paths), list(ram.paths))
    assert not binding.open()
    assert service.state is before and backend.changes == 0
    assert (program.paths, ram.paths) == before_paths
    assert message in dialogs.errors[-1][1]


def test_missing_sci_fields_use_gui_defaults_and_preserve_unknowns_on_save(tmp_path):
    window, _, backend, store, _, _, _, _, dialogs, binding = setup_binding()
    binding._applying = True
    try:
        window.operate_ribbon.sci_port_combo.setEditText("COM9")
        window.operate_ribbon.sci_baud_combo.setCurrentText("57600")
        window.settings_page.current_tx_timeout.setValue(101)
        window.settings_page.current_rx_timeout.setValue(202)
        window.settings_page.current_autobaud_timeout.setValue(303)
    finally:
        binding._applying = False
    document = SessionDocument(
        transport_configs={"sci_rs232": {"unknown": "kept"}, "future": {"host": "x"}}
    )
    path = str((tmp_path / "missing-fields.session").resolve())
    store.documents[path] = document
    dialogs.open_path = path
    assert binding.open() and backend.changes == 1
    assert window.operate_ribbon.sci_port_combo.currentText() == "COM9"
    assert window.operate_ribbon.sci_baud_combo.currentText() == "57600"
    assert window.settings_page.current_tx_timeout.value() == 101
    dialogs.save_path = str(tmp_path / "saved.session")
    window.program_cpu1_page.image_path_row.path_edit.setText("dirty.out")
    assert binding.save_as()
    saved = store.saved[-1][1]
    assert saved.transport_configs["sci_rs232"]["unknown"] == "kept"
    assert saved.transport_configs["future"]["host"] == "x"


def test_unrelated_task_does_not_advance_or_drop_parse_queue(tmp_path):
    app = qt_app()
    _, controller, _, store, _, program, ram, _, dialogs, binding = setup_binding()
    path = str((tmp_path / "queue.session").resolve())
    store.documents[path] = document_with_paths()
    dialogs.open_path = path
    assert binding.open()
    app.processEvents()
    assert program.prepares == 1 and binding._parse_queue == ["program_cpu2", "ram_cpu1", "ram_cpu2"]
    controller.apply(RuntimeSnapshot(RuntimeState.BUSY, active_task_id="unrelated"))
    controller.taskFinished.emit(TaskExecutionResult("program-cpu1-1", TaskFinalStatus.SUCCEEDED, "ok", "ok"))
    controller.taskFinished.emit(TaskExecutionResult("unrelated", TaskFinalStatus.SUCCEEDED, "ok", "ok"))
    app.processEvents()
    assert ram.prepares == [] and binding._parse_queue == ["program_cpu2", "ram_cpu1", "ram_cpu2"]
    controller.apply(RuntimeSnapshot())
    app.processEvents()
    assert binding.program_bindings[RuntimeCpuId.CPU2].prepares == 1
    controller.taskFinished.emit(TaskExecutionResult("program-cpu2-1", TaskFinalStatus.SUCCEEDED, "ok", "ok"))
    app.processEvents()
    assert ram.prepares == ["cpu1"] and binding._parse_queue == ["ram_cpu2"]
    controller.taskFinished.emit(TaskExecutionResult("ram-cpu1-1", TaskFinalStatus.SUCCEEDED, "ok", "ok"))
    app.processEvents()
    assert ram.prepares == ["cpu1", "cpu2"]


def test_task_already_active_rejection_is_event_driven_and_lossless():
    app = qt_app()
    _, controller, _, _, _, _, ram, _, _, binding = setup_binding()
    rejection = RequestAdmission(
        False,
        rejection=RequestRejection(
            RequestRejectionCode.TASK_ALREADY_ACTIVE, "occupied"
        ),
    )
    ram.admissions = [rejection, RequestAdmission(True, task_id="ram-retry")]
    binding._parse_queue = ["ram_cpu1"]
    binding._schedule_parse_start()
    app.processEvents()
    assert ram.prepares == ["cpu1"] and binding._parse_queue == ["ram_cpu1"]
    app.processEvents()
    assert ram.prepares == ["cpu1"]
    controller.apply(RuntimeSnapshot(RuntimeState.BUSY, active_task_id="other"))
    controller.apply(RuntimeSnapshot())
    app.processEvents()
    assert ram.prepares == ["cpu1", "cpu1"] and binding._parse_queue == []


def test_permanent_idle_rejection_skips_only_failed_queue_item():
    app = qt_app()
    _, _, _, _, _, _, ram, _, _, binding = setup_binding()
    rejection = RequestAdmission(
        False,
        rejection=RequestRejection(
            RequestRejectionCode.INVALID_RUNTIME_STATE, "permanent"
        ),
    )
    ram.admissions = [rejection, RequestAdmission(True, task_id="cpu2")]
    binding._parse_queue = ["ram_cpu1", "ram_cpu2"]
    binding._schedule_parse_start()
    app.processEvents()
    app.processEvents()
    assert ram.prepares == ["cpu1", "cpu2"] and binding._parse_queue == []


def test_startup_runtime_cache_issue_is_shown_once_and_untitled_remains_usable():
    cache = CacheStore(PersistenceFormatError("bad cache bytes"))
    window, _, backend, _, service, _, _, _, dialogs, _ = setup_binding(cache)
    assert service.state.display_name == "Untitled" and not service.state.is_dirty
    assert service.recent_sessions() == () and cache.save_calls == 0
    assert dialogs.errors == [("Runtime Cache", "bad cache bytes")]
    assert backend.changes == 0
    assert window.session_ribbon.current_value.text() == "Untitled"
