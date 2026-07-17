"""Read-only Advanced adapter for Backend-owned Program Image state."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from .runtime_v2_models import ImageParseStatus, RuntimeCpuId


class AdvancedFlashBinding(QObject):
    _runtime_transition_received = Signal(object)

    def __init__(self, page, controller, backend, parent: QObject | None = None) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        page.cpu1_flash_image_edit.setReadOnly(True)
        page.cpu2_flash_image_edit.setReadOnly(True)
        page.cpu1_flash_browse_button.setEnabled(False)
        page.cpu2_flash_browse_button.setEnabled(False)
        self._runtime_transition_received.connect(self._apply_runtime_transition)
        self._runtime_v2_listener = self._receive_runtime_transition_from_backend
        self.backend.subscribe_runtime_v2(self._runtime_v2_listener)
        self.destroyed.connect(
            lambda _object, backend=backend, listener=self._runtime_v2_listener: backend.unsubscribe_runtime_v2(
                listener
            )
        )
        self._render()

    def configuration_changed(self) -> None:
        self._render()

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self._runtime_transition_received.emit(result)

    @Slot(object)
    def _apply_runtime_transition(self, _result) -> None:
        self._render()

    def _render(self, resources=None) -> None:
        resources = resources or self.backend.target_resources
        for cpu_id in RuntimeCpuId:
            state = resources[cpu_id]
            edit = (
                self.page.cpu1_flash_image_edit
                if cpu_id is RuntimeCpuId.CPU1
                else self.page.cpu2_flash_image_edit
            )
            edit.setText(state.program_image_path)
            summary = (
                state.program_image_summary
                if state.program_image_parse_status is ImageParseStatus.READY
                else None
            )
            values = {
                "entry_point": f"0x{summary.identity.entry_point:08X}" if summary else "—",
                "image_size": f"{summary.identity.image_size_words} words" if summary else "—",
                "crc32": f"0x{summary.identity.image_crc32:08X}" if summary else "—",
            }
            method = (
                self.page.set_cpu1_flash_image_summary
                if cpu_id is RuntimeCpuId.CPU1
                else self.page.set_cpu2_flash_image_summary
            )
            method(**values)

    def _unsubscribe(self, *_args) -> None:
        self.backend.unsubscribe_runtime_v2(self._runtime_v2_listener)


__all__ = ["AdvancedFlashBinding"]
