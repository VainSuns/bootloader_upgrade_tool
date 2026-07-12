from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.gui.connection_models import SerialConnectRequest, SerialDisconnectRequest
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import TaskFinalStatus, TaskStepState
from bootloader_upgrade_tool.operations import DiscoveredTarget, TargetDiscoveryOutcome
from bootloader_upgrade_tool.operations.results import OperationErrorInfo, OperationResult
from bootloader_upgrade_tool.protocol.constants import CpuId, DeviceId
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE
from bootloader_upgrade_tool.transport.base import TransportError, TransportTimeoutError


def _info(cpu_id=CpuId.CPU1):
    return DeviceInfo(int(DeviceId.F28377D), int(cpu_id), 1, 0, 0, 1, 0, 256, 8, 2, 2)


class _Transport:
    def __init__(self, config, close_error=None):
        self.config = config
        self.close_error = close_error
        self.closed = 0

    def close(self):
        self.closed += 1
        if self.close_error:
            raise self.close_error


class _Session:
    def __init__(self, config, connect_error=None, close_error=None):
        self.config = config
        self.client = SimpleNamespace(device_info=_info())
        self.connect_error = connect_error
        self.close_error = close_error
        self.disconnected = 0

    def connect(self):
        if self.connect_error:
            raise self.connect_error

    def disconnect(self):
        self.disconnected += 1
        if self.close_error:
            raise self.close_error
        self.config.transport.close()


def _discovery_for(cpu_id=CpuId.CPU1):
    info = _info(cpu_id)
    profile, key = (CPU1_PROFILE, "cpu1") if cpu_id == CpuId.CPU1 else (CPU2_PROFILE, "cpu2")

    def discover(_session):
        target = DiscoveredTarget(info, profile, key)
        return TargetDiscoveryOutcome(OperationResult(True, "discover_connected_target", "discovery", "RESOLVE_TARGET", {}), target)

    return discover


def _backend(*, cpu_id=CpuId.CPU1, connect_error=None, session_close_error=None, transport_close_error=None, discovery=None):
    transports, sessions = [], []

    def transport_factory(config):
        transport = _Transport(config, transport_close_error)
        transports.append(transport)
        return transport

    def session_factory(config):
        session = _Session(config, connect_error, session_close_error)
        sessions.append(session)
        return session

    return RuntimeBackend(transport_factory, session_factory, discovery or _discovery_for(cpu_id)), transports, sessions


def _connect(backend, task_id="task"):
    events = []
    result = backend.connect(task_id, SerialConnectRequest(" COM3 ", 115200, 11, 22, 33), None, events.append)
    return result, events


def _seed_image_cache(backend):
    pair = (object(), object())
    with backend._image_lock:
        backend._image_selection_revision = 1
        backend._prepared_flash_image, backend._prepared_image_summary = pair
    return pair


@pytest.mark.parametrize(("cpu_id", "target_key"), [(CpuId.CPU1, "cpu1"), (CpuId.CPU2, "cpu2")])
def test_backend_connect_discovers_target_and_disconnects(cpu_id, target_key):
    backend, transports, sessions = _backend(cpu_id=cpu_id)
    result, events = _connect(backend)
    assert result.status is TaskFinalStatus.SUCCEEDED and result.payload.target_key == target_key
    assert [event.step_id for event in events if event.step_state is TaskStepState.STARTED] == ["connect_sci", "identify_target"]
    assert transports[0].config.port == "COM3" and transports[0].config.autobaud_timeout_ms == 33
    assert backend.active_session is sessions[0]
    disconnected = backend.disconnect("task2", SerialDisconnectRequest(), None, events.append)
    assert disconnected.status is TaskFinalStatus.SUCCEEDED and backend.active_session is None
    assert sessions[0].disconnected == 1 and transports[0].closed == 1


@pytest.mark.parametrize(
    ("exception", "code"),
    [(TransportTimeoutError("late"), "SCI_AUTOBAUD_TIMEOUT"), (TransportError("bad"), "SCI_CONNECTION_FAILED"), (OSError("gone"), "SCI_CONNECTION_FAILED")],
)
def test_backend_maps_expected_connect_errors_and_cleans(exception, code):
    backend, transports, _ = _backend(connect_error=exception)
    result, _ = _connect(backend)
    assert result.error.code == code and result.error.details["cleanup_pending"] is False
    assert backend.active_session is None and transports[0].closed == 1


def test_backend_preserves_expected_discovery_failure_and_cleans():
    error = OperationErrorInfo("UNKNOWN_CPU_ID", "unknown", "RESOLVE_TARGET", True, {})
    failed = TargetDiscoveryOutcome(OperationResult(False, "discover_connected_target", "discovery", "RESOLVE_TARGET", {}, error=error), None)
    backend, transports, _ = _backend(discovery=lambda _: failed)
    result, _ = _connect(backend)
    assert result.error.code == "UNKNOWN_CPU_ID" and result.error.details["cleanup_pending"] is False
    assert transports[0].closed == 1


def test_backend_unexpected_discovery_error_cleans_then_reraises():
    backend, transports, _ = _backend(discovery=lambda _: (_ for _ in ()).throw(RuntimeError("bug")))
    with pytest.raises(RuntimeError, match="bug"):
        _connect(backend)
    assert backend.active_session is None and transports[0].closed == 1


def test_backend_identify_progress_error_cleans_then_reraises():
    backend, transports, _ = _backend()

    def progress(event):
        if event.step_id == "identify_target" and event.step_state is TaskStepState.STARTED:
            raise RuntimeError("progress bug")

    with pytest.raises(RuntimeError, match="progress bug"):
        backend.connect("task", SerialConnectRequest("COM3", 115200, 11, 22, 33), None, progress)
    assert backend.active_session is None and transports[0].closed == 1


def test_backend_pending_cleanup_blocks_new_transport_until_retry_succeeds():
    backend, transports, sessions = _backend(connect_error=OSError("open"), session_close_error=OSError("session"), transport_close_error=OSError("port"))
    failed, _ = _connect(backend)
    assert failed.error.details["cleanup_pending"] is True
    retry, _ = _connect(backend, "retry")
    assert retry.summary == "Cleanup failed" and retry.error.details["cleanup_pending"] is True
    assert len(transports) == len(sessions) == 1
    transports[0].close_error = None
    backend._session_factory = lambda config: _Session(config)
    recovered, _ = _connect(backend, "recovered")
    assert recovered.status is TaskFinalStatus.SUCCEEDED and len(transports) == 2


def test_backend_invalid_connect_preserves_pending_cleanup_detail():
    backend, _, _ = _backend()
    backend._pending_close = _Transport(SimpleNamespace())
    result = backend.connect("task", object(), None, lambda _: None)
    assert result.error.code == "INVALID_CONNECTION_SETTINGS"
    assert result.error.details["cleanup_pending"] is True


def test_backend_disconnect_failure_is_pending_and_shutdown_retry_clears_it():
    backend, transports, sessions = _backend(session_close_error=OSError("busy"), transport_close_error=OSError("busy"))
    connected, _ = _connect(backend)
    assert connected.status is TaskFinalStatus.SUCCEEDED
    failed = backend.disconnect("disconnect", SerialDisconnectRequest(), None, lambda _: None)
    assert failed.summary == "Disconnect failed" and failed.error.details["cleanup_pending"] is True
    sessions[0].close_error = None
    transports[0].close_error = None
    shutdown = backend.shutdown("shutdown", SimpleNamespace(step_id="shutdown"), None, lambda _: None)
    assert shutdown.status is TaskFinalStatus.SUCCEEDED
    again = backend.shutdown("again", SimpleNamespace(step_id="shutdown"), None, lambda _: None)
    assert again.status is TaskFinalStatus.SUCCEEDED


def test_backend_rejects_concurrent_entry_without_waiting():
    backend = RuntimeBackend()
    backend._lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="concurrent"):
            backend.execute("task", object(), None, lambda _: None)
    finally:
        backend._lock.release()


def test_cpu1_connect_preserves_but_cpu2_connect_clears_image_cache():
    cpu1, _, _ = _backend(cpu_id=CpuId.CPU1)
    pair = _seed_image_cache(cpu1)
    _connect(cpu1)
    assert cpu1.prepared_image_cache == pair

    cpu2, _, _ = _backend(cpu_id=CpuId.CPU2)
    _seed_image_cache(cpu2)
    _connect(cpu2)
    assert cpu2.prepared_image_cache == (None, None)


@pytest.mark.parametrize("close_error", (None, OSError("busy")))
def test_disconnect_success_or_failure_clears_image_cache(close_error):
    backend, _, _ = _backend(
        session_close_error=close_error,
        transport_close_error=close_error,
    )
    _connect(backend)
    _seed_image_cache(backend)

    backend.disconnect("disconnect", SerialDisconnectRequest(), None, lambda _: None)

    assert backend.prepared_image_cache == (None, None)


def test_shutdown_clears_image_cache_without_a_connection():
    backend = RuntimeBackend()
    _seed_image_cache(backend)

    backend.shutdown("shutdown", SimpleNamespace(step_id="shutdown"), None, lambda _: None)

    assert backend.prepared_image_cache == (None, None)
