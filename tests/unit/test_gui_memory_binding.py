import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone

from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.memory_binding import MemoryRuntimeBinding
from bootloader_upgrade_tool.gui.pages import MemoryTargetPage
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo
from bootloader_upgrade_tool.gui.runtime_v2_events import (
    ActiveTargetChanged,
    ConnectionClosed,
    ConnectionOpened,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    RuntimeCpuId,
    RuntimeReadError,
)


READ_AT = datetime(2026, 7, 19, 4, 0, tzinfo=timezone.utc)


def qt_app():
    return QApplication.instance() or QApplication([])


def _pages_and_backend(cpu_id=RuntimeCpuId.CPU1):
    cpu1, cpu2 = MemoryTargetPage("cpu1"), MemoryTargetPage("cpu2")
    backend = RuntimeBackend()
    backend._runtime_v2_dispatcher.dispatch(
        ConnectionOpened(
            ConnectionInfo("connection", "SCI", "COM3", READ_AT, cpu_id.value)
        )
    )
    binding = MemoryRuntimeBinding(cpu1, cpu2, backend)
    return cpu1, cpu2, backend, binding


def test_binding_renders_initial_empty_and_each_cpu_independently() -> None:
    qt_app()
    cpu1, cpu2, backend, binding = _pages_and_backend()
    assert cpu1.memory_table.rowCount() == cpu2.memory_table.rowCount() == 0
    assert cpu1.freshness_value.text() == cpu2.freshness_value.text() == "Empty"

    generation = backend.connection_generation
    backend.record_memory_read_success(
        RuntimeCpuId.CPU1, generation, 0x1000, tuple(range(18)), READ_AT
    )
    assert cpu1.freshness_value.text() == "Fresh"
    assert cpu1.memory_table.rowCount() == 2
    assert cpu1.memory_table.item(0, 0).text() == "0x001000"
    assert cpu1.memory_table.item(1, 0).text() == "0x001010"
    assert cpu1.memory_table.item(1, 3).text() == "????"
    assert cpu1.clear_button.isEnabled()
    assert cpu2.freshness_value.text() == "Empty"

    assert not any(
        "snapshot" in name or "memory_state" in name
        for name in vars(binding)
    )
    cpu1.close()
    cpu2.close()


def test_disconnect_target_mismatch_failure_reread_and_clear_preserve_contract() -> None:
    app = qt_app()
    cpu1, cpu2, backend, _binding = _pages_and_backend()
    generation = backend.connection_generation
    backend.record_memory_read_success(
        RuntimeCpuId.CPU1, generation, 0x1000, (1, 2), READ_AT
    )

    backend._runtime_v2_dispatcher.dispatch(ActiveTargetChanged(None))
    assert cpu1.freshness_value.text() == "Stale"
    assert cpu1.memory_table.rowCount() == 1

    error = RuntimeReadError("READ_FAILED", "target read failed", "MEMORY_READ")
    backend.record_memory_read_failure(RuntimeCpuId.CPU1, generation, error)
    assert cpu1.freshness_value.text() == "Stale"
    assert "READ_FAILED" in cpu1.freshness_value.toolTip()
    assert cpu1.memory_table.item(0, 1).text() == "0001"

    backend.record_memory_read_success(
        RuntimeCpuId.CPU1, generation, 0x2000, (0xCAFE,), READ_AT
    )
    assert cpu1.freshness_value.text() == "Fresh"
    assert "READ_FAILED" not in cpu1.freshness_value.toolTip()
    assert cpu1.memory_table.item(0, 0).text() == "0x002000"

    backend._runtime_v2_dispatcher.dispatch(
        ConnectionClosed("connection", generation)
    )
    assert cpu1.freshness_value.text() == "Stale"
    assert "disconnected" in cpu1.freshness_value.toolTip()
    cpu1.clear_button.click()
    app.processEvents()
    assert cpu1.freshness_value.text() == "Empty"
    assert cpu1.memory_table.rowCount() == 0
    assert cpu2.freshness_value.text() == "Empty"

    cpu1.close()
    cpu2.close()


def test_first_failure_is_empty_with_error_and_refresh_has_no_runtime_path() -> None:
    app = qt_app()
    cpu1, cpu2, backend, _binding = _pages_and_backend()
    error = RuntimeReadError("READ_FAILED", "first failure", "MEMORY_READ")
    transitions = []
    backend.subscribe_runtime_v2(transitions.append)
    backend.record_memory_read_failure(
        RuntimeCpuId.CPU1, backend.connection_generation, error
    )
    assert cpu1.freshness_value.text() == "Empty"
    assert cpu1.memory_table.rowCount() == 0
    assert "first failure" in cpu1.freshness_value.toolTip()
    before = len(transitions)
    cpu1.refresh_button.click()
    app.processEvents()
    assert len(transitions) == before

    cpu1.close()
    cpu2.close()


def test_cpu2_injected_state_renders_only_cpu2() -> None:
    qt_app()
    cpu1, cpu2, backend, _binding = _pages_and_backend(RuntimeCpuId.CPU2)
    backend.record_memory_read_success(
        RuntimeCpuId.CPU2,
        backend.connection_generation,
        0x3000,
        (0x1234,),
        READ_AT,
    )
    assert cpu1.freshness_value.text() == "Empty"
    assert cpu2.freshness_value.text() == "Fresh"
    assert cpu2.memory_table.item(0, 1).text() == "1234"
    cpu1.close()
    cpu2.close()
