"""Render Backend-owned per-CPU Memory snapshots into pure Qt Views."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from .runtime_v2_models import DataFreshness, RuntimeCpuId


class MemoryRuntimeBinding(QObject):
    _runtime_transition_received = Signal(object)

    def __init__(self, cpu1_page, cpu2_page, backend, parent: QObject | None = None) -> None:
        super().__init__(parent or cpu1_page)
        self.backend = backend
        self.pages = {
            RuntimeCpuId.CPU1: cpu1_page,
            RuntimeCpuId.CPU2: cpu2_page,
        }
        cpu1_page.clearRequested.connect(self._clear)
        cpu2_page.clearRequested.connect(self._clear)
        self._runtime_transition_received.connect(self._apply_runtime_transition)
        self._runtime_v2_listener = self._receive_runtime_transition_from_backend
        backend.subscribe_runtime_v2(self._runtime_v2_listener)
        self.destroyed.connect(
            lambda _object, backend=backend, listener=self._runtime_v2_listener: backend.unsubscribe_runtime_v2(
                listener
            )
        )
        self._render(backend.runtime_v2_snapshot)

    def _receive_runtime_transition_from_backend(self, result) -> None:
        self._runtime_transition_received.emit(result)

    @Slot(object)
    def _apply_runtime_transition(self, result) -> None:
        self._render(result.snapshot)

    @Slot(str)
    def _clear(self, target: str) -> None:
        self.backend.clear_memory(RuntimeCpuId.from_target_key(target))

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


def _freshness_tooltip(cpu_id, state, snapshot) -> str:
    error = state.read_error
    error_text = "" if error is None else f"{error.code}: {error.message} ({error.stage})"
    if state.freshness is DataFreshness.EMPTY:
        return error_text or "No retained Memory data."

    details = (
        f"Address 0x{state.base_address:06X}; {state.word_count} words; "
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
