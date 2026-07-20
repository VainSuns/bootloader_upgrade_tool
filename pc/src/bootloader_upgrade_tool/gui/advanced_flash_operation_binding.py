"""Current-target binding for independent Advanced Flash operations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QSignalBlocker, Signal, Slot

from .advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    AdvancedFlashOperationSnapshot,
    AdvancedFlashOperationType,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
)
from .flash_service_models import (
    FlashServiceResourceStatus,
    PreparedFlashServiceSummary,
)
from .flash_write_models import FlashWriteOperationType, FlashWritePlan
from .runtime_models import RuntimeState, TaskFinalStatus
from .runtime_v2_models import (
    ConnectionGeneration,
    EraseScope,
    ImageParseStatus,
    RuntimeCpuId,
)
from .widgets.sector_selector import FlashSectorOption


_SCOPE_BY_LABEL = {
    "Required App Sectors": EraseScope.REQUIRED_APP_SECTORS,
    "Entire Application Region": EraseScope.ENTIRE_APPLICATION_REGION,
    "Custom Sector Mask": EraseScope.CUSTOM,
}

_OPERATION_SCOPE = {
    EraseScope.REQUIRED_APP_SECTORS: AdvancedFlashEraseScope.REQUIRED_APP_SECTORS,
    EraseScope.ENTIRE_APPLICATION_REGION: AdvancedFlashEraseScope.ENTIRE_APPLICATION_REGION,
    EraseScope.CUSTOM: AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK,
}

_PROGRAM_MATERIALIZATION_ERROR_CODES = frozenset({
    "INVALID_IMAGE_PATH",
    "UNSUPPORTED_IMAGE_TYPE",
    "GLOBAL_SETTINGS_LOAD_FAILED",
    "HEX2000_CONFIGURATION_INVALID",
    "HEX2000_NOT_FOUND",
    "IMAGE_PARSE_FAILED",
    "IMAGE_CONVERSION_FAILED",
    "IMAGE_FILE_ACCESS_FAILED",
    "IMAGE_CHANGED_DURING_PREPARATION",
    "IMAGE_VALIDATION_FAILED",
    "IMAGE_CHANGED",
})


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    operation_type: AdvancedFlashOperationType
    connection_id: str
    target_key: str
    image_source_path: str
    image_selection_revision: int
    image_tool_configuration_revision: int
    expected_image_identity: object
    expected_effective_sector_mask: int
    service_configuration_revision: int
    service_tool_configuration_revision: int
    expected_connection_generation: ConnectionGeneration
    expected_service_summary: PreparedFlashServiceSummary
    transport_label: str
    endpoint_label: str
    erase_scope: AdvancedFlashEraseScope | None = None
    erase_sector_mask: int | None = None


class AdvancedFlashOperationBinding(QObject):
    _runtime_transition_received = Signal(object)

    def __init__(
        self, page, controller, backend, confirmation_coordinator,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self.confirmation_coordinator = confirmation_coordinator
        self._pending: _OwnedTask | None = None
        self._owned: dict[str, _OwnedTask] = {}

        page.flashEraseRequested.connect(self.erase)
        page.flashProgramOnlyRequested.connect(self.program_only)
        page.flashVerifyOnlyRequested.connect(self.verify_only)
        page.erase_scope_combo.currentTextChanged.connect(self._scope_edited)
        page.custom_sector_selector.selectionChanged.connect(self._custom_selection_edited)
        page.cpu1_flash_image_edit.textChanged.connect(lambda _text: self.refresh())
        page.cpu2_flash_image_edit.textChanged.connect(lambda _text: self.refresh())
        controller.runtimeStateChanged.connect(lambda _snapshot: self.refresh())
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        self._runtime_transition_received.connect(self._apply_runtime_transition)
        self._runtime_v2_listener = self._receive_runtime_transition_from_backend
        backend.subscribe_runtime_v2(self._runtime_v2_listener)
        self.destroyed.connect(
            lambda _object, backend=backend, listener=self._runtime_v2_listener: backend.unsubscribe_runtime_v2(listener)
        )
        self.refresh()

    def erase(self):
        context = self._current_context(AdvancedFlashOperationType.ERASE)
        if context is None or context.erase_scope is None:
            self.refresh()
            return None
        request = EraseAdvancedFlashRequest(
            **self._identity_values(context),
            erase_scope=context.erase_scope,
            custom_sector_mask=context.erase_sector_mask or 0,
        )
        plan = self._write_plan(context, FlashWriteOperationType.ERASE)
        if not self.confirmation_coordinator.present(
            plan, request, lambda shown, frozen: self._confirm(context, shown, frozen)
        ):
            return None
        return plan

    def program_only(self):
        context = self._current_context(AdvancedFlashOperationType.PROGRAM_ONLY)
        if context is None:
            self.refresh()
            return None
        request = ProgramAdvancedFlashRequest(**self._identity_values(context))
        plan = self._write_plan(context, FlashWriteOperationType.PROGRAM_ONLY)
        if not self.confirmation_coordinator.present(
            plan, request, lambda shown, frozen: self._confirm(context, shown, frozen)
        ):
            return None
        return plan

    def verify_only(self):
        context = self._current_context(AdvancedFlashOperationType.VERIFY_ONLY)
        if context is None:
            self.refresh()
            return None
        return self._submit(context, VerifyAdvancedFlashRequest(**self._identity_values(context)))

    def refresh(self) -> None:
        self._render_sector_controls()
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

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self._runtime_transition_received.emit(result)

    @Slot(object)
    def _apply_runtime_transition(self, _result) -> None:
        self.refresh()

    def _render_sector_controls(self) -> None:
        snapshot = self.controller.snapshot
        info = snapshot.connection_info
        profile = self.backend.active_target
        if not (
            snapshot.state is RuntimeState.CONNECTED
            and info is not None
            and snapshot.active_target_key == info.target_key
            and profile is not None
            and profile.memory_map.flash is not None
        ):
            with QSignalBlocker(self.page.erase_scope_combo), QSignalBlocker(
                self.page.custom_sector_selector
            ):
                self.page.erase_scope_combo.setCurrentIndex(-1)
                self.page.custom_sector_selector.set_sectors(())
            self.page.erase_scope_combo.setEnabled(False)
            self.page.custom_sector_selector.setEnabled(False)
            return

        cpu_id = RuntimeCpuId.from_target_key(info.target_key)
        resource = self.backend.target_resources[cpu_id]
        flash = profile.memory_map.flash
        options = tuple(
            FlashSectorOption(
                sector.sector_id,
                sector.start,
                sector.end_exclusive - 1,
                sector.bit_index,
                protected=bool(
                    (1 << sector.bit_index) & flash.forbidden_erase_mask
                    or (1 << sector.bit_index) & ~flash.allowed_erase_mask
                ),
            )
            for sector in flash.sectors
        )
        selected = tuple(
            sector.sector_id
            for sector in flash.sectors
            if resource.custom_sector_mask & (1 << sector.bit_index)
        )
        label = next(text for text, scope in _SCOPE_BY_LABEL.items() if scope is resource.erase_scope)
        with QSignalBlocker(self.page.erase_scope_combo), QSignalBlocker(
            self.page.custom_sector_selector
        ):
            self.page.erase_scope_combo.setCurrentText(label)
            self.page.custom_sector_selector.set_sectors(
                options, selected_sector_ids=selected
            )
        editable = bool(
            snapshot.active_task_id is None
            and not snapshot.shutdown_requested
            and not snapshot.cleanup_pending
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
        )
        self.page.erase_scope_combo.setEnabled(editable)
        self.page.custom_sector_selector.setEnabled(
            editable and resource.erase_scope is EraseScope.CUSTOM
        )

    def _scope_edited(self, text: str) -> None:
        info = self.controller.snapshot.connection_info
        scope = _SCOPE_BY_LABEL.get(text)
        if info is None or scope is None:
            return
        resource = self.backend.target_resources[RuntimeCpuId.from_target_key(info.target_key)]
        self.backend.set_erase_configuration(
            info.target_key, scope, resource.custom_sector_mask
        )

    def _custom_selection_edited(self, _ids, mask: int) -> None:
        info = self.controller.snapshot.connection_info
        if info is None:
            return
        resource = self.backend.target_resources[RuntimeCpuId.from_target_key(info.target_key)]
        self.backend.set_erase_configuration(info.target_key, resource.erase_scope, mask)

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
        resource = self.backend.target_resources[RuntimeCpuId.CPU1]
        service_state = self.backend.flash_service_resource_state
        if (
            resource.program_image_parse_status is not ImageParseStatus.READY
            or resource.program_image_summary is None
            or not resource.program_image_path.strip()
            or service_state.status is not FlashServiceResourceStatus.READY
            or service_state.summary is None
        ):
            return None
        image_summary = resource.program_image_summary
        image_path = str(Path(resource.program_image_path).expanduser().resolve(strict=False))
        service_summary = service_state.summary
        runtime = self.backend.runtime_v2_snapshot
        connection = runtime.connection
        revision = self.backend.configuration_revision
        if not (
            self.backend.advanced_flash_selection_revision("cpu1") >= 0
            and service_summary.target_key == "cpu1"
            and service_state.revision == self.backend.service_configuration_revision
            and connection is not None
            and connection.connection_id == info.connection_id
            and connection.cpu_id is RuntimeCpuId.CPU1
            and connection.generation == runtime.connection_generation
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
            flash = profile.memory_map.flash
            scope = _OPERATION_SCOPE[resource.erase_scope]
            if flash is None:
                return None
            if scope is AdvancedFlashEraseScope.REQUIRED_APP_SECTORS:
                mask = image_summary.sector_mask
                if not mask & flash.metadata_sector_mask:
                    return None
            elif scope is AdvancedFlashEraseScope.ENTIRE_APPLICATION_REGION:
                mask = flash.allowed_erase_mask
            else:
                mask = resource.custom_sector_mask
            if mask == 0 or mask & flash.forbidden_erase_mask or mask & ~flash.allowed_erase_mask:
                return None

        return _OwnedTask(
            operation_type,
            info.connection_id,
            "cpu1",
            image_path,
            self.backend.advanced_flash_selection_revision("cpu1"),
            revision,
            image_summary.identity,
            image_summary.sector_mask,
            service_state.revision,
            revision,
            runtime.connection_generation,
            service_summary,
            connection.transport_label,
            connection.endpoint_label,
            scope,
            mask,
        )

    def _confirm(self, context: _OwnedTask, _plan: FlashWritePlan, request: object):
        if self._submission_context_current(context):
            return self._submit(context, request)
        self._show({
            "operation": context.operation_type.name,
            "status": "confirmation_rejected",
            "code": "FLASH_WRITE_PLAN_STALE",
            "message": "Flash write inputs changed. Review the current state and confirm again.",
        })
        self.refresh()
        return None

    def _submission_context_current(self, context: _OwnedTask) -> bool:
        return self._current_context(context.operation_type) == context

    @staticmethod
    def _write_plan(
        context: _OwnedTask, operation_type: FlashWriteOperationType
    ) -> FlashWritePlan:
        return FlashWritePlan(
            plan_id=uuid4().hex,
            operation_type=operation_type,
            cpu_id=RuntimeCpuId.CPU1,
            connection_id=context.connection_id,
            connection_generation=context.expected_connection_generation,
            transport_label=context.transport_label,
            endpoint_label=context.endpoint_label,
            image_source_path=context.image_source_path,
            image_selection_revision=context.image_selection_revision,
            image_tool_configuration_revision=context.image_tool_configuration_revision,
            image_identity=context.expected_image_identity,
            effective_sector_mask=context.expected_effective_sector_mask,
            service_configuration_revision=context.service_configuration_revision,
            service_tool_configuration_revision=context.service_tool_configuration_revision,
            service_summary=context.expected_service_summary,
            erase_scope=context.erase_scope,
            erase_sector_mask=context.erase_sector_mask,
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
        service_failure = bool(
            context is not None and self._current_service_failure(context, result)
        )
        program_failure = bool(
            context is not None and self._current_program_failure(context, result)
        )
        unmatched_program_failure = bool(
            result.status is TaskFinalStatus.FAILED
            and result.payload is None
            and result.error is not None
            and result.error.code in _PROGRAM_MATERIALIZATION_ERROR_CODES
            and not program_failure
        )
        if context is None or (
            not service_failure
            and (
                unmatched_program_failure
                or (not program_failure and not self._context_current(context))
            )
        ):
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
                "metadata_refresh_result": payload.metadata_refresh_result_dict(),
                "metadata_summary": self._plain_metadata(payload.metadata_snapshot),
                "warning": self._plain_warning(result.warning),
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
                value["metadata_refresh_result"] = payload.metadata_refresh_result_dict()
                value["metadata_summary"] = self._plain_metadata(payload.metadata_snapshot)
            value["warning"] = self._plain_warning(result.warning)
            self._show(value)
        self.refresh()

    def _current_service_failure(self, context: _OwnedTask, result) -> bool:
        state = self.backend.flash_service_resource_state
        return bool(
            result.status is TaskFinalStatus.FAILED
            and result.payload is None
            and result.error is not None
            and self._non_service_context_current(context)
            and state.status in {
                FlashServiceResourceStatus.STALE,
                FlashServiceResourceStatus.ERROR,
                FlashServiceResourceStatus.UNAVAILABLE,
            }
            and state.revision == context.service_configuration_revision + 1
            and state.error_code == result.error.code
        )

    def _current_program_failure(self, context: _OwnedTask, result) -> bool:
        resource = self.backend.target_resources[RuntimeCpuId.CPU1]
        try:
            path = str(Path(resource.program_image_path).expanduser().resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            return False
        snapshot = self.controller.snapshot
        disconnected = (
            snapshot.state is RuntimeState.DISCONNECTED
            and snapshot.active_task_id is None
            and snapshot.connection_info is None
            and snapshot.active_target_key is None
            and not snapshot.cleanup_pending
        )
        info = snapshot.connection_info
        connected = (
            snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
            and not snapshot.cleanup_pending
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
            and info is not None
            and info.connection_id == context.connection_id
            and info.target_key == context.target_key
            and snapshot.active_target_key == context.target_key
        )
        return bool(
            result.status is TaskFinalStatus.FAILED
            and result.payload is None
            and result.error is not None
            and context.target_key == "cpu1"
            and resource.program_image_parse_status is ImageParseStatus.ERROR
            and resource.program_image_summary is None
            and path == context.image_source_path
            and self.backend.advanced_flash_selection_revision("cpu1")
            == context.image_selection_revision
            and resource.program_image_parse_error
            == f"Code: {result.error.code}\n{result.error.message}"
            and self.backend.service_configuration_revision
            == context.service_configuration_revision
            and context.service_tool_configuration_revision
            == self.backend.configuration_revision
            and (
                Path(context.image_source_path).suffix.lower() == ".txt"
                or context.image_tool_configuration_revision
                == self.backend.configuration_revision
            )
            and (connected or disconnected)
        )

    def _context_current(self, context: _OwnedTask) -> bool:
        if not (
            self._non_service_context_current(context)
            and context.service_configuration_revision
            == self.backend.service_configuration_revision
        ):
            return False

        return True

    def _non_service_context_current(self, context: _OwnedTask) -> bool:
        resource = self.backend.target_resources[RuntimeCpuId.CPU1]
        summary = resource.program_image_summary
        try:
            path = str(Path(resource.program_image_path).expanduser().resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            path = ""
        if not (
            context.image_selection_revision
            == self.backend.advanced_flash_selection_revision("cpu1")
            and resource.program_image_parse_status is ImageParseStatus.READY
            and summary is not None
            and path == context.image_source_path
            and summary.identity == context.expected_image_identity
            and summary.sector_mask == context.expected_effective_sector_mask
            and (
                Path(context.image_source_path).suffix.lower() == ".txt"
                or context.image_tool_configuration_revision
                == self.backend.configuration_revision
            )
            and context.service_tool_configuration_revision
            == self.backend.configuration_revision
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
    def _identity_values(context: _OwnedTask) -> dict[str, object]:
        return {
            "connection_id": context.connection_id,
            "target_key": context.target_key,
            "image_source_path": context.image_source_path,
            "image_selection_revision": context.image_selection_revision,
            "image_tool_configuration_revision": context.image_tool_configuration_revision,
            "expected_image_identity": context.expected_image_identity,
            "expected_effective_sector_mask": context.expected_effective_sector_mask,
            "service_configuration_revision": context.service_configuration_revision,
            "service_tool_configuration_revision": context.service_tool_configuration_revision,
            "expected_connection_generation": context.expected_connection_generation,
            "expected_service_summary": context.expected_service_summary,
        }

    @staticmethod
    def _plain_warning(warning):
        if warning is None:
            return None
        return {
            "code": warning.code,
            "message": warning.message,
            "stage": warning.stage,
            "details": AdvancedFlashOperationBinding._plain_value(warning.details),
        }

    @staticmethod
    def _plain_value(value):
        if value is None or type(value) in (bool, int, float, str):
            return value
        if isinstance(value, dict) or hasattr(value, "items"):
            return {
                key: AdvancedFlashOperationBinding._plain_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [AdvancedFlashOperationBinding._plain_value(item) for item in value]
        raise TypeError(f"Unsupported Shared Result value: {type(value).__name__}")

    @staticmethod
    def _plain_metadata(snapshot):
        if snapshot is None:
            return None
        raw = snapshot.raw_metadata
        return {
            "metadata_valid": snapshot.metadata_valid,
            "image_valid": snapshot.image_valid,
            "entry_point_valid": snapshot.entry_point_valid,
            "boot_attempt_present": snapshot.boot_attempt_present,
            "app_confirmed": snapshot.app_confirmed,
            "confirmed_bootable": snapshot.confirmed_bootable,
            "entry_point": raw.entry_point,
            "image_size_words": raw.image_size_words,
            "image_crc32": raw.image_crc32,
            "boot_attempt_count": raw.boot_attempt_count,
        }

    def _show(self, value: dict[str, object]) -> None:
        self.page.result_output.setPlainText(json.dumps(value, indent=2, sort_keys=True))


__all__ = ["AdvancedFlashOperationBinding"]
