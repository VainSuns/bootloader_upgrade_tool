import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.memory_binding import MemoryRuntimeBinding
from bootloader_upgrade_tool.gui.memory_models import MemoryRefreshRequest
from bootloader_upgrade_tool.gui.pages import MemoryTargetPage
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo, RuntimeSnapshot, RuntimeState
from bootloader_upgrade_tool.gui.runtime_v2_events import ConnectionOpened
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    DataFreshness,
    MemoryRuntimeState,
    RuntimeCpuId,
)
from bootloader_upgrade_tool.protocol.constants import CpuId, DeviceId, Feature
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE


READ_AT = datetime(2026, 7, 19, 4, 0, tzinfo=timezone.utc)


def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _close_memory_pages():
    yield
    app = QApplication.instance()
    if app is not None:
        for widget in app.topLevelWidgets():
            if isinstance(widget, MemoryTargetPage):
                widget.close()
        app.processEvents()


class _Controller(QObject):
    runtimeStateChanged = Signal(object)

    def __init__(self, snapshot):
        super().__init__()
        self.snapshot = snapshot
        self.requests = []

    def request_task(self, request):
        self.requests.append(request)
        return SimpleNamespace(accepted=True, task_id=f"task-{len(self.requests)}")

    def apply(self, **changes):
        self.snapshot = replace(self.snapshot, **changes)
        self.runtimeStateChanged.emit(self.snapshot)


def _device_info(cpu_id, feature_flags=int(Feature.MEMORY_READ)):
    return DeviceInfo(
        int(DeviceId.F28377D), int(cpu_id), 1, 0, 0, 1,
        feature_flags, 256, 8, 2, 2,
    )


def _binding(*, cpu_id=RuntimeCpuId.CPU1, profile=None, feature_flags=int(Feature.MEMORY_READ)):
    qt_app()
    pages = {cpu: MemoryTargetPage(cpu.value) for cpu in RuntimeCpuId}
    profile = profile or (CPU1_PROFILE if cpu_id is RuntimeCpuId.CPU1 else CPU2_PROFILE)
    info = ConnectionInfo("connection", "SCI", "COM3", READ_AT, cpu_id.value)
    backend = RuntimeBackend()
    backend._target = profile
    backend._device_info = _device_info(CpuId(int(profile.cpu_id)), feature_flags)
    backend._connection_info = info
    backend._runtime_v2_dispatcher.dispatch(ConnectionOpened(info))
    controller = _Controller(
        RuntimeSnapshot(
            state=RuntimeState.CONNECTED,
            connection_info=info,
            active_target_key=cpu_id.value,
        )
    )
    binding = MemoryRuntimeBinding(pages, controller, backend)
    return pages, controller, backend, binding


def _future_cpu2_profile():
    return replace(
        CPU2_PROFILE,
        command_set=replace(CPU2_PROFILE.command_set, memory_read=0x0230),
    )


def test_cpu1_connection_enables_only_cpu1_and_loads_profile_references() -> None:
    pages, _controller, _backend, _binding = _binding()
    assert pages[RuntimeCpuId.CPU1].refresh_button.isEnabled()
    assert not pages[RuntimeCpuId.CPU2].refresh_button.isEnabled()
    assert pages[RuntimeCpuId.CPU1].reference_range_combo.count() > 1


def test_inactive_page_retains_its_snapshot_and_local_controls() -> None:
    pages, _controller, backend, binding = _binding()
    generation = backend.connection_generation
    backend._runtime_v2_store.replace_memory_state(
        RuntimeCpuId.CPU2,
        MemoryRuntimeState(
            RuntimeCpuId.CPU2,
            DataFreshness.STALE,
            0x3000,
            (0x1234,),
            READ_AT,
            generation,
        ),
    )
    binding._render(backend.runtime_v2_snapshot)

    cpu2 = pages[RuntimeCpuId.CPU2]
    assert cpu2.memory_table.item(0, 1).text() == "1234"
    assert cpu2.freshness_value.text() == "Stale"
    assert cpu2.display_format_combo.isEnabled() and cpu2.search_edit.isEnabled()
    assert not cpu2.refresh_button.isEnabled()


def test_cpu2_enablement_is_symmetric_when_profile_and_device_advertise_capability() -> None:
    pages, _controller, _backend, _binding = _binding(
        cpu_id=RuntimeCpuId.CPU2, profile=_future_cpu2_profile()
    )
    assert not pages[RuntimeCpuId.CPU1].refresh_button.isEnabled()
    assert pages[RuntimeCpuId.CPU2].refresh_button.isEnabled()


def test_current_cpu2_profile_and_missing_feature_keep_matching_page_disabled() -> None:
    pages, _controller, _backend, _binding = _binding(cpu_id=RuntimeCpuId.CPU2)
    assert not pages[RuntimeCpuId.CPU2].refresh_button.isEnabled()

    pages, _controller, _backend, _binding = _binding(feature_flags=0)
    assert not pages[RuntimeCpuId.CPU1].refresh_button.isEnabled()


def test_target_mismatch_never_submits_and_matching_page_builds_request() -> None:
    pages, controller, backend, _binding = _binding()
    pages[RuntimeCpuId.CPU2].refreshRequested.emit("cpu2")
    assert controller.requests == []

    cpu1 = pages[RuntimeCpuId.CPU1]
    cpu1.start_address_edit.setText("0x12345678")
    cpu1.word_count_spin.setValue(17)
    cpu1.refreshRequested.emit("cpu1")

    request = controller.requests[-1]
    assert request == MemoryRefreshRequest(
        "connection", "cpu1", backend.connection_generation, 0x12345678, 17
    )


def test_invalid_address_does_not_submit_or_clear_old_data_and_unclassified_address_submits() -> None:
    pages, controller, backend, binding = _binding()
    backend.record_memory_read_success(
        RuntimeCpuId.CPU1, backend.connection_generation, 0x1000, (1, 2), READ_AT
    )
    cpu1 = pages[RuntimeCpuId.CPU1]
    cpu1.start_address_edit.setText("not-an-address")
    cpu1.refreshRequested.emit("cpu1")
    assert controller.requests == []
    assert cpu1.memory_table.item(0, 1).text() == "0001"
    assert "Input error" in cpu1.preview_notice.text()

    cpu1.start_address_edit.setText("0xDEADBEEF")
    cpu1.word_count_spin.setValue(1)
    cpu1.refreshRequested.emit("cpu1")
    assert controller.requests[-1].start_address == 0xDEADBEEF


def test_busy_disables_reads_and_idle_reenables_matching_page() -> None:
    pages, controller, _backend, _binding = _binding()
    controller.apply(state=RuntimeState.BUSY, active_task_id="other")
    assert all(not page.refresh_button.isEnabled() for page in pages.values())
    controller.apply(state=RuntimeState.CONNECTED, active_task_id=None)
    assert pages[RuntimeCpuId.CPU1].refresh_button.isEnabled()


def test_clear_is_per_cpu_and_display_search_are_local() -> None:
    pages, controller, backend, binding = _binding()
    generation = backend.connection_generation
    for cpu_id, address in ((RuntimeCpuId.CPU1, 0x1000), (RuntimeCpuId.CPU2, 0x2000)):
        backend._runtime_v2_store.replace_memory_state(
            cpu_id,
            MemoryRuntimeState(cpu_id, DataFreshness.STALE, address, (0x0041,), READ_AT, generation),
        )
    binding._render(backend.runtime_v2_snapshot)

    pages[RuntimeCpuId.CPU1].clearRequested.emit("cpu1")
    assert backend.runtime_v2_snapshot.memory_states[RuntimeCpuId.CPU1].words == ()
    assert backend.runtime_v2_snapshot.memory_states[RuntimeCpuId.CPU2].words == (0x0041,)

    pages[RuntimeCpuId.CPU2].display_format_combo.setCurrentText("ASCII")
    pages[RuntimeCpuId.CPU2].search_edit.setText("A")
    assert controller.requests == []
