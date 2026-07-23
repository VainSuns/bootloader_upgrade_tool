"""Read-only Advanced adapter for Backend-owned Program Image state."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QLineEdit, QPushButton

from .runtime_v2_models import ImageParseStatus, RuntimeCpuId


@dataclass(frozen=True, slots=True)
class _TargetView:
    program_image_edit: QLineEdit
    program_image_browse_button: QPushButton
    summary_setter_name: str


class AdvancedFlashBinding(QObject):
    _runtime_transition_received = Signal(object)

    def __init__(self, page, controller, backend, parent: QObject | None = None) -> None:
        super().__init__(parent or page)
        self.page = page
        self.controller = controller
        self.backend = backend
        self._target_views = MappingProxyType({
            cpu_id: _TargetView(
                getattr(page, f"{cpu_id.value}_flash_image_edit"),
                getattr(page, f"{cpu_id.value}_flash_browse_button"),
                f"set_{cpu_id.value}_flash_image_summary",
            )
            for cpu_id in RuntimeCpuId
        })
        for view in self._target_views.values():
            view.program_image_edit.setReadOnly(True)
            view.program_image_browse_button.setEnabled(True)
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
            view = self._target_views[cpu_id]
            view.program_image_edit.setText(state.program_image_path)
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
            getattr(self.page, view.summary_setter_name)(**values)

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
