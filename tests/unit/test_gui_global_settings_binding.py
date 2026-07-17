from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.global_settings_binding import GlobalSettingsBinding
from bootloader_upgrade_tool.gui.main_window import BootloaderMainWindow
from bootloader_upgrade_tool.gui.persistence_models import (
    DocumentLoadResult,
    GlobalCommandSettings,
    GlobalSettingsDocument,
)
from bootloader_upgrade_tool.gui.persistence_stores import GlobalSettingsStore
from bootloader_upgrade_tool.gui.runtime_models import RuntimeSnapshot, RuntimeState


def qt_app():
    return QApplication.instance() or QApplication([])


class Controller(QObject):
    runtimeStateChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self.snapshot = RuntimeSnapshot()

    def apply(self, snapshot):
        self.snapshot = snapshot
        self.runtimeStateChanged.emit(snapshot)


class Backend:
    def __init__(self):
        self.configuration_revision = 0
        self.calls = []

    def set_image_tool_paths(self, hex_path, sci8_root):
        self.calls.append((hex_path, sci8_root))
        self.configuration_revision += 1


class Store:
    def __init__(self, result):
        self.result = result
        self.saved = []
        self.save_error = None

    def load(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def save(self, document):
        if self.save_error:
            raise self.save_error
        self.saved.append(document)


class Dialogs:
    def __init__(self):
        self.errors = []
        self.information = []

    def show_error(self, _parent, title, message):
        self.errors.append((title, message))

    def show_information(self, _parent, title, message):
        self.information.append((title, message))


def make_binding(store):
    qt_app()
    window = BootloaderMainWindow()
    controller, backend, dialogs = Controller(), Backend(), Dialogs()
    binding = GlobalSettingsBinding(
        window,
        window.settings_page,
        window.settings_ribbon,
        controller,
        backend,
        store,
        "internal-cache",
        dialogs,
    )
    return window, controller, backend, dialogs, binding


def test_missing_store_applies_defaults_without_creating_file(tmp_path):
    path = tmp_path / "global.json"
    window, _, backend, _, binding = make_binding(GlobalSettingsStore(path))
    assert binding.document == GlobalSettingsDocument()
    assert not path.exists()
    assert backend.calls == [("", "internal-cache")]
    assert not window.settings_page.save_global_button.isEnabled()


def test_current_v2_populates_exact_controls_and_only_captures_v2_fields():
    document = GlobalSettingsDocument(
        hex2000_executable_path="hex.exe",
        command=GlobalCommandSettings(123, 2, 45),
        log_output_path="logs",
    )
    store = Store(DocumentLoadResult(document, 2))
    window, _, _, _, binding = make_binding(store)
    page = window.settings_page
    assert page.hex2000_path.path_edit.text() == "hex.exe"
    assert (page.global_command_timeout.value(), page.global_max_retries.value(), page.global_retry_backoff.value()) == (123, 2, 45)
    assert page.global_log_output_path.path_edit.text() == "logs"
    page.set_flash_service_resource_state(
        provider="test", image_path="service.out", map_path="service.map", status="Ready"
    )
    page.current_tx_timeout.setValue(99)
    page.global_max_retries.setValue(3)
    assert binding.save()
    assert store.saved[-1] == GlobalSettingsDocument(
        hex2000_executable_path="hex.exe",
        command=GlobalCommandSettings(123, 3, 45),
        log_output_path="logs",
    )


def test_migration_notices_enable_save_without_auto_save():
    store = Store(DocumentLoadResult(GlobalSettingsDocument(), 1, True, ("old field removed",)))
    window, _, _, dialogs, _ = make_binding(store)
    assert window.settings_page.save_global_button.isEnabled()
    assert store.saved == []
    assert dialogs.information[-1][1] == "old field removed"


def test_malformed_load_reports_error_displays_defaults_and_does_not_save():
    store = Store(ValueError("malformed"))
    window, _, backend, dialogs, binding = make_binding(store)
    assert binding.document == GlobalSettingsDocument()
    assert dialogs.errors and store.saved == []
    assert window.settings_page.hex2000_path.path_edit.text() == ""
    assert backend.calls[-1] == ("", "internal-cache")


def test_save_failure_preserves_baseline_and_backend_configuration():
    original = GlobalSettingsDocument(hex2000_executable_path="old.exe")
    store = Store(DocumentLoadResult(original, 2))
    window, _, backend, dialogs, binding = make_binding(store)
    before_calls = list(backend.calls)
    window.settings_page.hex2000_path.path_edit.setText("new.exe")
    store.save_error = OSError("readonly")
    assert not binding.save()
    assert backend.calls == before_calls and dialogs.errors
    assert window.settings_page.save_global_button.isEnabled()


def test_reload_discards_edits_and_runtime_gate_disables_actions():
    document = GlobalSettingsDocument(hex2000_executable_path="saved.exe")
    store = Store(DocumentLoadResult(document, 2))
    window, controller, _, _, binding = make_binding(store)
    window.settings_page.hex2000_path.path_edit.setText("dirty.exe")
    assert window.settings_page.save_global_button.isEnabled()
    assert binding.reload()
    assert window.settings_page.hex2000_path.path_edit.text() == "saved.exe"
    controller.apply(RuntimeSnapshot(RuntimeState.BUSY, active_task_id="task"))
    assert not window.settings_page.save_global_button.isEnabled()
    assert not window.settings_page.reload_global_button.isEnabled()
    assert not window.settings_page.hex2000_path.isEnabled()
