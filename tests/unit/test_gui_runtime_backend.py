from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.gui.connection_models import SerialConnectRequest, SerialDisconnectRequest
from bootloader_upgrade_tool.gui.runtime_backend import RuntimeBackend
from bootloader_upgrade_tool.gui.runtime_models import TaskFinalStatus, TaskStepState
from bootloader_upgrade_tool.gui.runtime_v2_models import ConnectionGeneration, RuntimeCpuId
from bootloader_upgrade_tool.gui.runtime_v2_events import (
    ActiveTargetChanged,
    ConnectionGenerationChanged,
)
from bootloader_upgrade_tool.operations import DiscoveredTarget, TargetDiscoveryOutcome
from bootloader_upgrade_tool.operations.results import OperationErrorInfo, OperationResult
from bootloader_upgrade_tool.protocol.constants import CpuId, DeviceId
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import CPU1_PROFILE, CPU2_PROFILE
from bootloader_upgrade_tool.transport import (
    TransportError,
    TransportOpenResult,
    TransportOpenStatus,
    TransportTimeoutError,
)


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
    def __init__(self, config, connect_error=None, close_error=None, connect_result=None, on_connect=None):
        self.config = config
        self.client = SimpleNamespace(device_info=_info())
        self.connect_error = connect_error
        self.close_error = close_error
        self.connect_result = connect_result or TransportOpenResult(TransportOpenStatus.OPENED, False, "OPEN_COMPLETE")
        self.on_connect = on_connect
        self.cancellation = None
        self.disconnected = 0

    def connect(self, cancellation):
        self.cancellation = cancellation
        if self.connect_error:
            raise self.connect_error
        if self.on_connect:
            self.on_connect(cancellation)
        return self.connect_result

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


def _backend(*, cpu_id=CpuId.CPU1, connect_error=None, session_close_error=None, transport_close_error=None, connect_result=None, on_connect=None, discovery=None):
    transports, sessions = [], []

    def transport_factory(config):
        transport = _Transport(config, transport_close_error)
        transports.append(transport)
        return transport

    def session_factory(config):
        session = _Session(config, connect_error, session_close_error, connect_result, on_connect)
        sessions.append(session)
        return session

    return RuntimeBackend(transport_factory, session_factory, discovery or _discovery_for(cpu_id)), transports, sessions


def _connect(backend, task_id="task", cancellation=None):
    events = []
    result = backend.connect(task_id, SerialConnectRequest(" COM3 ", 115200, 11, 22, 33), cancellation, events.append)
    return result, events


class _Cancellation:
    def __init__(self):
        self.requested = False

    def request_cancel(self):
        self.requested = True

    def is_cancel_requested(self):
        return self.requested


def _seed_image_cache(backend):
    pair = (object(), object())
    with backend._image_lock:
        backend._image_selection_revision = 1
        backend._prepared_flash_image, backend._prepared_image_summary = pair
    return pair


@pytest.mark.parametrize(("cpu_id", "target_key"), [(CpuId.CPU1, "cpu1"), (CpuId.CPU2, "cpu2")])
def test_backend_connect_discovers_target_and_disconnects(cpu_id, target_key):
    backend, transports, sessions = _backend(cpu_id=cpu_id)
    backend._metadata_status_snapshot = object()
    result, events = _connect(backend)
    assert result.status is TaskFinalStatus.SUCCEEDED and result.payload.target_key == target_key
    assert [event.step_id for event in events if event.step_state is TaskStepState.STARTED] == ["connect_sci", "identify_target"]
    assert transports[0].config.port == "COM3" and transports[0].config.autobaud_timeout_ms == 33
    assert backend.active_session is sessions[0]
    assert backend.metadata_status_snapshot is None
    backend._metadata_status_snapshot = object()
    disconnected = backend.disconnect("task2", SerialDisconnectRequest(), None, events.append)
    assert disconnected.status is TaskFinalStatus.SUCCEEDED and backend.active_session is None
    assert backend.metadata_status_snapshot is None
    assert sessions[0].disconnected == 1 and transports[0].closed == 1


def test_backend_connection_lifecycle_publishes_one_atomic_v2_result_per_change():
    backend, _, _ = _backend()
    transitions = []
    backend.subscribe_runtime_v2(transitions.append)

    connected, _ = _connect(backend)
    assert connected.status is TaskFinalStatus.SUCCEEDED
    assert len(transitions) == 1
    assert transitions[0].snapshot.connection_generation == ConnectionGeneration(1)
    assert transitions[0].snapshot.connection.cpu_id is RuntimeCpuId.CPU1
    assert tuple(type(event) for event in transitions[0].derived_events) == (
        ConnectionGenerationChanged,
        ActiveTargetChanged,
    )

    disconnected = backend.disconnect("disconnect", SerialDisconnectRequest(), None, None)
    assert disconnected.status is TaskFinalStatus.SUCCEEDED
    assert len(transitions) == 2
    assert transitions[-1].snapshot.connection is None
    assert transitions[-1].snapshot.connection_generation == ConnectionGeneration(1)

    backend._discovery_operation = _discovery_for(CpuId.CPU2)
    reconnected, _ = _connect(backend, "reconnect")
    assert reconnected.status is TaskFinalStatus.SUCCEEDED
    assert len(transitions) == 3
    assert transitions[-1].snapshot.connection_generation == ConnectionGeneration(2)
    assert transitions[-1].snapshot.connection.cpu_id is RuntimeCpuId.CPU2


def test_backend_v2_listener_failure_does_not_change_connect_or_disconnect_result():
    backend, _, _ = _backend()

    def fail(_result):
        raise RuntimeError("observer failed")

    backend.subscribe_runtime_v2(fail)
    connected, _ = _connect(backend)
    connection_info = connected.payload
    disconnected = backend.disconnect("disconnect", SerialDisconnectRequest(), None, None)
    assert connected.status is TaskFinalStatus.SUCCEEDED
    assert connection_info.target_key == "cpu1"
    assert disconnected.status is TaskFinalStatus.SUCCEEDED


def test_backend_clear_without_v2_connection_publishes_nothing():
    backend, _, _ = _backend()
    transitions = []
    backend.subscribe_runtime_v2(transitions.append)
    backend._clear_active()
    backend._clear_active()
    assert transitions == []


def test_backend_forwards_exact_cancellation_token():
    backend, _, sessions = _backend()
    cancellation = _Cancellation()
    result, _ = _connect(backend, cancellation=cancellation)
    assert result.status is TaskFinalStatus.SUCCEEDED
    assert sessions[0].cancellation is cancellation


def test_backend_open_cancellation_is_clean_and_does_not_discover_or_close_again():
    discovery_calls = []
    open_result = TransportOpenResult(TransportOpenStatus.CANCELLED, True, "OPEN_SETTLE")
    backend, transports, sessions = _backend(
        connect_result=open_result,
        discovery=lambda session: discovery_calls.append(session),
    )
    result, events = _connect(backend, cancellation=_Cancellation())
    assert result.status is TaskFinalStatus.CANCELLED and result.cancel_requested
    assert result.payload == {"cancellation_stage": "OPEN_SETTLE", "resource_released": True}
    assert result.step_results == (open_result,) and not discovery_calls
    assert [event.step_state for event in events] == [TaskStepState.STARTED]
    assert sessions[0].disconnected == 0 and transports[0].closed == 0
    assert backend.active_session is backend.active_transport is backend.active_target is None


def test_backend_cancels_after_open_before_discovery_and_closes_once():
    discovery_calls = []
    backend, transports, sessions = _backend(
        on_connect=lambda cancellation: cancellation.request_cancel(),
        discovery=lambda session: discovery_calls.append(session),
    )
    result, events = _connect(backend, cancellation=_Cancellation())
    assert result.status is TaskFinalStatus.CANCELLED and result.payload["cancellation_stage"] == "BEFORE_TARGET_DISCOVERY"
    assert result.payload["transport_open_stage"] == "OPEN_COMPLETE" and result.payload["resource_released"]
    assert not discovery_calls
    assert not any(event.step_id == "identify_target" for event in events)
    assert sessions[0].disconnected == 1 and transports[0].closed == 1


def test_backend_cancels_after_successful_discovery_without_committing_session():
    cancellation = _Cancellation()

    def discover(session):
        cancellation.request_cancel()
        return _discovery_for()(session)

    backend, transports, sessions = _backend(discovery=discover)
    result, events = _connect(backend, cancellation=cancellation)
    assert result.status is TaskFinalStatus.CANCELLED
    assert result.payload["cancellation_stage"] == "AFTER_TARGET_DISCOVERY"
    assert len(result.step_results) == 2 and isinstance(result.step_results[1], OperationResult)
    assert any(event.step_id == "identify_target" and event.step_state is TaskStepState.COMPLETED for event in events)
    assert sessions[0].disconnected == 1 and transports[0].closed == 1
    assert backend.connection_info is None and backend.active_target is None


def test_backend_discovery_failure_takes_precedence_over_requested_cancellation():
    cancellation = _Cancellation()
    error = OperationErrorInfo("UNKNOWN_CPU_ID", "unknown", "RESOLVE_TARGET", True, {})
    failed = TargetDiscoveryOutcome(OperationResult(False, "discover_connected_target", "discovery", "RESOLVE_TARGET", {}, error=error), None)

    def discover(_session):
        cancellation.request_cancel()
        return failed

    backend, transports, _ = _backend(discovery=discover)
    result, _ = _connect(backend, cancellation=cancellation)
    assert result.status is TaskFinalStatus.FAILED and result.error.code == "UNKNOWN_CPU_ID"
    assert transports[0].closed == 1


def test_backend_cancellation_cleanup_failure_stays_pending_and_blocks_allocation():
    backend, transports, sessions = _backend(
        on_connect=lambda cancellation: cancellation.request_cancel(),
        session_close_error=OSError("session busy"),
        transport_close_error=OSError("port busy"),
    )
    failed, _ = _connect(backend, cancellation=_Cancellation())
    assert failed.status is TaskFinalStatus.FAILED and failed.cancel_requested
    assert failed.error.code == "CONNECT_CANCELLATION_CLEANUP_FAILED"
    assert failed.error.details["cleanup_pending"] is True
    assert failed.error.details["resource_released"] is False
    assert backend.pending_close is transports[0] and backend.active_session is None
    retry, _ = _connect(backend, "retry", _Cancellation())
    assert retry.summary == "Cleanup failed" and len(transports) == len(sessions) == 1
    transports[0].close_error = None
    backend._session_factory = lambda config: _Session(config)
    recovered, _ = _connect(backend, "recovered", _Cancellation())
    assert recovered.status is TaskFinalStatus.SUCCEEDED and len(transports) == 2


@pytest.mark.parametrize("invalid", (None, True, "opened", object()))
def test_backend_invalid_session_open_result_cleans_and_raises(invalid):
    backend, transports, sessions = _backend(connect_result=invalid)
    sessions.clear()

    def session_factory(config):
        session = _Session(config)
        session.connect_result = invalid
        sessions.append(session)
        return session

    backend._session_factory = session_factory
    with pytest.raises(TypeError, match="TransportOpenResult"):
        _connect(backend, cancellation=_Cancellation())
    assert sessions[0].disconnected == 1 and transports[0].closed == 1
    assert backend.active_session is backend.active_transport is backend.active_target is None
    assert backend.connection_info is None


@pytest.mark.parametrize(
    ("open_result", "message"),
    (
        (TransportOpenResult("opened", False, "OPEN_COMPLETE"), "status"),  # type: ignore[arg-type]
        (TransportOpenResult(TransportOpenStatus.OPENED, 0, "OPEN_COMPLETE"), "resource_released"),  # type: ignore[arg-type]
        (TransportOpenResult(TransportOpenStatus.CANCELLED, 1, "OPEN_SETTLE"), "resource_released"),  # type: ignore[arg-type]
    ),
)
def test_backend_rejects_invalid_transport_open_result_fields(open_result, message):
    discovery_calls = []
    backend, transports, sessions = _backend(
        connect_result=open_result,
        discovery=lambda session: discovery_calls.append(session),
    )
    with pytest.raises(TypeError, match=message):
        _connect(backend, cancellation=_Cancellation())
    assert not discovery_calls
    assert sessions[0].disconnected == 1 and transports[0].closed == 1
    assert backend.active_session is backend.active_transport is backend.active_target is None
    assert backend.connection_info is None


@pytest.mark.parametrize("stage", (None, 0, ""))
def test_transport_open_result_constructor_rejects_invalid_stage(stage):
    with pytest.raises(ValueError, match="stage"):
        TransportOpenResult(TransportOpenStatus.OPENED, False, stage)  # type: ignore[arg-type]


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


def test_cpu2_completed_progress_failure_preserves_image_cache():
    backend, _, _ = _backend(cpu_id=CpuId.CPU2)
    pair = _seed_image_cache(backend)

    def progress(event):
        if event.step_id == "identify_target" and event.step_state is TaskStepState.COMPLETED:
            raise RuntimeError("progress bug")

    with pytest.raises(RuntimeError, match="progress bug"):
        backend.connect("task", SerialConnectRequest("COM3", 115200, 11, 22, 33), None, progress)
    assert backend.prepared_image_cache == pair


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
    backend._metadata_status_snapshot = object()

    backend.shutdown("shutdown", SimpleNamespace(step_id="shutdown"), None, lambda _: None)

    assert backend.prepared_image_cache == (None, None)
    assert backend.metadata_status_snapshot is None


def test_new_backend_has_empty_symmetric_runtime_v2_state():
    backend = RuntimeBackend()
    snapshot = backend.runtime_v2_snapshot
    assert snapshot.connection_generation == ConnectionGeneration(0)
    assert snapshot.connection is None
    assert set(snapshot.target_resources) == {RuntimeCpuId.CPU1, RuntimeCpuId.CPU2}
    assert set(snapshot.memory_states) == {RuntimeCpuId.CPU1, RuntimeCpuId.CPU2}
    with pytest.raises(TypeError):
        backend.target_resources[RuntimeCpuId.CPU1] = object()  # type: ignore[index]


def test_success_disconnect_and_reconnect_advance_runtime_v2_generation():
    backend, _, _ = _backend(cpu_id=CpuId.CPU1)
    first, _ = _connect(backend)
    assert first.status is TaskFinalStatus.SUCCEEDED
    assert backend.connection_generation == ConnectionGeneration(1)
    assert backend.runtime_v2_snapshot.connection.cpu_id is RuntimeCpuId.CPU1
    legacy_connection = backend.connection_info

    backend.disconnect("disconnect", SerialDisconnectRequest(), None, lambda _: None)
    disconnected = backend.runtime_v2_snapshot
    assert disconnected.connection is None
    assert disconnected.connection_generation == ConnectionGeneration(1)

    backend._discovery_operation = _discovery_for(CpuId.CPU2)
    second, _ = _connect(backend, "reconnect")
    assert second.status is TaskFinalStatus.SUCCEEDED
    assert backend.connection_generation == ConnectionGeneration(2)
    assert backend.runtime_v2_snapshot.connection.cpu_id is RuntimeCpuId.CPU2
    assert legacy_connection.target_key == "cpu1" and backend.connection_info.target_key == "cpu2"


def test_cancelled_and_failed_connects_do_not_allocate_runtime_v2_generation():
    cancelled, _, _ = _backend(
        connect_result=TransportOpenResult(TransportOpenStatus.CANCELLED, True, "OPEN_SETTLE")
    )
    cancelled_transitions = []
    cancelled.subscribe_runtime_v2(cancelled_transitions.append)
    result, _ = _connect(cancelled, cancellation=_Cancellation())
    assert result.status is TaskFinalStatus.CANCELLED
    assert cancelled.connection_generation == ConnectionGeneration(0)
    assert cancelled.runtime_v2_snapshot.connection is None
    assert cancelled_transitions == []

    error = OperationErrorInfo("UNKNOWN_CPU_ID", "unknown", "RESOLVE_TARGET", True, {})
    outcome = TargetDiscoveryOutcome(
        OperationResult(False, "discover_connected_target", "discovery", "RESOLVE_TARGET", {}, error=error),
        None,
    )
    failed, _, _ = _backend(discovery=lambda _: outcome)
    failed_transitions = []
    failed.subscribe_runtime_v2(failed_transitions.append)
    result, _ = _connect(failed)
    assert result.status is TaskFinalStatus.FAILED
    assert failed.connection_generation == ConnectionGeneration(0)
    assert failed.runtime_v2_snapshot.connection is None
    assert failed_transitions == []


def test_runtime_v2_does_not_mirror_or_clear_legacy_prepared_image_cache():
    backend, _, _ = _backend(cpu_id=CpuId.CPU1)
    pair = _seed_image_cache(backend)
    _connect(backend)
    assert backend.prepared_image_cache == pair
    assert all(state.program_image_summary is None for state in backend.target_resources.values())
