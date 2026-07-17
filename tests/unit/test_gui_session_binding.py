from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.main_window import BootloaderMainWindow
from bootloader_upgrade_tool.gui.persistence_models import (
    DocumentLoadResult,
    RuntimeCacheDocument,
    SessionDocument,
    TargetSessionSettings,
)
from bootloader_upgrade_tool.gui.runtime_models import (
    ConnectionInfo,
    RequestAdmission,
    RuntimeSnapshot,
    RuntimeState,
    TaskExecutionResult,
    TaskFinalStatus,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import RuntimeCpuId
from bootloader_upgrade_tool.gui.session_application_service import SessionApplicationService
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
    def __init__(self):
        self.document = RuntimeCacheDocument()

    def load(self):
        return DocumentLoadResult(self.document, 1)

    def save(self, document):
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
        self.changes = 0

    def apply_session_change(self):
        self.changes += 1
        return object()


class ProgramBinding:
    def __init__(self):
        self.paths = []
        self.prepares = 0

    def apply_session_path(self, path):
        self.paths.append(path)

    def prepare_current(self, *, force=True):
        self.prepares += 1
        return RequestAdmission(True, task_id=f"program-{self.prepares}")


class RamBinding:
    def __init__(self):
        self.paths = []
        self.prepares = []

    def apply_session_path(self, target, path):
        self.paths.append((target, path))

    def prepare(self, target):
        self.prepares.append(target)
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


def setup_binding():
    qt_app()
    window = BootloaderMainWindow()
    controller, backend = Controller(), Backend()
    store, cache = SessionStore(), CacheStore()
    service = SessionApplicationService(store, cache, lambda: datetime.now(timezone.utc))
    program, ram, read, dialogs = ProgramBinding(), RamBinding(), ReadBinding(), Dialogs()
    binding = SessionGuiBinding(
        window,
        window.session_ribbon,
        controller,
        backend,
        service,
        window.program_cpu1_page,
        window.program_cpu2_page,
        window.advanced_page,
        program,
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
    controller.taskFinished.emit(TaskExecutionResult("program-1", TaskFinalStatus.SUCCEEDED, "ok", "ok"))
    app.processEvents()
    assert ram.prepares == ["cpu1"]
    controller.taskFinished.emit(TaskExecutionResult("ram-cpu1-1", TaskFinalStatus.CANCELLED, "bad", "bad", cancel_requested=True))
    app.processEvents()
    assert ram.prepares == ["cpu1", "cpu2"]


def test_user_edits_mark_dirty_and_save_preserves_unrepresented_fields(tmp_path):
    window, _, backend, store, service, _, _, _, dialogs, binding = setup_binding()
    original = document_with_paths()
    service.replace_document(original)
    service._baseline = original
    binding._apply_document(original, queue_parses=False)
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
