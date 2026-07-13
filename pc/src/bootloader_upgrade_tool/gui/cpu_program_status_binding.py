"""CPU1/CPU2 Program status routing and one-shot automatic Metadata reads."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from .runtime_models import RuntimeSnapshot, RuntimeState, TaskFinalStatus
from .status_models import LoadedImageMatch, MetadataRefreshRequest, MetadataStatusSnapshot


class CpuProgramStatusBinding(QObject):
    def __init__(
        self,
        cpu1_page,
        cpu2_page,
        controller,
        target_provider: Callable[[], object | None],
        *,
        automatic_failure_callback: Callable[[str, str], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or cpu1_page)
        self.pages = {"cpu1": cpu1_page, "cpu2": cpu2_page}
        self.controller = controller
        self.target_provider = target_provider
        self.automatic_failure_callback = automatic_failure_callback
        self._snapshot = controller.snapshot
        self._consumed_connections: set[str] = set()
        self._pending: tuple[str, str] | None = None
        self._submitting: tuple[str, str] | None = None
        self._automatic_tasks: dict[str, tuple[str, str]] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._submit_automatic_refresh)
        controller.runtimeStateChanged.connect(self.apply_snapshot)
        controller.taskStarted.connect(self._on_task_started)
        controller.taskFinished.connect(self._on_task_finished)
        self.clear_all()
        self.apply_snapshot(controller.snapshot)

    def set_automatic_failure_callback(self, callback: Callable[[str, str], None]) -> None:
        self.automatic_failure_callback = callback

    def consume_pending_auto_refresh(self) -> None:
        info = self._snapshot.connection_info
        if info is not None:
            self._consumed_connections.add(info.connection_id)
        self._timer.stop()
        self._pending = None

    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        previous = self._snapshot
        changed = _identity(previous) != _identity(snapshot)
        if changed:
            self.consume_pending_auto_refresh()
            self.clear_all()
        self._snapshot = snapshot
        if (
            snapshot.state is RuntimeState.DISCONNECTING
            or snapshot.state is RuntimeState.DISCONNECTED
            or snapshot.shutdown_requested
        ):
            self.consume_pending_auto_refresh()
            self.clear_all()
            return
        if not self._automatic_allowed(snapshot):
            if self._pending is not None:
                self.consume_pending_auto_refresh()
            elif (
                snapshot.state is RuntimeState.CONNECTED
                and snapshot.connection_info is not None
                and snapshot.connection_info.target_key in self.pages
                and getattr(getattr(self.target_provider(), "command_set", None), "get_metadata_summary", None) is None
            ):
                self._consumed_connections.add(snapshot.connection_info.connection_id)
            return
        info = snapshot.connection_info
        assert info is not None
        if info.connection_id not in self._consumed_connections and self._pending is None:
            self._pending = (info.connection_id, info.target_key)
            self._timer.start(0)

    def clear_all(self) -> None:
        for target in self.pages:
            self.clear_target(target)

    def clear_target(self, target_key: str) -> None:
        page = self.pages[target_key]
        for key in page.status_rows:
            page.set_status(key, "Unknown", "unknown")

    def _automatic_allowed(self, snapshot: RuntimeSnapshot) -> bool:
        info = snapshot.connection_info
        profile = self.target_provider()
        return bool(
            snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_task_id is None
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
            and not snapshot.shutdown_requested
            and info is not None
            and info.target_key in self.pages
            and snapshot.active_target_key == info.target_key
            and profile is not None
            and getattr(profile.command_set, "get_metadata_summary", None) is not None
        )

    def _submit_automatic_refresh(self) -> None:
        pending = self._pending
        if pending is None:
            return
        connection_id, target_key = pending
        self._pending = None
        self._consumed_connections.add(connection_id)
        snapshot = self.controller.snapshot
        self._snapshot = snapshot
        if not self._automatic_allowed(snapshot) or _identity(snapshot) != pending:
            return
        self._submitting = pending
        admission = self.controller.request_task(MetadataRefreshRequest(connection_id, automatic=True))
        if admission.accepted and admission.task_id not in self._automatic_tasks:
            self._automatic_tasks[admission.task_id] = pending
        self._submitting = None

    def _on_task_started(self, state) -> None:
        if self._submitting is not None:
            self._automatic_tasks[state.task_id] = self._submitting
        else:
            self.consume_pending_auto_refresh()

    def _on_task_finished(self, result) -> None:
        owned = self._automatic_tasks.pop(result.task_id, None)
        payload = result.payload
        if result.status is TaskFinalStatus.SUCCEEDED and isinstance(payload, MetadataStatusSnapshot):
            self._render_if_current(payload)
            return
        if owned is None or not self._is_current(*owned):
            return
        self.clear_target(owned[1])
        if self.automatic_failure_callback is not None:
            self.automatic_failure_callback(*owned)

    def _render_if_current(self, snapshot: MetadataStatusSnapshot) -> None:
        if not self._is_current(snapshot.connection_id, snapshot.target_key):
            return
        _render_program_metadata(self.pages[snapshot.target_key], snapshot)

    def _is_current(self, connection_id: str, target_key: str) -> bool:
        snapshot = self.controller.snapshot
        info = snapshot.connection_info
        return bool(
            info is not None
            and snapshot.state not in {RuntimeState.DISCONNECTED, RuntimeState.DISCONNECTING}
            and not snapshot.shutdown_requested
            and info.connection_id == connection_id
            and info.target_key == target_key
            and snapshot.active_target_key == target_key
        )


def _identity(snapshot: RuntimeSnapshot) -> tuple[str, str] | None:
    info = snapshot.connection_info
    return (info.connection_id, info.target_key) if info is not None else None


def _render_program_metadata(page, snapshot: MetadataStatusSnapshot) -> None:
    raw = snapshot.raw_metadata
    loaded_text, loaded_state = {
        LoadedImageMatch.MATCH: ("Match", "success"),
        LoadedImageMatch.MISMATCH: ("Mismatch", "warning"),
        LoadedImageMatch.NO_PREPARED_IMAGE: ("No prepared image", "unknown"),
        LoadedImageMatch.NO_VALID_TARGET_IMAGE: ("Unknown", "unknown"),
    }[snapshot.loaded_image_match]
    values = {
        "metadata_valid": ("Valid" if snapshot.metadata_valid else "Invalid", "success" if snapshot.metadata_valid else "warning"),
        "entry_point_valid": ("Valid" if snapshot.entry_point_valid else "Invalid", "success" if snapshot.entry_point_valid else "warning"),
        "image_valid": ("Valid" if snapshot.image_valid else "Unavailable", "success" if snapshot.image_valid else "warning"),
        "flash_app_crc32": (f"0x{raw.image_crc32:08X}" if snapshot.image_valid else "Unavailable", "success" if snapshot.image_valid else "warning"),
        "boot_attempt": (f"Yes ({raw.boot_attempt_count})" if snapshot.boot_attempt_present else "No", "success" if snapshot.boot_attempt_present else "neutral"),
        "loaded_image_matches": (loaded_text, loaded_state),
        "app_confirmed": ("Yes" if snapshot.app_confirmed else "No", "success" if snapshot.app_confirmed else "neutral"),
        "confirmed_bootable": ("Yes" if snapshot.confirmed_bootable else "No", "success" if snapshot.confirmed_bootable else "warning"),
    }
    for key, (text, state) in values.items():
        page.set_status(key, text, state)


__all__ = ["CpuProgramStatusBinding"]
