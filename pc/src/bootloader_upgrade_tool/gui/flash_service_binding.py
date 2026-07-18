"""Presentation binding for the Backend-owned Flash Service resource state."""

from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QObject

from .flash_service_models import (
    FlashServiceResourceStatus,
    PrepareFlashServiceRequest,
    PreparedFlashServiceSummary,
)
from .runtime_models import RuntimeState, TaskFinalStatus


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    resource_revision: int
    tool_configuration_revision: int


class FlashServiceBinding(QObject):
    def __init__(
        self,
        page,
        advanced_page,
        controller,
        backend,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or page)
        self.page = page
        self.advanced_page = advanced_page
        self.controller = controller
        self.backend = backend
        self._pending: _OwnedTask | None = None
        self._owned: dict[str, _OwnedTask] = {}

        page.flash_service_prepare_button.clicked.connect(self.prepare)
        controller.runtimeStateChanged.connect(lambda _snapshot: self._apply_enabled())
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        self._apply_enabled()

    def prepare(self):
        state = self.backend.refresh_flash_service_resources()
        if state.status is FlashServiceResourceStatus.UNAVAILABLE:
            self._render()
            self._apply_enabled()
            return None
        context = _OwnedTask(state.revision, self.backend.configuration_revision)
        request = PrepareFlashServiceRequest(
            context.resource_revision,
            context.tool_configuration_revision,
        )
        self._pending = context
        owned_before = set(self._owned)
        try:
            try:
                admission = self.controller.request_task(request)
            except Exception as exc:
                for task_id in self._owned.keys() - owned_before:
                    self._owned.pop(task_id)
                self._show({
                    "operation": "prepare_flash_service",
                    "status": "FAILED",
                    "error": {
                        "code": "REQUEST_TASK_FAILED",
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    },
                })
                self._apply_enabled()
                return None
        finally:
            self._pending = None
        if admission.accepted:
            self._owned.setdefault(admission.task_id, context)
        elif admission.rejection is not None:
            self._show({
                "operation": "prepare_flash_service",
                "status": "REJECTED",
                "rejection": {
                    "code": admission.rejection.code.name,
                    "message": admission.rejection.message,
                },
            })
        elif admission.error is not None:
            self._show({
                "operation": "prepare_flash_service",
                "status": "FAILED",
                "error": {
                    "code": admission.error.code,
                    "stage": admission.error.stage,
                    "message": admission.error.message,
                },
            })
        self._apply_enabled()
        return admission

    def tool_configuration_changed(self) -> None:
        self._apply_enabled()

    def _task_started(self, state) -> None:
        if self._pending is not None:
            self._owned[state.task_id] = self._pending
            self._render(preparing=True)

    def _task_finished(self, result) -> None:
        context = self._owned.pop(result.task_id, None)
        self._render()
        if context is not None:
            if result.status is TaskFinalStatus.SUCCEEDED:
                summary = result.payload
                state = self.backend.flash_service_resource_state
                if (
                    type(summary) is PreparedFlashServiceSummary
                    and state.status is FlashServiceResourceStatus.READY
                    and state.summary == summary
                    and summary.resource_revision == state.revision
                    and summary.tool_configuration_revision
                    == context.tool_configuration_revision
                    and self.backend.configuration_revision
                    == context.tool_configuration_revision
                ):
                    self._show({
                        "operation": "prepare_flash_service",
                        "target_key": "cpu1",
                        "resource_revision": summary.resource_revision,
                        "service_image_path": summary.service_image_path,
                        "service_map_path": summary.service_map_path,
                        "descriptor_symbol": summary.descriptor_symbol,
                        "descriptor_address": f"0x{summary.descriptor_address:08X}",
                        "api_table_address": f"0x{summary.api_table_address:08X}",
                        "crc_patch_address": f"0x{summary.crc_patch_address:08X}",
                    })
            elif result.status is TaskFinalStatus.FAILED:
                state = self.backend.flash_service_resource_state
                if (
                    result.error is not None
                    and self.backend.configuration_revision
                    == context.tool_configuration_revision
                    and state.revision == context.resource_revision + 1
                    and state.status in {
                        FlashServiceResourceStatus.ERROR,
                        FlashServiceResourceStatus.STALE,
                        FlashServiceResourceStatus.UNAVAILABLE,
                    }
                    and state.error_code == result.error.code
                ):
                    self._show({
                        "operation": "prepare_flash_service",
                        "target_key": "cpu1",
                        "status": "FAILED",
                        "error": {
                            "code": result.error.code,
                            "stage": result.error.stage,
                            "message": result.error.message,
                        },
                    })
        self._apply_enabled()

    def _render(self, *, preparing: bool = False) -> bool:
        state = self.backend.flash_service_resource_state
        labels = {
            FlashServiceResourceStatus.UNAVAILABLE: "Unavailable",
            FlashServiceResourceStatus.UNVALIDATED: "Not prepared",
            FlashServiceResourceStatus.READY: "Ready",
            FlashServiceResourceStatus.ERROR: "Failed",
            FlashServiceResourceStatus.STALE: "Reload required",
        }
        summary = state.summary
        self.page.set_flash_service_resource_state(
            provider=state.provider_name,
            image_path=state.image_path or "Unavailable",
            map_path=state.map_path or "Unavailable",
            status="Preparing" if preparing else labels[state.status],
            descriptor_address=(
                f"0x{summary.descriptor_address:08X}"
                if not preparing and summary is not None
                else "Not prepared"
            ),
        )
        return state.status is not FlashServiceResourceStatus.UNAVAILABLE

    def _apply_enabled(self) -> None:
        snapshot = self.controller.snapshot
        if (
            snapshot.active_task_id is None
            and self.backend.flash_service_resource_state.status
            in {
                FlashServiceResourceStatus.UNAVAILABLE,
                FlashServiceResourceStatus.UNVALIDATED,
                FlashServiceResourceStatus.READY,
            }
        ):
            try:
                self.backend.refresh_flash_service_resources()
            except RuntimeError:
                pass
        resources_available = self._render()
        self.page.set_flash_service_prepare_enabled(
            resources_available
            and snapshot.state in {RuntimeState.DISCONNECTED, RuntimeState.CONNECTED}
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
        )

    def _show(self, value: dict[str, object]) -> None:
        self.advanced_page.result_output.setPlainText(json.dumps(value, indent=2, sort_keys=True))


__all__ = ["FlashServiceBinding"]
