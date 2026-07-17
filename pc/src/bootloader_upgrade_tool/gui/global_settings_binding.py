"""Global Settings v2 view binding."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from .persistence_models import GlobalCommandSettings, GlobalSettingsDocument
from .persistence_stores import GlobalSettingsStore


class GlobalSettingsDialogProvider(Protocol):
    def show_error(self, parent, title: str, message: str) -> None: ...
    def show_information(self, parent, title: str, message: str) -> None: ...


class _QtGlobalSettingsDialogProvider:
    def show_error(self, parent, title: str, message: str) -> None:
        QMessageBox.critical(parent, title, message)

    def show_information(self, parent, title: str, message: str) -> None:
        QMessageBox.information(parent, title, message)


class GlobalSettingsBinding(QObject):
    def __init__(
        self,
        main_window,
        settings_page,
        settings_ribbon,
        controller,
        runtime_backend,
        store: GlobalSettingsStore,
        internal_sci8_root: str,
        dialog_provider: GlobalSettingsDialogProvider | None = None,
        configuration_changed=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.page = settings_page
        self.ribbon = settings_ribbon
        self.controller = controller
        self.backend = runtime_backend
        self.store = store
        self.internal_sci8_root = internal_sci8_root
        self.dialogs = dialog_provider or _QtGlobalSettingsDialogProvider()
        self.configuration_changed = configuration_changed
        self._applying = False
        self._migrated = False
        self._baseline = GlobalSettingsDocument()
        self._candidate = self._baseline

        for signal in (
            self.page.hex2000_path.path_edit.textChanged,
            self.page.global_command_timeout.valueChanged,
            self.page.global_max_retries.valueChanged,
            self.page.global_retry_backoff.valueChanged,
            self.page.global_log_output_path.path_edit.textChanged,
        ):
            signal.connect(self._edited)
        self.page.save_global_button.clicked.connect(self.save)
        self.page.reload_global_button.clicked.connect(self.reload)
        self.ribbon.saveGlobalRequested.connect(self.save)
        self.ribbon.reloadGlobalRequested.connect(self.reload)
        self.controller.runtimeStateChanged.connect(lambda _snapshot: self._apply_gate())
        self._load(apply_backend=True)

    @property
    def document(self) -> GlobalSettingsDocument:
        return self._candidate

    def save(self) -> bool:
        if not self._gate_open():
            return False
        candidate = self._capture()
        try:
            self.store.save(candidate)
        except Exception as exc:
            self.dialogs.show_error(self.main_window, "Global Settings", str(exc))
            self._apply_gate()
            return False
        self._baseline = self._candidate = candidate
        self._migrated = False
        self._apply_backend(candidate)
        self._apply_gate()
        return True

    def reload(self) -> bool:
        if not self._gate_open():
            return False
        return self._load(apply_backend=True)

    def _load(self, *, apply_backend: bool) -> bool:
        try:
            result = self.store.load()
        except Exception as exc:
            document = GlobalSettingsDocument()
            self.dialogs.show_error(self.main_window, "Global Settings", str(exc))
            migrated = False
            notices: tuple[str, ...] = ()
            ok = False
        else:
            document = result.document
            migrated = result.migrated
            notices = result.notices
            ok = True
        self._baseline = self._candidate = document
        self._migrated = migrated
        self._apply_document(document)
        if apply_backend:
            self._apply_backend(document)
        for notice in notices:
            self.dialogs.show_information(self.main_window, "Global Settings Migration", notice)
        self._apply_gate()
        return ok

    def _apply_document(self, document: GlobalSettingsDocument) -> None:
        self._applying = True
        try:
            self.page.hex2000_path.path_edit.setText(document.hex2000_executable_path)
            self.page.global_command_timeout.setValue(document.command.timeout_ms)
            self.page.global_max_retries.setValue(document.command.max_retries)
            self.page.global_retry_backoff.setValue(document.command.retry_backoff_ms)
            self.page.global_log_output_path.path_edit.setText(document.log_output_path)
        finally:
            self._applying = False

    def _capture(self) -> GlobalSettingsDocument:
        return GlobalSettingsDocument(
            hex2000_executable_path=self.page.hex2000_path.path_edit.text(),
            command=GlobalCommandSettings(
                timeout_ms=self.page.global_command_timeout.value(),
                max_retries=self.page.global_max_retries.value(),
                retry_backoff_ms=self.page.global_retry_backoff.value(),
            ),
            log_output_path=self.page.global_log_output_path.path_edit.text(),
        )

    def _apply_backend(self, document: GlobalSettingsDocument) -> None:
        revision = self.backend.configuration_revision
        self.backend.set_image_tool_paths(document.hex2000_executable_path, self.internal_sci8_root)
        if self.backend.configuration_revision != revision and self.configuration_changed is not None:
            self.configuration_changed()

    def _edited(self, *_args) -> None:
        if self._applying:
            return
        self._candidate = self._capture()
        self._apply_gate()

    def _gate_open(self) -> bool:
        snapshot = self.controller.snapshot
        return snapshot.active_task_id is None and not snapshot.shutdown_requested

    def _apply_gate(self) -> None:
        enabled = self._gate_open()
        dirty = self._candidate != self._baseline or self._migrated
        self.page.set_global_v2_controls_enabled(enabled)
        for button in (self.page.save_global_button, self.ribbon.save_global_button):
            button.setEnabled(enabled and dirty)
        for button in (self.page.reload_global_button, self.ribbon.reload_global_button):
            button.setEnabled(enabled)


__all__ = ["GlobalSettingsBinding", "GlobalSettingsDialogProvider"]
