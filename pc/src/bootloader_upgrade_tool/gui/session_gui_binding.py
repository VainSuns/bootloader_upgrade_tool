"""Session lifecycle and GUI synchronization."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Protocol

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from .persistence_models import SessionDocument
from .recent_sessions_dialog import RecentSessionsDialog
from .runtime_models import RequestRejectionCode, RuntimeState
from .runtime_v2_models import EraseScope, RuntimeCpuId
from .session_application_service import SessionSwitchCandidate


class DirtySessionDecision(Enum):
    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class _SessionMaterialization:
    port: str
    baudrate: int
    tx_timeout_ms: int
    rx_timeout_ms: int
    autobaud_timeout_ms: int
    cpu1_program_path: str
    cpu2_program_path: str
    cpu1_ram_path: str
    cpu2_ram_path: str
    cpu1_erase_scope: EraseScope
    cpu1_custom_sector_mask: int
    cpu2_erase_scope: EraseScope
    cpu2_custom_sector_mask: int


class SessionDialogProvider(Protocol):
    def choose_open_session(self, parent) -> str | None: ...
    def choose_save_session(self, parent, current_path) -> str | None: ...
    def confirm_dirty_session(self, parent, display_name: str) -> DirtySessionDecision: ...
    def show_error(self, parent, title: str, message: str) -> None: ...
    def show_warning(self, parent, title: str, message: str) -> None: ...
    def show_information(self, parent, title: str, message: str) -> None: ...


class QtSessionDialogProvider:
    def choose_open_session(self, parent) -> str | None:
        path, _ = QFileDialog.getOpenFileName(parent, "Open Session", "", "Session (*.json);;All files (*)")
        return path or None

    def choose_save_session(self, parent, current_path) -> str | None:
        path, _ = QFileDialog.getSaveFileName(
            parent, "Save Session", str(current_path or ""), "Session (*.json);;All files (*)"
        )
        return path or None

    def confirm_dirty_session(self, parent, display_name: str) -> DirtySessionDecision:
        box = QMessageBox(QMessageBox.Icon.Warning, "Unsaved Session", f"Save changes to {display_name}?", parent=parent)
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return DirtySessionDecision.SAVE
        if box.clickedButton() is discard:
            return DirtySessionDecision.DISCARD
        return DirtySessionDecision.CANCEL

    def show_error(self, parent, title: str, message: str) -> None:
        QMessageBox.critical(parent, title, message)

    def show_warning(self, parent, title: str, message: str) -> None:
        QMessageBox.warning(parent, title, message)

    def show_information(self, parent, title: str, message: str) -> None:
        QMessageBox.information(parent, title, message)


class SessionGuiBinding(QObject):
    def __init__(
        self,
        main_window,
        session_ribbon,
        controller,
        runtime_backend,
        session_application_service,
        program_cpu1_page,
        program_cpu2_page,
        advanced_page,
        program_image_bindings,
        advanced_ram_binding,
        advanced_read_binding,
        dialog_provider: SessionDialogProvider | None = None,
        recent_dialog_factory=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.ribbon = session_ribbon
        self.controller = controller
        self.backend = runtime_backend
        self.service = session_application_service
        self.program_cpu1_page = program_cpu1_page
        self.program_cpu2_page = program_cpu2_page
        self.advanced_page = advanced_page
        bindings = dict(program_image_bindings)
        if set(bindings) != set(RuntimeCpuId):
            raise ValueError("program_image_bindings must contain exactly CPU1 and CPU2")
        self.program_bindings = (
            program_image_bindings
            if isinstance(program_image_bindings, type(MappingProxyType({})))
            else MappingProxyType(bindings)
        )
        self.ram_binding = advanced_ram_binding
        self.read_binding = advanced_read_binding
        self.dialogs = dialog_provider or QtSessionDialogProvider()
        self.recent_dialog_factory = recent_dialog_factory or RecentSessionsDialog
        self.recent_dialog = None
        self._applying = False
        self._parse_queue: list[str] = []
        self._parse_task_id: str | None = None
        self._submitting_parse = False
        self._completed_parse_ids: set[str] = set()
        self._parse_start_scheduled = False
        self._parse_schedule_generation = 0

        self.ribbon.newRequested.connect(self.new)
        self.ribbon.openRequested.connect(self.open)
        self.ribbon.saveRequested.connect(self.save)
        self.ribbon.saveAsRequested.connect(self.save_as)
        self.ribbon.recentRequested.connect(self.show_recent)
        self.controller.runtimeStateChanged.connect(self._runtime_state_changed)
        self.controller.taskStarted.connect(self._task_started)
        self.controller.taskFinished.connect(self._task_finished)
        for signal in (
            self.main_window.operate_ribbon.sci_port_combo.currentTextChanged,
            self.main_window.operate_ribbon.sci_baud_combo.currentTextChanged,
            self.main_window.settings_page.current_tx_timeout.valueChanged,
            self.main_window.settings_page.current_rx_timeout.valueChanged,
            self.main_window.settings_page.current_autobaud_timeout.valueChanged,
            self.program_cpu1_page.image_path_row.path_edit.textChanged,
            self.program_cpu2_page.image_path_row.path_edit.textChanged,
            self.advanced_page.cpu1_ram_image_edit.textChanged,
            self.advanced_page.cpu2_ram_image_edit.textChanged,
            self.advanced_page.erase_scope_combo.currentTextChanged,
            self.advanced_page.custom_sector_selector.selectionChanged,
        ):
            signal.connect(self._session_edited)
        initial = SessionSwitchCandidate(
            self.service.state.document,
            self.service.state.path,
            self.service.state.display_name,
        )
        self._apply_materialization(self._materialize_candidate(initial), queue_parses=False)
        self._render()
        for warning in self.service.startup_warnings:
            self.dialogs.show_error(self.main_window, "Runtime Cache", warning)

    def new(self) -> bool:
        if not self._begin_switch() or not self._resolve_dirty():
            return False
        try:
            candidate = self.service.prepare_new_untitled()
            materialized = self._materialize_candidate(candidate)
        except Exception as exc:
            self.dialogs.show_error(self.main_window, "Change Session", str(exc))
            return False
        return self._finish_switch(candidate, materialized)

    def open(self) -> bool:
        if not self._begin_switch() or not self._resolve_dirty():
            return False
        path = self.dialogs.choose_open_session(self.main_window)
        return self._open_path(path) if path else False

    def open_recent(self, path: str) -> bool:
        if not self._begin_switch() or not self._resolve_dirty():
            return False
        return self._open_path(path)

    def save(self) -> bool:
        if not self._save_gate_open():
            return False
        if self.service.state.path is None:
            return self.save_as()
        self.service.replace_document(self._capture_document())
        try:
            result = self.service.save()
        except Exception as exc:
            self.dialogs.show_error(self.main_window, "Save Session", str(exc))
            self._render()
            return False
        self._show_warnings(result.warnings)
        self._render()
        return True

    def save_as(self) -> bool:
        if not self._save_gate_open():
            return False
        path = self.dialogs.choose_save_session(self.main_window, self.service.state.path)
        if not path:
            return False
        self.service.replace_document(self._capture_document())
        try:
            result = self.service.save_as(path)
        except Exception as exc:
            self.dialogs.show_error(self.main_window, "Save Session", str(exc))
            self._render()
            return False
        self._show_warnings(result.warnings)
        self._render()
        return True

    def request_close(self) -> bool:
        return self._resolve_dirty()

    def show_recent(self) -> None:
        if self.recent_dialog is not None:
            self.recent_dialog.raise_()
            self.recent_dialog.activateWindow()
            return
        dialog = self.recent_dialog_factory(self.service.recent_sessions(), self.main_window)
        self.recent_dialog = dialog
        dialog.openRequested.connect(self._recent_open)
        dialog.removeRequested.connect(self._recent_remove)
        dialog.finished.connect(self._recent_closed)
        dialog.open()

    def _recent_open(self, path: str) -> None:
        if self.open_recent(path) and self.recent_dialog is not None:
            self.recent_dialog.close()

    def _recent_remove(self, path: str) -> None:
        try:
            entries = self.service.remove_recent_session(path)
        except Exception as exc:
            self.dialogs.show_error(self.main_window, "Recent Sessions", str(exc))
            return
        if self.recent_dialog is not None:
            self.recent_dialog.set_entries(entries)
        self._render()

    def _recent_closed(self, _result: int) -> None:
        self.recent_dialog = None

    def _begin_switch(self) -> bool:
        allowed, reason = self._switch_gate()
        if not allowed:
            self.dialogs.show_information(self.main_window, "Change Session", reason or "Session change is unavailable")
            return False
        return True

    def _resolve_dirty(self) -> bool:
        if not self.service.state.is_dirty:
            return True
        decision = self.dialogs.confirm_dirty_session(self.main_window, self.service.state.display_name)
        if decision is DirtySessionDecision.CANCEL:
            return False
        if decision is DirtySessionDecision.SAVE:
            return self.save()
        return True

    def _open_path(self, path: str) -> bool:
        try:
            candidate = self.service.prepare_open(path)
            materialized = self._materialize_candidate(candidate)
        except Exception as exc:
            self.dialogs.show_error(self.main_window, "Open Session", str(exc))
            return False
        return self._finish_switch(candidate, materialized)

    def _finish_switch(
        self,
        candidate: SessionSwitchCandidate,
        materialized: _SessionMaterialization,
    ) -> bool:
        try:
            self.backend.apply_session_change()
        except Exception as exc:
            self.dialogs.show_error(self.main_window, "Change Session", str(exc))
            return False
        self._cancel_parse_queue()
        self.service.commit_switch(candidate)
        self.read_binding.clear_connection_state()
        self.advanced_page.result_output.clear()
        self._apply_materialization(materialized, queue_parses=True)
        self._render()
        return True

    def _materialize_candidate(
        self, candidate: SessionSwitchCandidate
    ) -> _SessionMaterialization:
        document = candidate.document
        cpu1 = document.target_settings[RuntimeCpuId.CPU1]
        cpu2 = document.target_settings[RuntimeCpuId.CPU2]
        sci = document.transport_configs.get("sci_rs232", {})
        port = sci.get("port", self.main_window.operate_ribbon.sci_port_combo.currentText())
        if type(port) is not str:
            raise ValueError("sci_rs232.port must be a string")
        baud_combo = self.main_window.operate_ribbon.sci_baud_combo
        baudrate = sci.get("baudrate", int(baud_combo.currentText()))
        if type(baudrate) is not int:
            raise ValueError("sci_rs232.baudrate must be an integer")
        supported_baudrates = {int(baud_combo.itemText(index)) for index in range(baud_combo.count())}
        if baudrate not in supported_baudrates:
            raise ValueError("sci_rs232.baudrate is not supported by the Operate Ribbon")
        settings = self.main_window.settings_page

        self.backend.validate_erase_configuration(
            "cpu1", cpu1.erase_scope, cpu1.custom_sector_mask
        )
        self.backend.validate_erase_configuration(
            "cpu2", cpu2.erase_scope, cpu2.custom_sector_mask
        )

        def timeout(name: str, control) -> int:
            value = sci.get(name, control.value())
            if type(value) is not int:
                raise ValueError(f"sci_rs232.{name} must be an integer")
            if not control.minimum() <= value <= control.maximum():
                raise ValueError(
                    f"sci_rs232.{name} must be between {control.minimum()} and {control.maximum()}"
                )
            return value

        return _SessionMaterialization(
            port,
            baudrate,
            timeout("tx_timeout_ms", settings.current_tx_timeout),
            timeout("rx_timeout_ms", settings.current_rx_timeout),
            timeout("autobaud_timeout_ms", settings.current_autobaud_timeout),
            cpu1.program_image_path,
            cpu2.program_image_path,
            cpu1.ram_image_path,
            cpu2.ram_image_path,
            cpu1.erase_scope,
            cpu1.custom_sector_mask,
            cpu2.erase_scope,
            cpu2.custom_sector_mask,
        )

    def _apply_materialization(
        self, materialized: _SessionMaterialization, *, queue_parses: bool
    ) -> None:
        self._applying = True
        try:
            combo = self.main_window.operate_ribbon.sci_port_combo
            combo.setEditText(materialized.port)
            self.main_window.operate_ribbon.sci_baud_combo.setCurrentText(
                str(materialized.baudrate)
            )
            settings = self.main_window.settings_page
            settings.current_tx_timeout.setValue(materialized.tx_timeout_ms)
            settings.current_rx_timeout.setValue(materialized.rx_timeout_ms)
            settings.current_autobaud_timeout.setValue(materialized.autobaud_timeout_ms)
            self.program_bindings[RuntimeCpuId.CPU1].apply_session_path(materialized.cpu1_program_path)
            self.program_bindings[RuntimeCpuId.CPU2].apply_session_path(materialized.cpu2_program_path)
            self.ram_binding.apply_session_path("cpu1", materialized.cpu1_ram_path)
            self.ram_binding.apply_session_path("cpu2", materialized.cpu2_ram_path)
            self.backend.set_erase_configuration(
                "cpu1",
                materialized.cpu1_erase_scope,
                materialized.cpu1_custom_sector_mask,
            )
            self.backend.set_erase_configuration(
                "cpu2",
                materialized.cpu2_erase_scope,
                materialized.cpu2_custom_sector_mask,
            )
        finally:
            self._applying = False
        self._parse_queue = [
            kind
            for kind, path in (
                ("program_cpu1", materialized.cpu1_program_path),
                ("program_cpu2", materialized.cpu2_program_path),
                ("ram_cpu1", materialized.cpu1_ram_path),
                ("ram_cpu2", materialized.cpu2_ram_path),
            )
            if path.strip()
        ] if queue_parses else []
        self._schedule_parse_start()

    def _capture_document(self) -> SessionDocument:
        document = self.service.state.document
        configs = dict(document.transport_configs)
        sci = dict(configs.get("sci_rs232", {}))
        port_combo = self.main_window.operate_ribbon.sci_port_combo
        port = port_combo.currentText().strip()
        index = port_combo.currentIndex()
        if index >= 0 and port == port_combo.itemText(index).strip():
            port = port_combo.itemData(index) or port
        settings = self.main_window.settings_page
        sci.update(
            port=str(port),
            baudrate=int(self.main_window.operate_ribbon.sci_baud_combo.currentText()),
            tx_timeout_ms=settings.current_tx_timeout.value(),
            rx_timeout_ms=settings.current_rx_timeout.value(),
            autobaud_timeout_ms=settings.current_autobaud_timeout.value(),
        )
        configs["sci_rs232"] = MappingProxyType(sci)
        targets = dict(document.target_settings)
        resources = self.backend.target_resources
        targets[RuntimeCpuId.CPU1] = replace(
            targets[RuntimeCpuId.CPU1],
            program_image_path=resources[RuntimeCpuId.CPU1].program_image_path,
            ram_image_path=resources[RuntimeCpuId.CPU1].ram_image_path,
            erase_scope=resources[RuntimeCpuId.CPU1].erase_scope,
            custom_sector_mask=resources[RuntimeCpuId.CPU1].custom_sector_mask,
        )
        targets[RuntimeCpuId.CPU2] = replace(
            targets[RuntimeCpuId.CPU2],
            program_image_path=resources[RuntimeCpuId.CPU2].program_image_path,
            ram_image_path=resources[RuntimeCpuId.CPU2].ram_image_path,
            erase_scope=resources[RuntimeCpuId.CPU2].erase_scope,
            custom_sector_mask=resources[RuntimeCpuId.CPU2].custom_sector_mask,
        )
        return replace(document, transport_configs=configs, target_settings=targets)

    def _session_edited(self, *_args) -> None:
        if self._applying:
            return
        try:
            self.service.replace_document(self._capture_document())
        except (TypeError, ValueError):
            return
        self._render()

    def _switch_gate(self) -> tuple[bool, str | None]:
        snapshot = self.controller.snapshot
        if snapshot.active_task_id is not None or snapshot.cleanup_pending or snapshot.shutdown_requested or snapshot.disconnect_decision_pending:
            return False, "Wait for the current task or transition to finish before changing Session."
        connected = snapshot.state is not RuntimeState.DISCONNECTED or any(
            value is not None
            for value in (snapshot.connection_info, snapshot.active_target_key)
        )
        if connected:
            return False, "Disconnect before changing Session."
        if any(value is not None for value in (self.backend.active_session, self.backend.active_transport, self.backend.connection_info, self.backend.pending_close, self.backend.runtime_v2_snapshot.connection)):
            return False, "Disconnect before changing Session."
        return True, None

    def _save_gate_open(self) -> bool:
        snapshot = self.controller.snapshot
        return snapshot.active_task_id is None and not snapshot.shutdown_requested

    def _render(self) -> None:
        state = self.service.state
        self.ribbon.set_session_state(current=state.display_name, modified=state.is_dirty, path=str(state.path) if state.path else None)
        switch, reason = self._switch_gate()
        save = self._save_gate_open()
        self.ribbon.set_action_states(
            new_enabled=switch,
            open_enabled=switch,
            save_enabled=save and state.is_dirty,
            save_as_enabled=save,
            recent_enabled=switch,
            switch_reason=reason,
        )

    def _runtime_state_changed(self, snapshot) -> None:
        self._render()
        if snapshot.shutdown_requested:
            self._cancel_parse_queue()
        elif self._parse_task_id is None and self._parse_idle():
            self._schedule_parse_start()

    def _parse_idle(self) -> bool:
        snapshot = self.controller.snapshot
        return (
            snapshot.state is RuntimeState.DISCONNECTED
            and snapshot.active_task_id is None
            and not snapshot.cleanup_pending
            and not snapshot.shutdown_requested
        )

    def _schedule_parse_start(self) -> None:
        if (
            not self._parse_queue
            or self._parse_task_id is not None
            or self._parse_start_scheduled
            or not self._parse_idle()
        ):
            return
        self._parse_start_scheduled = True
        generation = self._parse_schedule_generation
        QTimer.singleShot(0, lambda: self._start_next_parse(generation))

    def _start_next_parse(self, generation: int) -> None:
        if generation != self._parse_schedule_generation:
            return
        self._parse_start_scheduled = False
        if self._parse_task_id is not None or not self._parse_queue:
            return
        if not self._parse_idle():
            return
        kind = self._parse_queue[0]
        self._submitting_parse = True
        if kind.startswith("program_"):
            admission = self.program_bindings[
                RuntimeCpuId.from_target_key(kind.removeprefix("program_"))
            ].prepare_current(force=True)
        else:
            admission = self.ram_binding.prepare(kind.removeprefix("ram_"))
        self._submitting_parse = False
        if admission is not None and admission.accepted:
            self._parse_queue.pop(0)
            if admission.task_id in self._completed_parse_ids:
                self._completed_parse_ids.remove(admission.task_id)
            else:
                self._parse_task_id = admission.task_id
            return
        transient = bool(
            admission is not None
            and admission.rejection is not None
            and admission.rejection.code is RequestRejectionCode.TASK_ALREADY_ACTIVE
        ) or self.controller.snapshot.active_task_id is not None
        if transient:
            return
        self._parse_queue.pop(0)
        self._schedule_parse_start()

    def _task_started(self, state) -> None:
        if self._submitting_parse:
            self._parse_task_id = state.task_id

    def _task_finished(self, result) -> None:
        if result.task_id != self._parse_task_id:
            return
        if self._submitting_parse:
            self._completed_parse_ids.add(result.task_id)
        self._parse_task_id = None
        self._schedule_parse_start()

    def _cancel_parse_queue(self) -> None:
        self._parse_schedule_generation += 1
        self._parse_start_scheduled = False
        self._parse_queue.clear()
        self._parse_task_id = None
        self._completed_parse_ids.clear()

    def _show_warnings(self, warnings: tuple[str, ...]) -> None:
        for warning in warnings:
            self.dialogs.show_warning(self.main_window, "Session Saved", warning)


__all__ = [
    "DirtySessionDecision",
    "QtSessionDialogProvider",
    "SessionDialogProvider",
    "SessionGuiBinding",
]
