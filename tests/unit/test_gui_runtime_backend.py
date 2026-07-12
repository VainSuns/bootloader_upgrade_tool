from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.gui.connection_models import SerialConnectRequest, SerialDisconnectRequest
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import TaskFinalStatus, TaskStepState
from bootloader_upgrade_tool.operations import DiscoveredTarget, TargetDiscoveryOutcome
from bootloader_upgrade_tool.operations.results import OperationResult
from bootloader_upgrade_tool.protocol.constants import CpuId, DeviceId
from bootloader_upgrade_tool.protocol.models import DeviceInfo


INFO = DeviceInfo(int(DeviceId.F28377D), int(CpuId.CPU1), 1, 0, 0, 1, 0, 256, 8, 2, 2)


class _Transport:
    def __init__(self, config):
        self.config = config
        self.opened = False
        self.closed = 0

    def open(self):
        self.opened = True

    def close(self):
        self.closed += 1


class _Session:
    def __init__(self, config):
        self.config = config
        self.client = SimpleNamespace(device_info=INFO)
        self.connected = False
        self.disconnected = 0

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.disconnected += 1


def _discovery(session):
    target = DiscoveredTarget(INFO, __import__("bootloader_upgrade_tool.targets", fromlist=["CPU1_PROFILE"]).CPU1_PROFILE, "cpu1")
    return TargetDiscoveryOutcome(OperationResult(True, "discover_connected_target", "discovery", "RESOLVE_TARGET", {}), target)


def test_backend_connect_owns_session_and_disconnects():
    transports = []
    sessions = []

    def transport_factory(config):
        item = _Transport(config)
        transports.append(item)
        return item

    def session_factory(config):
        item = _Session(config)
        sessions.append(item)
        return item

    backend = RuntimeBackend(transport_factory, session_factory, _discovery)
    events = []
    result = backend.connect("task", SerialConnectRequest(" COM3 ", 115200, 11, 22, 33), None, events.append)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert [event.step_id for event in events if event.step_state is TaskStepState.STARTED] == ["connect_sci", "identify_target"]
    assert transports[0].config.port == "COM3"
    assert transports[0].config.autobaud_timeout_ms == 33
    assert backend.active_session is sessions[0]
    assert result.payload.target_key == "cpu1"

    disconnected = backend.disconnect("task2", SerialDisconnectRequest(), None, events.append)
    assert disconnected.status is TaskFinalStatus.SUCCEEDED
    assert backend.active_session is None
    assert sessions[0].disconnected == 1


def test_backend_rejects_concurrent_entry_without_waiting():
    backend = RuntimeBackend()
    backend._lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="concurrent"):
            backend.execute("task", object(), None, lambda _: None)
    finally:
        backend._lock.release()
