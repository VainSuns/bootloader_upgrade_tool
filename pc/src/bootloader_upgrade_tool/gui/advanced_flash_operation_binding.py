"""Current-target binding for independent Advanced Flash operations."""

from __future__ import annotations

from dataclasses import dataclass
import json

from PySide6.QtCore import QObject

from .advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    AdvancedFlashOperationSnapshot,
    AdvancedFlashOperationType,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
)
from .flash_service_models import FlashServiceResourceStatus
from .runtime_models import RuntimeState, TaskFinalStatus


_SCOPE_BY_LABEL = {
    "Required App Sectors": AdvancedFlashEraseScope.REQUIRED_APP_SECTORS,
    "Entire Application Region": AdvancedFlashEraseScope.ENTIRE_APPLICATION_REGION,
    "Custom Sector Mask": AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK,
}


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    operation_type: AdvancedFlashOperationType
    connection_id: str
    target_key: str
    image_selection_revision: int
    image_tool_configuration_revision: int
    service_configuration_revision: int
    service_tool_configuration_revision: int
    erase_scope: AdvancedFlashEraseScope | None = None
    erase_sector_mask: int | None = None


class AdvancedFlashOperationBinding(QObject):
    def __init__(self, page, controller, backend, parent: QObject | None = None) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self._pending: _OwnedTask | None = None
        self._owned: dict[str, _OwnedTask] = {}

        page.flashEraseRequested.connect(self.erase)
        page.flashProgramOnlyRequested.connect(self.program_only)
        page.flashVerifyOnlyRequested.connect(self.verify_only)
        page.erase_scope_combo.currentTextChanged.connect(lambda _text: self.refresh())
        page.custom_sector_selector.selectionChanged.connect(lambda _ids, _mask: self.refresh())
        page.cpu1_flash_image_edit.textChanged.connect(lambda _text: self.refresh())
        page.cpu2_flash_image_edit.textChanged.connect(lambda _text: self.refresh())
        controller.runtimeStateChanged.connect(lambda _snapshot: self.refresh())
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        self.refresh()

    def erase(self):
        context = self._current_context(AdvancedFlashOperationType.ERASE)
        if context is None or context.erase_scope is None:
            self.refresh()
            return None
        request = EraseAdvancedFlashRequest(
            context.connection_id,
            context.target_key,
            context.image_selection_revision,
            context.image_tool_configuration_revision,
            context.service_configuration_revision,
            context.service_tool_configuration_revision,
            context.erase_scope,
            context.erase_sector_mask or 0,
        )
        return self._submit(context, request)

    def program_only(self):
        context = self._current_context(AdvancedFlashOperationType.PROGRAM_ONLY)
        if context is None:
            self.refresh()
            return None
        return self._submit(context, ProgramAdvancedFlashRequest(*self._identity_values(context)))

    def verify_only(self):
        context = self._current_context(AdvancedFlashOperationType.VERIFY_ONLY)
        if context is None:
            self.refresh()
            return None
        return self._submit(context, VerifyAdvancedFlashRequest(*self._identity_values(context)))

    def refresh(self) -> None:
        erase = self._current_context(AdvancedFlashOperationType.ERASE)
        program = self._current_context(AdvancedFlashOperationType.PROGRAM_ONLY)
        verify = self._current_context(AdvancedFlashOperationType.VERIFY_ONLY)
        self.page.set_flash_operation_controls_enabled(
            erase=erase is not None,
            program_only=program is not None,
            verify_only=verify is not None,
        )

    def tool_configuration_changed(self) -> None:
        self.refresh()

    def _current_context(self, operation_type: AdvancedFlashOperationType) -> _OwnedTask | None:
        snapshot = self.controller.snapshot
        info = snapshot.connection_info
        if not (
            snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
            and not snapshot.cleanup_pending
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
            and info is not None
            and info.target_key == "cpu1"
            and snapshot.active_target_key == "cpu1"
        ):
            return None
        image_cache = self.backend.prepared_advanced_flash_image_cache("cpu1")
        service_state = self.backend.flash_service_resource_state
        if (
            image_cache is None
            or service_state.status is not FlashServiceResourceStatus.READY
            or service_state.summary is None
        ):
            return None
        image_summary = image_cache[1]
        service_summary = service_state.summary
        revision = self.backend.configuration_revision
        if not (
            image_summary.target_key == "cpu1"
            and image_summary.selection_revision
            == self.backend.advanced_flash_selection_revision("cpu1")
            and image_summary.configuration_revision == revision
            and service_summary.target_key == "cpu1"
            and service_state.revision == self.backend.service_configuration_revision
        ):
            return None
        profile = self.backend.active_target
        if profile is None:
            return None
        commands = profile.command_set
        common = (
            "get_service_status",
            "service_attach",
            "ram_load_begin",
            "ram_load_data",
            "ram_load_end",
            "ram_check_crc",
        )
        required = {
            AdvancedFlashOperationType.ERASE: (*common, "erase"),
            AdvancedFlashOperationType.PROGRAM_ONLY: (*common, "program_begin", "program_data", "program_end"),
            AdvancedFlashOperationType.VERIFY_ONLY: (*common, "verify_begin", "verify_data", "verify_end"),
        }[operation_type]
        if any(getattr(commands, field, None) is None for field in required):
            return None

        scope = None
        mask = None
        if operation_type is AdvancedFlashOperationType.ERASE:
            scope = _SCOPE_BY_LABEL.get(self.page.erase_scope_combo.currentText())
            flash = profile.memory_map.flash
            if scope is None or flash is None:
                return None
            if scope is AdvancedFlashEraseScope.REQUIRED_APP_SECTORS:
                mask = image_cache[0].sector_mask | flash.metadata_sector_mask
            elif scope is AdvancedFlashEraseScope.ENTIRE_APPLICATION_REGION:
                mask = flash.allowed_erase_mask
            else:
                mask = self.page.custom_sector_selector.selected_mask()
            if mask == 0 or mask & flash.forbidden_erase_mask or mask & ~flash.allowed_erase_mask:
                return None

        return _OwnedTask(
            operation_type,
            info.connection_id,
            "cpu1",
            image_summary.selection_revision,
            image_summary.configuration_revision,
            service_state.revision,
            revision,
            scope,
            mask,
        )

    def _submit(self, context: _OwnedTask, request):
        self._pending = context
        admission = self.controller.request_task(request)
        if admission.accepted:
            self._owned.setdefault(admission.task_id, context)
        self._pending = None
        if not admission.accepted and self._context_current(context):
            self._show({
                "operation": context.operation_type.name,
                "status": "rejected",
                "message": admission.rejection.message if admission.rejection else "Request rejected",
            })
        return admission

    def _task_started(self, state) -> None:
        if self._pending is not None:
            self._owned[state.task_id] = self._pending

    def _task_finished(self, result) -> None:
        context = self._owned.pop(result.task_id, None)
        if context is None or not self._context_current(context):
            self.refresh()
            return
        if result.status in {
            TaskFinalStatus.SUCCEEDED,
            TaskFinalStatus.CANCELLED,
            TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST,
        }:
            payload = result.payload
            if type(payload) is not AdvancedFlashOperationSnapshot or not self._payload_current(context, payload):
                self.refresh()
                return
            self._show({
                "operation": context.operation_type.name,
                "connection_id": context.connection_id,
                "target_key": context.target_key,
                "image_selection_revision": context.image_selection_revision,
                "image_tool_configuration_revision": context.image_tool_configuration_revision,
                "service_configuration_revision": context.service_configuration_revision,
                "service_tool_configuration_revision": context.service_tool_configuration_revision,
                "erase_scope": context.erase_scope.name if context.erase_scope else None,
                "erase_sector_mask": (
                    f"0x{context.erase_sector_mask:08X}" if context.erase_sector_mask is not None else None
                ),
                "status": result.status.name,
                "result": payload.operation_result_dict(),
            })
        elif result.status is TaskFinalStatus.FAILED:
            payload = result.payload
            if payload is not None and (
                type(payload) is not AdvancedFlashOperationSnapshot
                or not self._payload_current(context, payload)
            ):
                self.refresh()
                return
            value = {
                "operation": context.operation_type.name,
                "connection_id": context.connection_id,
                "target_key": context.target_key,
                "image_selection_revision": context.image_selection_revision,
                "image_tool_configuration_revision": context.image_tool_configuration_revision,
                "service_configuration_revision": context.service_configuration_revision,
                "service_tool_configuration_revision": context.service_tool_configuration_revision,
                "status": "FAILED",
                "error": ({
                    "code": result.error.code,
                    "stage": result.error.stage,
                    "message": result.error.message,
                } if result.error else None),
            }
            if payload is not None:
                value["result"] = payload.operation_result_dict()
            self._show(value)
        self.refresh()

    def _context_current(self, context: _OwnedTask) -> bool:
        if not (
            context.image_selection_revision == self.backend.advanced_flash_selection_revision("cpu1")
            and context.image_tool_configuration_revision == self.backend.configuration_revision
            and context.service_configuration_revision == self.backend.service_configuration_revision
            and context.service_tool_configuration_revision == self.backend.configuration_revision
        ):
            return False
        snapshot = self.controller.snapshot
        if (
            snapshot.state is RuntimeState.DISCONNECTED
            and snapshot.active_task_id is None
            and snapshot.connection_info is None
            and snapshot.active_target_key is None
            and not snapshot.cleanup_pending
        ):
            return True
        info = snapshot.connection_info
        return bool(
            info is not None
            and info.connection_id == context.connection_id
            and info.target_key == context.target_key
            and snapshot.active_target_key == context.target_key
        )

    def _payload_current(self, context: _OwnedTask, payload: AdvancedFlashOperationSnapshot) -> bool:
        return (
            payload.connection_id == context.connection_id
            and payload.target_key == context.target_key
            and payload.image_selection_revision == context.image_selection_revision
            and payload.image_tool_configuration_revision == context.image_tool_configuration_revision
            and payload.service_configuration_revision == context.service_configuration_revision
            and payload.service_tool_configuration_revision == context.service_tool_configuration_revision
            and payload.operation_type is context.operation_type
            and payload.erase_scope is context.erase_scope
            and payload.erase_sector_mask == context.erase_sector_mask
            and self._context_current(context)
        )

    @staticmethod
    def _identity_values(context: _OwnedTask) -> tuple[object, ...]:
        return (
            context.connection_id,
            context.target_key,
            context.image_selection_revision,
            context.image_tool_configuration_revision,
            context.service_configuration_revision,
            context.service_tool_configuration_revision,
        )

    def _show(self, value: dict[str, object]) -> None:
        self.page.result_output.setPlainText(json.dumps(value, indent=2, sort_keys=True))


__all__ = ["AdvancedFlashOperationBinding"]
