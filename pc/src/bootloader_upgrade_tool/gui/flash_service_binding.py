"""Shared Flash Service resource preparation binding."""

from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QObject

from ..app_resources import AppResourceError, AppResourceProvider
from .flash_service_models import PrepareFlashServiceRequest, PreparedFlashServiceSummary
from .runtime_models import RuntimeState, TaskFinalStatus
from .runtime_v2_events import SessionChanged


@dataclass(frozen=True, slots=True)
class _OwnedTask:
    configuration_revision: int
    tool_configuration_revision: int
    image_path: str
    map_path: str


class FlashServiceBinding(QObject):
    def __init__(
        self,
        page,
        advanced_page,
        controller,
        backend,
        app_resource_provider: AppResourceProvider,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or page)
        self.page = page
        self.advanced_page = advanced_page
        self.controller = controller
        self.backend = backend
        self.app_resource_provider = app_resource_provider
        self._configuration_revision = backend.service_configuration_revision
        self._pending: _OwnedTask | None = None
        self._owned: dict[str, _OwnedTask] = {}
        self._descriptor_address = "Not prepared"
        self._status = "Not prepared"
        self._last_resource_error: str | None = None

        page.flash_service_prepare_button.clicked.connect(self.prepare)
        controller.runtimeStateChanged.connect(lambda _snapshot: self._apply_enabled())
        controller.taskStarted.connect(self._task_started)
        controller.taskFinished.connect(self._task_finished)
        runtime_listener = self._runtime_v2_transition
        backend.subscribe_runtime_v2(runtime_listener)
        self.destroyed.connect(
            lambda _object=None, backend=backend, listener=runtime_listener:
                backend.unsubscribe_runtime_v2(listener)
        )
        self._apply_enabled()

    def prepare(self):
        try:
            image_path, map_path = self._resolve_resources()
        except AppResourceError as exc:
            self._resource_failed(exc)
            return None
        context = _OwnedTask(
            self._configuration_revision,
            self.backend.configuration_revision,
            str(image_path),
            str(map_path),
        )
        request = PrepareFlashServiceRequest(
            context.image_path,
            context.map_path,
            "",
            context.configuration_revision,
            context.tool_configuration_revision,
        )
        self._pending = context
        admission = self.controller.request_task(request)
        if admission.accepted:
            self._owned.setdefault(admission.task_id, context)
        self._pending = None
        if not admission.accepted and self._context_current(context):
            self._show({"operation": "prepare_flash_service", "status": "rejected"})
        return admission

    def tool_configuration_changed(self) -> None:
        self._reset_display()
        self._apply_enabled()

    def _task_started(self, state) -> None:
        if self._pending is not None:
            self._owned[state.task_id] = self._pending
            self._descriptor_address = "Not prepared"
            self._status = "Preparing"
            self._apply_resource_state()

    def _task_finished(self, result) -> None:
        context = self._owned.pop(result.task_id, None)
        if context is None or not self._context_current(context):
            return
        if result.status is TaskFinalStatus.SUCCEEDED:
            summary = result.payload
            if type(summary) is not PreparedFlashServiceSummary or not self._summary_current(context, summary):
                return
            self._descriptor_address = f"0x{summary.descriptor_address:08X}"
            self._status = "Ready"
            self._apply_resource_state()
            self._show({
                "operation": "prepare_flash_service",
                "target_key": "cpu1",
                "configuration_revision": context.configuration_revision,
                "service_image_path": summary.service_image_path,
                "service_map_path": summary.service_map_path,
                "descriptor_symbol": "g_boot_flash_service_descriptor",
                "descriptor_address": self._descriptor_address,
                "api_table_address": f"0x{summary.api_table_address:08X}",
                "crc_patch_address": f"0x{summary.crc_patch_address:08X}",
            })
        elif result.status is TaskFinalStatus.FAILED:
            self._status = "Failed"
            self._apply_resource_state()
            self._show({
                "operation": "prepare_flash_service",
                "target_key": "cpu1",
                "status": "FAILED",
                "error": result.error.code if result.error else result.message,
            })
        self._apply_enabled()

    def _runtime_v2_transition(self, transition) -> None:
        if isinstance(transition.source_event, SessionChanged):
            self._configuration_revision += 1
            self.backend.invalidate_prepared_service_image(self._configuration_revision)
            self._reset_display()
            self._apply_enabled()

    def _reset_display(self) -> None:
        self._descriptor_address = "Not prepared"
        self._status = "Not prepared"
        self._apply_resource_state()

    def _resolve_resources(self):
        return (
            self.app_resource_provider.flash_service_image_path(),
            self.app_resource_provider.flash_service_map_path(),
        )

    def _apply_resource_state(self) -> bool:
        try:
            image_path, map_path = self._resolve_resources()
        except AppResourceError as exc:
            self._status = "Unavailable"
            self._descriptor_address = "Not prepared"
            self.page.set_flash_service_resource_state(
                provider=type(self.app_resource_provider).__name__,
                image_path="Unavailable",
                map_path="Unavailable",
                status="Unavailable",
                descriptor_address="Not prepared",
            )
            message = str(exc)
            if message != self._last_resource_error:
                self._show({
                    "operation": "prepare_flash_service",
                    "status": "UNAVAILABLE",
                    "error": {"code": type(exc).__name__, "message": message},
                })
                self._last_resource_error = message
            return False
        if self._status == "Unavailable":
            self._status = "Not prepared"
        self._last_resource_error = None
        self.page.set_flash_service_resource_state(
            provider=type(self.app_resource_provider).__name__,
            image_path=str(image_path),
            map_path=str(map_path),
            status=self._status,
            descriptor_address=self._descriptor_address,
        )
        return True

    def _resource_failed(self, exc: AppResourceError) -> None:
        self._status = "Unavailable"
        self._descriptor_address = "Not prepared"
        self._apply_resource_state()
        self.page.set_flash_service_prepare_enabled(False)

    def _context_current(self, context: _OwnedTask) -> bool:
        try:
            image_path, map_path = self._resolve_resources()
        except AppResourceError:
            return False
        return (
            context.configuration_revision == self._configuration_revision
            and context.tool_configuration_revision == self.backend.configuration_revision
            and context.image_path == str(image_path)
            and context.map_path == str(map_path)
        )

    @staticmethod
    def _summary_current(context: _OwnedTask, summary: PreparedFlashServiceSummary) -> bool:
        return (
            summary.target_key == "cpu1"
            and summary.configuration_revision == context.configuration_revision
            and summary.tool_configuration_revision == context.tool_configuration_revision
            and summary.service_image_path == context.image_path
            and summary.service_map_path == context.map_path
            and summary.descriptor_symbol == ""
        )

    def _apply_enabled(self) -> None:
        snapshot = self.controller.snapshot
        resources_available = self._apply_resource_state()
        enabled = (
            resources_available
            and snapshot.state in {RuntimeState.DISCONNECTED, RuntimeState.CONNECTED}
            and snapshot.active_task_id is None
            and not snapshot.shutdown_requested
        )
        self.page.set_flash_service_prepare_enabled(enabled)

    def _show(self, value: dict[str, object]) -> None:
        self.advanced_page.result_output.setPlainText(json.dumps(value, indent=2, sort_keys=True))


__all__ = ["FlashServiceBinding"]
