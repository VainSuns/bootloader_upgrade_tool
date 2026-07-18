"""Current-target binding for independent Advanced Metadata operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import json
from pathlib import Path

from PySide6.QtCore import QObject

from .advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
    AdvancedMetadataOperationType,
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from .flash_service_models import FlashServiceResourceStatus
from .runtime_models import RuntimeState, TaskFinalStatus
from .runtime_v2_models import ImageParseStatus, RuntimeCpuId
from .status_models import MetadataStatusSnapshot


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    operation_type: AdvancedMetadataOperationType
    connection_id: str
    target_key: str
    image_source_path: str
    image_selection_revision: int
    image_tool_configuration_revision: int
    expected_image_identity: object
    expected_effective_sector_mask: int
    service_configuration_revision: int
    service_tool_configuration_revision: int
    verification_token: str | None
    entry_point: int
    image_size_words: int
    image_crc32: int
    app_end: int


class AdvancedMetadataOperationBinding(QObject):
    def __init__(
        self,
        page,
        controller,
        backend,
        *,
        apply_metadata_snapshot,
        clear_metadata,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self.apply_metadata_snapshot = apply_metadata_snapshot
        self.clear_metadata = clear_metadata
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
            "image_source_path": context.image_source_path,
            "image_selection_revision": context.image_selection_revision,
            "image_tool_configuration_revision": context.image_tool_configuration_revision,
            "expected_image_identity": context.expected_image_identity,
            "expected_effective_sector_mask": context.expected_effective_sector_mask,
            "service_configuration_revision": context.service_configuration_revision,
            "service_tool_configuration_revision": context.service_tool_configuration_revision,
        }
        if operation_type is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            request = WriteAdvancedImageValidRequest(**values, verification_token=context.verification_token)
        elif operation_type is AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT:
            request = WriteAdvancedBootAttemptRequest(**values)
        else:
            request = WriteAdvancedAppConfirmedRequest(**values)
        self._pending = context
        admission = self.controller.request_task(request)
        if admission.accepted:
            self._owned.setdefault(admission.task_id, context)
            self.clear_metadata()
        self._pending = None
        if not admission.accepted and self._context_current(context):
            self._show({
                "operation": operation_type.name,
                "status": "rejected",
                "message": admission.rejection.message if admission.rejection else "Request rejected",
            })
        return admission

    def _current_context(self, operation_type) -> _OwnedTask | None:
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
        profile = self.backend.active_target
        if (
            resource.program_image_parse_status is not ImageParseStatus.READY
            or resource.program_image_summary is None
            or not resource.program_image_path.strip()
            or service_state.status is not FlashServiceResourceStatus.READY
            or service_state.summary is None
            or profile is None
            or getattr(profile, "cpu_id", None) != 1
        ):
            return None
        image_summary = resource.program_image_summary
        image_path = str(Path(resource.program_image_path).expanduser().resolve(strict=False))
        service_summary = service_state.summary
        revision = self.backend.configuration_revision
        if not (
            service_summary.target_key == "cpu1"
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

        token = None
        if operation_type is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            credential = self.backend.clean_verify_credential
            if not (
                credential is not None
                and credential.connection_id == info.connection_id
                and credential.target_key == "cpu1"
                and credential.image_selection_revision
                == self.backend.advanced_flash_selection_revision("cpu1")
                and credential.image_tool_configuration_revision == revision
                and credential.entry_point == image_summary.identity.entry_point
                and credential.image_size_words == image_summary.identity.image_size_words
                and credential.image_crc32 == image_summary.identity.image_crc32
                and credential.app_end == image_summary.identity.app_end
            ):
                return None
            token = credential.token
        elif not self._metadata_matches(info.connection_id, image_summary):
            return None
        elif (
            operation_type is AdvancedMetadataOperationType.WRITE_APP_CONFIRMED
            and not self.backend.metadata_status_snapshot.boot_attempt_present
        ):
            return None

        identity = image_summary.identity
        return _OwnedTask(
            operation_type,
            info.connection_id,
            "cpu1",
            image_path,
            self.backend.advanced_flash_selection_revision("cpu1"),
            revision,
            identity,
            image_summary.sector_mask,
            service_state.revision,
            revision,
            token,
            identity.entry_point,
            identity.image_size_words,
            identity.image_crc32,
            identity.app_end,
        )

    def _metadata_matches(self, connection_id, image_summary) -> bool:
        snapshot = self.backend.metadata_status_snapshot
        if type(snapshot) is not MetadataStatusSnapshot:
            return False
        raw = snapshot.raw_metadata
        return bool(
            snapshot.connection_id == connection_id
            and snapshot.target_key == "cpu1"
            and snapshot.metadata_valid
            and snapshot.image_valid
            and raw.entry_point == image_summary.identity.entry_point
            and raw.image_size_words == image_summary.identity.image_size_words
            and raw.image_crc32 == image_summary.identity.image_crc32
        )

    def _task_started(self, state) -> None:
        if self._pending is not None:
            self._owned[state.task_id] = self._pending

    def _task_finished(self, result) -> None:
        context = self._owned.pop(result.task_id, None)
        service_failure = bool(
            context is not None and self._current_service_failure(context, result)
        )
        if context is None or (
            not service_failure and not self._submitted_context_current(context)
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
        if (
            payload is not None
            and result.status is not TaskFinalStatus.FAILED
            and payload.metadata_snapshot is not None
            and self.controller.snapshot.state is not RuntimeState.DISCONNECTED
        ):
            self.apply_metadata_snapshot(payload.metadata_snapshot)
        self.refresh()

    def _current_service_failure(self, context, result) -> bool:
        state = self.backend.flash_service_resource_state
        return bool(
            result.status is TaskFinalStatus.FAILED
            and result.payload is None
            and result.error is not None
            and self._non_service_context_current(context)
            and (
                context.operation_type
                is not AdvancedMetadataOperationType.WRITE_IMAGE_VALID
                or (
                    self.backend.clean_verify_credential is not None
                    and self.backend.clean_verify_credential.token
                    == context.verification_token
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
            credential = self.backend.clean_verify_credential
            return bool(credential is not None and credential.token == context.verification_token)
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
        current = bool(
            info is not None
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
            and payload.verification_token == context.verification_token
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
