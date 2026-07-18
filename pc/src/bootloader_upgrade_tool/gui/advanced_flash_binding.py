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
        page.cpu1_flash_browse_button.setEnabled(True)
        page.cpu2_flash_browse_button.setEnabled(True)
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
        snapshot = self.backend.runtime_v2_snapshot
        resources = resources or snapshot.target_resources
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
                "app_end": f"0x{summary.identity.app_end:08X}" if summary else "—",
                "entry_point": f"0x{summary.identity.entry_point:08X}" if summary else "—",
                "image_size": f"{summary.identity.image_size_words} words" if summary else "—",
                "crc32": f"0x{summary.identity.image_crc32:08X}" if summary else "—",
                "parse_status": {
                    ImageParseStatus.EMPTY: "Not parsed",
                    ImageParseStatus.PARSING: "Parsing",
                    ImageParseStatus.READY: "Ready",
                    ImageParseStatus.ERROR: "Error",
                }[state.program_image_parse_status],
                "verify": self._verify_text(cpu_id, state, summary, snapshot),
            }
            method = (
                self.page.set_cpu1_flash_image_summary
                if cpu_id is RuntimeCpuId.CPU1
                else self.page.set_cpu2_flash_image_summary
            )
            method(**values)

    @staticmethod
    def _verify_text(cpu_id, state, summary, snapshot) -> str:
        if summary is None:
            return "—"
        evidence = state.verify_evidence
        connection = snapshot.connection
        return "Verified" if (
            evidence is not None
            and evidence.cpu_id is cpu_id
            and evidence.image_identity == summary.identity
            and evidence.connection_generation == snapshot.connection_generation
            and connection is not None
            and connection.generation == evidence.connection_generation
            and connection.cpu_id is cpu_id
        ) else "Not verified"

    def _unsubscribe(self, *_args) -> None:
        self.backend.unsubscribe_runtime_v2(self._runtime_v2_listener)


__all__ = ["AdvancedFlashBinding"]
