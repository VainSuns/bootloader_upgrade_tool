"""Bind generic target Memory pages to Runtime V2."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QObject, Signal, Slot

from .memory_models import MemoryRefreshRequest
from .runtime_models import RuntimeSnapshot, RuntimeState
from .runtime_v2_models import DataFreshness, RuntimeCpuId


class MemoryRuntimeBinding(QObject):
    _runtime_transition_received = Signal(object)

    def __init__(
        self,
        pages: Mapping[RuntimeCpuId, object],
        controller,
        backend,
        parent: QObject | None = None,
    ) -> None:
        normalized = dict(pages)
        if set(normalized) != set(RuntimeCpuId) or any(
            type(key) is not RuntimeCpuId for key in normalized
        ):
            raise ValueError("pages must contain exactly one page for every RuntimeCpuId")
        if any(page.target != cpu_id.value for cpu_id, page in normalized.items()):
            raise ValueError("page target must match its RuntimeCpuId key")
        super().__init__(parent or next(iter(normalized.values())))
        self.pages = normalized
        self.controller = controller
        self.backend = backend

        for page in self.pages.values():
            page.refreshRequested.connect(self._refresh)
            page.clearRequested.connect(self._clear)
        controller.runtimeStateChanged.connect(self.apply_snapshot)
        self._runtime_transition_received.connect(self._apply_runtime_transition)
        self._runtime_v2_listener = self._receive_runtime_transition_from_backend
        backend.subscribe_runtime_v2(self._runtime_v2_listener)
        self.destroyed.connect(
            lambda _object, backend=backend, listener=self._runtime_v2_listener: backend.unsubscribe_runtime_v2(
                listener
            )
        )
        self._render(backend.runtime_v2_snapshot)
        self.apply_snapshot(controller.snapshot)

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self._runtime_transition_received.emit(result)

    @Slot(object)
    def _apply_runtime_transition(self, result) -> None:
        self._render(result.snapshot)
        self._apply_enabled(self.controller.snapshot)

    @Slot(object)
    def apply_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        self._apply_enabled(snapshot)

    @Slot(str)
    def _refresh(self, target: str) -> None:
        try:
            cpu_id = RuntimeCpuId.from_target_key(target)
        except (TypeError, ValueError):
            return
        context = self._ready_context(cpu_id, self.controller.snapshot)
        if context is None:
            return
        page = self.pages.get(cpu_id)
        if page is None:
            return
        try:
            start_address = int(page.start_address_edit.text().strip(), 0)
            request = MemoryRefreshRequest(
                context.connection.connection_id,
                context.target_key,
                context.connection.generation,
                start_address,
                page.word_count_spin.value(),
            )
        except (TypeError, ValueError) as exc:
            page.show_input_error(str(exc) or "Invalid Memory read parameters")
            return
        self.controller.request_task(request)

    @Slot(str)
    def _clear(self, target: str) -> None:
        try:
            cpu_id = RuntimeCpuId.from_target_key(target)
        except (TypeError, ValueError):
            return
        if cpu_id in self.pages:
            self.backend.clear_memory(cpu_id)

    def _apply_enabled(self, snapshot: RuntimeSnapshot) -> None:
        for cpu_id, page in self.pages.items():
            context = self._ready_context(cpu_id, snapshot)
            page.set_interactions_enabled(context is not None)
            if context is not None:
                page.set_reference_ranges(_reference_ranges(context.profile.memory_map))

    def _ready_context(self, requested_cpu: RuntimeCpuId, snapshot: RuntimeSnapshot):
        context = self.backend.active_target_context
        info = snapshot.connection_info
        available, _reason = self.backend.memory_read_availability(requested_cpu.value)
        if not (
            snapshot.state is RuntimeState.CONNECTED
            and snapshot.active_task_id is None
            and not snapshot.connection_suspect
            and not snapshot.disconnect_decision_pending
            and not snapshot.shutdown_requested
            and not snapshot.cleanup_pending
            and info is not None
            and context is not None
            and available
            and requested_cpu is context.cpu_id
            and requested_cpu.value == context.target_key
            and info.connection_id == context.connection.connection_id
            and info.target_key == context.target_key
            and snapshot.active_target_key == context.target_key
        ):
            return None
        return context

    def _render(self, snapshot) -> None:
        for cpu_id, page in self.pages.items():
            state = snapshot.memory_states[cpu_id]
            page.set_memory_rows(_memory_rows(state.base_address, state.words))
            text, semantic_state = {
                DataFreshness.EMPTY: ("Empty", "unknown"),
                DataFreshness.FRESH: ("Fresh", "success"),
                DataFreshness.STALE: ("Stale", "warning"),
            }[state.freshness]
            page.set_memory_freshness(
                text,
                state=semantic_state,
                tooltip=_freshness_tooltip(cpu_id, state, snapshot),
            )
            page.set_clear_enabled(bool(state.words))


def _memory_rows(base_address, words):
    if base_address is None:
        return ()
    return tuple(
        (base_address + offset, words[offset : offset + 16])
        for offset in range(0, len(words), 16)
    )


def _reference_ranges(memory_map):
    ranges = []
    flash = memory_map.flash
    if flash is not None:
        ranges.extend(
            (f"Flash Sector {sector.sector_id}", sector.start, sector.end_exclusive)
            for sector in flash.sectors
        )
        ranges.extend(
            (f"App Flash {index}", item.start, item.end_exclusive)
            for index, item in enumerate(flash.app_ranges, 1)
        )
    if memory_map.metadata is not None:
        item = memory_map.metadata.range
        ranges.append(("Metadata", item.start, item.end_exclusive))
    ram = memory_map.ram
    if ram is not None:
        for label, items in (
            ("Service RAM", ram.service_ranges),
            ("RAM App", ram.ram_app_ranges),
            ("Reserved RAM", ram.reserved_ranges),
        ):
            ranges.extend(
                (f"{label} {index}", item.start, item.end_exclusive)
                for index, item in enumerate(items, 1)
            )
    return tuple(ranges)


def _freshness_tooltip(cpu_id, state, snapshot) -> str:
    error = state.read_error
    error_text = "" if error is None else f"{error.code}: {error.message} ({error.stage})"
    if state.freshness is DataFreshness.EMPTY:
        return error_text or "No retained Memory data."

    details = (
        f"Address 0x{state.base_address:08X}; {state.word_count} words; "
        f"read {state.read_at.isoformat()}; generation {state.connection_generation.value}."
    )
    if state.freshness is DataFreshness.FRESH:
        return details

    connection = snapshot.connection
    reasons = []
    if connection is None:
        reasons.append("disconnected")
    elif connection.cpu_id is not cpu_id:
        reasons.append("inactive Target")
    if connection is not None and connection.generation != state.connection_generation:
        reasons.append("old connection generation")
    if error_text:
        reasons.append(f"latest read failed: {error_text}")
    return f"{details} Stale: {', '.join(reasons) if reasons else 'state no longer current'}."


__all__ = ["MemoryRuntimeBinding"]
