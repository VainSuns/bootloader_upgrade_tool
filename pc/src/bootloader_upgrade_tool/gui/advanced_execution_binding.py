"""Advanced Flash App execution binding."""

from __future__ import annotations

from dataclasses import dataclass
import json

from PySide6.QtCore import QObject, Signal, Slot

from ..operations import operation_result_to_dict
from .advanced_execution_models import (
    AdvancedFlashAppRunSnapshot,
    FLASH_APP_RUN_CPU,
    FLASH_APP_RUN_TARGET_KEY,
    RunAdvancedFlashAppRequest,
)
from .runtime_models import RuntimeState, TaskFinalStatus
from .runtime_v2_models import ConnectionGeneration, DataFreshness
from .status_models import MetadataStatusSnapshot


@dataclass(frozen=True, slots=True)
class _RunContext:
    connection_id: str
    target_key: str
    connection_generation: ConnectionGeneration
    metadata_snapshot: MetadataStatusSnapshot
    entry_point: int


class AdvancedExecutionBinding(QObject):
    _runtime_transition_received = Signal(object)

    def __init__(self, page, controller, backend, parent: QObject | None = None) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self._pending: _RunContext | None = None
        self._owned: dict[str, _RunContext] = {}

        page.runFlashAppRequested.connect(self.run_flash_app)
        controller.runtimeStateChanged.connect(lambda _snapshot: self.refresh())
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        self._runtime_transition_received.connect(self._apply_runtime_transition)
        self._runtime_v2_listener = self._receive_runtime_transition_from_backend
        backend.subscribe_runtime_v2(self._runtime_v2_listener)
        self.destroyed.connect(
            lambda _object, backend=backend, listener=self._runtime_v2_listener:
                backend.unsubscribe_runtime_v2(listener)
        )
        self.refresh()

    def refresh(self) -> None:
        context = self._current_context()
        self.page.set_execution_entry_point(
            f"0x{context.entry_point:08X}" if context is not None else "—"
        )
        self.page.set_execution_controls_enabled(run_flash_app=context is not None)

    def run_flash_app(self):
        context = self._current_context()
        if context is None:
            self.refresh()
            return None
        request = RunAdvancedFlashAppRequest(
            context.connection_id,
            context.target_key,
            context.connection_generation,
            context.metadata_snapshot,
            context.entry_point,
        )
        self._pending = context
        try:
            admission = self.controller.request_task(request)
        finally:
            self._pending = None
        if admission.accepted:
            self._owned.setdefault(admission.task_id, context)
        else:
            self._show({
                "operation": "run_flash_app",
                "status": "REJECTED",
                "message": admission.rejection.message if admission.rejection else "Request rejected",
            })
        return admission

    def _current_context(self) -> _RunContext | None:
        snapshot = self.controller.snapshot
        info = snapshot.connection_info
        context = self.backend.active_target_context
        runtime = self.backend.runtime_v2_snapshot
        metadata_state = runtime.metadata_state
        metadata = metadata_state.value
        if not (
            snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
            and not snapshot.cleanup_pending
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
            and info is not None
            and context is not None
            and runtime.connection is not None
            and context.cpu_id is FLASH_APP_RUN_CPU
            and context.target_key == FLASH_APP_RUN_TARGET_KEY
            and info.target_key == context.target_key == snapshot.active_target_key
            and context.connection.connection_id == info.connection_id
            and context.connection.cpu_id is context.cpu_id
            and runtime.connection == context.connection
            and context.connection.generation == runtime.connection_generation
            and getattr(context.profile.command_set, "run", None) is not None
            and metadata_state.freshness is DataFreshness.FRESH
            and type(metadata) is MetadataStatusSnapshot
            and metadata.connection_id == info.connection_id
            and metadata.target_key == context.target_key
            and metadata.metadata_valid is True
            and metadata.image_valid is True
            and metadata.entry_point_valid is True
            and type(metadata.raw_metadata.entry_point) is int
            and metadata.raw_metadata.entry_point >= 0
        ):
            return None
        return _RunContext(
            info.connection_id,
            context.target_key,
            context.connection.generation,
            metadata,
            metadata.raw_metadata.entry_point,
        )

    def _task_started(self, state) -> None:
        if self._pending is not None:
            self._owned[state.task_id] = self._pending

    def _task_finished(self, result) -> None:
        context = self._owned.pop(result.task_id, None)
        if context is None:
            return
        payload = result.payload
        if result.status is TaskFinalStatus.SUCCEEDED and (
            type(payload) is not AdvancedFlashAppRunSnapshot
            or payload.connection_id != context.connection_id
            or payload.target_key != context.target_key
            or payload.connection_generation != context.connection_generation
            or payload.metadata_snapshot != context.metadata_snapshot
            or payload.entry_point != context.entry_point
        ):
            return
        value = {
            "operation": "run_flash_app",
            "connection_id": context.connection_id,
            "target_key": context.target_key,
            "entry_point": f"0x{context.entry_point:08X}",
            "status": result.status.name,
            "connection_release_requested": result.completion_action.name == "RELEASE_CONNECTION",
        }
        if type(payload) is AdvancedFlashAppRunSnapshot:
            value["operation_result"] = operation_result_to_dict(payload.operation_result)
        elif result.error is not None:
            value["error"] = {
                "code": result.error.code,
                "stage": result.error.stage,
                "message": result.error.message,
            }
        self._show(value)
        self.refresh()

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self._runtime_transition_received.emit(result)

    @Slot(object)
    def _apply_runtime_transition(self, _result) -> None:
        self.refresh()

    def _show(self, value: dict[str, object]) -> None:
        self.page.result_output.setPlainText(json.dumps(value, indent=2, sort_keys=True))


__all__ = ["AdvancedExecutionBinding"]
