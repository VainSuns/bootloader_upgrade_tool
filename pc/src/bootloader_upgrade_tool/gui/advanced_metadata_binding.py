"""Current-target binding for independent Advanced Metadata operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject

from .advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
    AdvancedMetadataOperationType,
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from .flash_service_models import (
    FlashServiceResourceStatus,
    PreparedFlashServiceSummary,
)
from .flash_write_models import FlashWriteOperationType, FlashWritePlan
from .runtime_models import RuntimeState, TaskFinalStatus
from .runtime_v2_models import (
    ConnectionGeneration,
    DataFreshness,
    ImageParseStatus,
    RuntimeCpuId,
    VerifyEvidence,
)
from .status_models import MetadataStatusSnapshot


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
    operation_type: AdvancedMetadataOperationType
    cpu_id: RuntimeCpuId
    connection_id: str
    target_key: str
    image_source_path: str | None
    image_selection_revision: int | None
    image_tool_configuration_revision: int | None
    expected_image_identity: object | None
    expected_effective_sector_mask: int | None
    service_configuration_revision: int
    service_tool_configuration_revision: int
    expected_connection_generation: ConnectionGeneration
    expected_service_summary: PreparedFlashServiceSummary
    expected_metadata_snapshot: MetadataStatusSnapshot | None
    transport_label: str
    endpoint_label: str
    expected_verify_evidence: VerifyEvidence | None
    entry_point: int
    image_size_words: int
    image_crc32: int
    app_end: int | None


class AdvancedMetadataOperationBinding(QObject):
    def __init__(
        self,
        page,
        controller,
        backend,
        confirmation_coordinator,
        *,
        apply_metadata_snapshot=None,
        clear_metadata=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self.confirmation_coordinator = confirmation_coordinator
        self._pending: _OwnedTask | None = None
        self._owned: dict[str, _OwnedTask] = {}

        page.writeImageValidRequested.connect(self.write_image_valid)
        page.writeBootAttemptRequested.connect(self.write_boot_attempt)
        page.writeAppConfirmedRequested.connect(self.write_app_confirmed)
        page.cpu1_flash_image_edit.textChanged.connect(lambda _text: self.refresh())
        page.cpu2_flash_image_edit.textChanged.connect(lambda _text: self.refresh())
        controller.runtimeStateChanged.connect(lambda _snapshot: self.refresh())
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        self.refresh()

    def write_image_valid(self):
        return self._submit_operation(AdvancedMetadataOperationType.WRITE_IMAGE_VALID)

    def write_boot_attempt(self):
        return self._submit_operation(AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT)

    def write_app_confirmed(self):
        return self._submit_operation(AdvancedMetadataOperationType.WRITE_APP_CONFIRMED)

    def refresh(self) -> None:
        contexts = {
            operation: self._current_context(operation)
            for operation in AdvancedMetadataOperationType
        }
        self.page.set_metadata_operation_controls_enabled(
            image_valid=contexts[AdvancedMetadataOperationType.WRITE_IMAGE_VALID] is not None,
            boot_attempt=contexts[AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT] is not None,
            app_confirmed=contexts[AdvancedMetadataOperationType.WRITE_APP_CONFIRMED] is not None,
        )

    def tool_configuration_changed(self) -> None:
        self.refresh()

    def _submit_operation(self, operation_type):
        context = self._current_context(operation_type)
        if context is None:
            self.refresh()
            return None
        values = {
            "connection_id": context.connection_id,
            "target_key": context.target_key,
            "service_configuration_revision": context.service_configuration_revision,
            "service_tool_configuration_revision": context.service_tool_configuration_revision,
            "expected_connection_generation": context.expected_connection_generation,
            "expected_service_summary": context.expected_service_summary,
            "expected_metadata_snapshot": context.expected_metadata_snapshot,
        }
        if operation_type is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            request = WriteAdvancedImageValidRequest(
                **values,
                image_source_path=context.image_source_path,
                image_selection_revision=context.image_selection_revision,
                image_tool_configuration_revision=context.image_tool_configuration_revision,
                expected_image_identity=context.expected_image_identity,
                expected_effective_sector_mask=context.expected_effective_sector_mask,
                expected_verify_evidence=context.expected_verify_evidence,
            )
        elif operation_type is AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT:
            request = WriteAdvancedBootAttemptRequest(**values)
        else:
            request = WriteAdvancedAppConfirmedRequest(**values)
        plan = self._write_plan(context)
        if not self.confirmation_coordinator.present(
            plan, request, lambda shown, frozen: self._confirm(context, shown, frozen)
        ):
            return None
        return plan

    def _current_context(self, operation_type) -> _OwnedTask | None:
        snapshot = self.controller.snapshot
        info = snapshot.connection_info
        context = self.backend.active_target_context
        if not (
            snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
            and not snapshot.cleanup_pending
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
            and info is not None
            and context is not None
            and context.connection.connection_id == info.connection_id
            and snapshot.active_target_key == info.target_key == context.target_key
            and context.connection.cpu_id is context.cpu_id
            and context.resource.cpu_id is context.cpu_id
        ):
            return None
        service_state = self.backend.flash_service_resource_state
        profile = context.profile
        try:
            profile_cpu_id = RuntimeCpuId.from_target_key(f"cpu{int(profile.cpu_id)}")
            target_cpu_id = RuntimeCpuId.from_target_key(context.target_key)
        except (AttributeError, TypeError, ValueError):
            return None
        if (
            service_state.status is not FlashServiceResourceStatus.READY
            or service_state.summary is None
            or profile_cpu_id is not context.cpu_id
            or target_cpu_id is not context.cpu_id
        ):
            return None
        service_summary = service_state.summary
        connection = context.connection
        revision = self.backend.configuration_revision
        if not (
            service_summary.target_key == context.target_key
            and service_state.revision == self.backend.service_configuration_revision
        ):
            return None
        commands = profile.command_set
        if any(
            getattr(commands, field, None) is None
            for field in (
                "get_service_status", "service_attach", "ram_load_begin",
                "ram_load_data", "ram_load_end", "ram_check_crc",
                "get_metadata_summary", "metadata_append_record",
            )
        ):
            return None

        resource = context.resource
        evidence = metadata_snapshot = None
        image_path = None
        image_selection_revision = image_tool_revision = None
        identity = None
        sector_mask = None
        app_end = None
        if operation_type is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            image_summary = resource.program_image_summary
            if (
                resource.program_image_parse_status is not ImageParseStatus.READY
                or image_summary is None
                or not resource.program_image_path.strip()
            ):
                return None
            image_path = str(Path(resource.program_image_path).expanduser().resolve(strict=False))
            image_selection_revision = self.backend.advanced_flash_selection_revision(
                context.target_key
            )
            image_tool_revision = revision
            identity = image_summary.identity
            sector_mask = image_summary.sector_mask
            app_end = identity.app_end
            evidence = resource.verify_evidence
            if not (
                type(evidence) is VerifyEvidence
                and evidence.cpu_id is context.cpu_id
                and evidence.connection_generation == self.backend.connection_generation
                and connection.generation == evidence.connection_generation
                and evidence.image_identity == image_summary.identity
            ):
                return None
        else:
            metadata_snapshot = self._matching_metadata_snapshot(
                info.connection_id, context.target_key
            )
            if metadata_snapshot is None:
                return None
            raw = metadata_snapshot.raw_metadata
            if operation_type is AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT:
                if (
                    metadata_snapshot.app_confirmed
                    or raw.boot_attempt_limit <= 0
                    or raw.boot_attempt_limit > 3
                    or raw.boot_attempt_count >= raw.boot_attempt_limit
                    or raw.boot_attempt_count >= 3
                ):
                    return None
            elif not metadata_snapshot.boot_attempt_present or metadata_snapshot.app_confirmed:
                return None
        return _OwnedTask(
            operation_type,
            context.cpu_id,
            info.connection_id,
            context.target_key,
            image_path,
            image_selection_revision,
            image_tool_revision,
            identity,
            sector_mask,
            service_state.revision,
            revision,
            connection.generation,
            service_summary,
            metadata_snapshot,
            connection.transport_label,
            connection.endpoint_label,
            evidence,
            identity.entry_point if identity is not None else raw.entry_point,
            identity.image_size_words if identity is not None else raw.image_size_words,
            identity.image_crc32 if identity is not None else raw.image_crc32,
            app_end,
        )

    def _matching_metadata_snapshot(self, connection_id, target_key):
        state = self.backend.runtime_v2_snapshot.metadata_state
        snapshot = state.value
        if type(snapshot) is not MetadataStatusSnapshot:
            return None
        raw = snapshot.raw_metadata
        return snapshot if (
            state.freshness is DataFreshness.FRESH
            and snapshot.connection_id == connection_id
            and snapshot.target_key == target_key
            and snapshot.metadata_valid
            and snapshot.image_valid
        ) else None

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

    def _submit(self, context: _OwnedTask, request: object):
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

    @staticmethod
    def _write_plan(context: _OwnedTask) -> FlashWritePlan:
        operation_type = {
            AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
                FlashWriteOperationType.WRITE_IMAGE_VALID,
            AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT:
                FlashWriteOperationType.WRITE_BOOT_ATTEMPT,
            AdvancedMetadataOperationType.WRITE_APP_CONFIRMED:
                FlashWriteOperationType.WRITE_APP_CONFIRMED,
        }[context.operation_type]
        return FlashWritePlan(
            plan_id=uuid4().hex,
            operation_type=operation_type,
            cpu_id=context.cpu_id,
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
            verify_evidence=context.expected_verify_evidence,
            metadata_snapshot=context.expected_metadata_snapshot,
        )

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
                or (
                    not program_failure
                    and not self._submitted_context_current(context)
                )
            )
        ):
            self.refresh()
            return
        payload = result.payload
        if payload is not None and (
            type(payload) is not AdvancedMetadataOperationSnapshot
            or not self._payload_current(context, payload)
        ):
            self.refresh()
            return
        self._show(self._result_document(result, context, payload))
        self.refresh()

    def _current_service_failure(self, context, result) -> bool:
        state = self.backend.flash_service_resource_state
        resource = self.backend.target_resources.get(context.cpu_id)
        return bool(
            result.status is TaskFinalStatus.FAILED
            and result.payload is None
            and result.error is not None
            and self._non_service_context_current(context)
            and (
                context.operation_type
                is not AdvancedMetadataOperationType.WRITE_IMAGE_VALID
                or (
                    resource is not None
                    and resource.verify_evidence == context.expected_verify_evidence
                )
            )
            and state.status in {
                FlashServiceResourceStatus.STALE,
                FlashServiceResourceStatus.ERROR,
                FlashServiceResourceStatus.UNAVAILABLE,
            }
            and state.revision == context.service_configuration_revision + 1
            and state.error_code == result.error.code
        )

    def _current_program_failure(self, context, result) -> bool:
        if context.operation_type is not AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            return False
        resource = self.backend.target_resources.get(context.cpu_id)
        try:
            target_cpu_id = RuntimeCpuId.from_target_key(context.target_key)
        except (TypeError, ValueError):
            return False
        if (
            target_cpu_id is not context.cpu_id
            or resource is None
            or resource.cpu_id is not context.cpu_id
        ):
            return False
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
        active = self.backend.active_target_context
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
            and active is not None
            and active.cpu_id is context.cpu_id
            and active.target_key == context.target_key
            and active.connection.connection_id == context.connection_id
            and active.connection.cpu_id is context.cpu_id
            and active.resource.cpu_id is context.cpu_id
        )
        return bool(
            result.status is TaskFinalStatus.FAILED
            and result.payload is None
            and result.error is not None
            and resource.program_image_parse_status is ImageParseStatus.ERROR
            and resource.program_image_summary is None
            and path == context.image_source_path
            and self.backend.advanced_flash_selection_revision(context.target_key)
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

    def _result_document(self, result, context, payload):
        primary_data = payload.primary_result_dict() if payload is not None else None
        primary_summary = primary_data.get("summary", {}) if primary_data is not None else {}
        value = {
            "task_id": result.task_id,
            "operation": context.operation_type.name,
            "connection_id": context.connection_id,
            "target_key": context.target_key,
            "image_selection_revision": context.image_selection_revision,
            "image_tool_configuration_revision": context.image_tool_configuration_revision,
            "service_configuration_revision": context.service_configuration_revision,
            "service_tool_configuration_revision": context.service_tool_configuration_revision,
            "prepared_image": {
                "entry_point": context.entry_point,
                "image_size_words": context.image_size_words,
                "image_crc32": context.image_crc32,
                "app_end": context.app_end,
            },
            "status": result.status.name,
            "summary": result.summary,
            "message": result.message,
            "cancel_requested": result.cancel_requested,
            "completion_action": result.completion_action.name,
            "primary_result": primary_data,
            "written": primary_summary.get("written") if primary_data is not None else None,
            "already_exists": primary_summary.get("already_exists") if primary_data is not None else None,
            "reason": primary_summary.get("reason") if primary_data is not None else None,
            "readback_result": payload.readback_result_dict() if payload is not None else None,
            "metadata_summary": self._plain_metadata(payload.metadata_snapshot) if payload is not None else None,
            "error": self._json_value(result.error),
            "warning": self._json_value(result.warning),
        }
        return self._json_value(value)

    def _context_current(self, context) -> bool:
        if not self._submitted_context_current(context):
            return False
        if context.operation_type is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            resource = self.backend.target_resources.get(context.cpu_id)
            return bool(
                resource is not None
                and resource.verify_evidence == context.expected_verify_evidence
            )
        return True

    def _submitted_context_current(self, context) -> bool:
        if not (
            self._non_service_context_current(context)
            and context.service_configuration_revision
            == self.backend.service_configuration_revision
        ):
            return False

        return True

    def _non_service_context_current(self, context) -> bool:
        snapshot = self.controller.snapshot
        resource = self.backend.target_resources.get(context.cpu_id)
        try:
            target_cpu_id = RuntimeCpuId.from_target_key(context.target_key)
        except (TypeError, ValueError):
            return False
        if (
            target_cpu_id is not context.cpu_id
            or resource is None
            or resource.cpu_id is not context.cpu_id
        ):
            return False
        if context.operation_type is not AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            if (
                snapshot.state is RuntimeState.DISCONNECTED
                and snapshot.active_task_id is None
                and snapshot.connection_info is None
                and snapshot.active_target_key is None
                and not snapshot.cleanup_pending
            ):
                return True
            info = snapshot.connection_info
            active = self.backend.active_target_context
            return bool(
                context.service_tool_configuration_revision == self.backend.configuration_revision
                and info is not None
                and active is not None
                and active.cpu_id is context.cpu_id
                and active.target_key == context.target_key
                and active.connection.connection_id == context.connection_id
                and active.connection.cpu_id is context.cpu_id
                and active.resource.cpu_id is context.cpu_id
                and info.connection_id == context.connection_id
                and info.target_key == context.target_key
                and snapshot.active_target_key == context.target_key
            )
        summary = resource.program_image_summary
        try:
            path = str(Path(resource.program_image_path).expanduser().resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            path = ""
        if not (
            context.image_selection_revision
            == self.backend.advanced_flash_selection_revision(context.target_key)
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
        if (
            snapshot.state is RuntimeState.DISCONNECTED
            and snapshot.active_task_id is None
            and snapshot.connection_info is None
            and snapshot.active_target_key is None
            and not snapshot.cleanup_pending
        ):
            return True
        info = snapshot.connection_info
        active = self.backend.active_target_context
        current = bool(
            info is not None
            and active is not None
            and active.cpu_id is context.cpu_id
            and active.target_key == context.target_key
            and active.connection.connection_id == context.connection_id
            and active.connection.cpu_id is context.cpu_id
            and active.resource.cpu_id is context.cpu_id
            and info.connection_id == context.connection_id
            and info.target_key == context.target_key
            and snapshot.active_target_key == context.target_key
        )
        return current

    def _payload_current(self, context, payload) -> bool:
        return bool(
            payload.connection_id == context.connection_id
            and payload.target_key == context.target_key
            and payload.image_selection_revision == context.image_selection_revision
            and payload.image_tool_configuration_revision == context.image_tool_configuration_revision
            and payload.service_configuration_revision == context.service_configuration_revision
            and payload.service_tool_configuration_revision == context.service_tool_configuration_revision
            and payload.operation_type is context.operation_type
            and payload.verify_evidence == context.expected_verify_evidence
            and payload.entry_point == context.entry_point
            and payload.image_size_words == context.image_size_words
            and payload.image_crc32 == context.image_crc32
            and payload.app_end == context.app_end
            and self._submitted_context_current(context)
        )

    def _show(self, value) -> None:
        self.page.result_output.setPlainText(
            json.dumps(value, allow_nan=False, indent=2, sort_keys=True)
        )

    @classmethod
    def _json_value(cls, value):
        if value is None or type(value) in (bool, int, float, str):
            return value
        if isinstance(value, Enum):
            return value.name
        if is_dataclass(value) and not isinstance(value, type):
            return {item.name: cls._json_value(getattr(value, item.name)) for item in fields(value)}
        if isinstance(value, Mapping):
            if any(type(key) is not str for key in value):
                raise TypeError("Shared Result mapping keys must be strings")
            return {key: cls._json_value(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._json_value(item) for item in value]
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
__all__ = ["AdvancedMetadataOperationBinding"]
