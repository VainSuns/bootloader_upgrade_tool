from __future__ import annotations

import signal
from dataclasses import replace

import pytest

from bootloader_upgrade_tool.cli.runtime import (
    CancellationSource,
    CliRuntime,
    CliRuntimeConfig,
    RuntimeCommunicationError,
    cancellation_handler,
)
from bootloader_upgrade_tool.operations import (
    DiscoveredTarget,
    FlashOperationContext,
    OperationErrorInfo,
    OperationResult,
    TargetDiscoveryOutcome,
)
from bootloader_upgrade_tool.protocol.constants import CpuId, DeviceId
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import CPU1_PROFILE
from bootloader_upgrade_tool.transport import TransportError, TransportOpenResult, TransportOpenStatus


class FakeSession:
    def __init__(self, *, open_result=None, disconnect_error=None) -> None:
        self.client = type("Client", (), {})()
        self.client.device_info = DeviceInfo(
            int(DeviceId.F28377D), int(CpuId.CPU1), 1, 0, 0, 1, 0, 256, 8, 2, 2
        )
        self.open_result = open_result or TransportOpenResult(
            TransportOpenStatus.OPENED, False, "OPEN_COMPLETE"
        )
        self.disconnect_error = disconnect_error
        self.connect_calls = []
        self.disconnect_calls = 0

    def connect(self, cancellation=None):
        self.connect_calls.append(cancellation)
        return self.open_result

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.disconnect_error is not None:
            raise self.disconnect_error


class FakeTransport:
    def __init__(self) -> None:
        self.config = None

    def open(self, cancellation=None):
        del cancellation
        return TransportOpenResult(TransportOpenStatus.OPENED, False, "OPEN_COMPLETE")

    def close(self) -> None:
        pass

    def write_all(self, data: bytes) -> None:
        del data

    def read_some(self, max_bytes: int) -> bytes:
        del max_bytes
        return b""


def successful_discovery(session: FakeSession) -> TargetDiscoveryOutcome:
    discovered = DiscoveredTarget(session.client.device_info, CPU1_PROFILE, "cpu1")
    return TargetDiscoveryOutcome(
        OperationResult(True, "discover_connected_target", "discovery", "RESOLVE_TARGET", {}),
        discovered,
    )


def make_runtime(
    *,
    config: CliRuntimeConfig | None = None,
    session: FakeSession | None = None,
    discovery=None,
    configs: list | None = None,
):
    session = session or FakeSession()
    configs = configs if configs is not None else []
    transport = FakeTransport()

    def transport_factory(serial_config):
        configs.append(serial_config)
        transport.config = serial_config
        return transport

    def session_factory(_session_config):
        return session

    return CliRuntime(
        config or CliRuntimeConfig(port="COM7"),
        transport_factory=transport_factory,
        session_factory=session_factory,
        discovery=discovery or successful_discovery,
    ), session, configs


def test_serial_factory_preserves_transport_defaults_without_timeout_override() -> None:
    runtime, _session, configs = make_runtime()

    runtime.connect()

    assert configs[0].port == "COM7"
    assert configs[0].baudrate == 9600
    assert configs[0].tx_timeout_ms == 1000
    assert configs[0].rx_timeout_ms == 1000
    assert configs[0].autobaud_timeout_ms == 5000


def test_timeout_ms_only_changes_serial_transport_timeouts() -> None:
    runtime, _session, configs = make_runtime(
        config=CliRuntimeConfig(port="COM8", baud=115200, timeout_ms=77)
    )

    runtime.connect()

    serial_config = configs[0]
    assert serial_config.baudrate == 115200
    assert serial_config.tx_timeout_ms == 77
    assert serial_config.rx_timeout_ms == 77
    assert serial_config.autobaud_timeout_ms == 77
    assert not hasattr(serial_config, "command_timeout_ms")


def test_one_shot_lifecycle_discovers_once_then_builds_context_with_same_token() -> None:
    calls: list[str] = []
    source = CancellationSource()
    session = FakeSession()

    def discover(item):
        calls.append("discover")
        assert item is session
        return successful_discovery(item)

    runtime, _session, _configs = make_runtime(session=session, discovery=discover)
    runtime.connect(source)
    first = runtime.discover()
    second = runtime.discover()
    context = runtime.operation_context()
    runtime.disconnect()

    assert first is second
    assert calls == ["discover"]
    assert session.connect_calls == [source]
    assert context.session is session
    assert context.target is CPU1_PROFILE
    assert context.cancellation is source
    assert session.disconnect_calls == 1
    with pytest.raises(RuntimeError, match="discovery"):
        runtime.discovered_target


def test_flash_operation_context_reuses_session_target_token_and_progress() -> None:
    source = CancellationSource()
    runtime, session, _configs = make_runtime()
    runtime.connect(source)
    runtime.discover()
    service = object()
    progress = object()

    context = runtime.flash_operation_context(service, progress)

    assert isinstance(context, FlashOperationContext)
    assert context.session is session
    assert context.target is runtime.target
    assert context.cancellation is source
    assert context.progress is progress
    assert context.service is service
    assert context.force_service_attach is False


def test_cancelled_open_does_not_discover_or_double_close() -> None:
    session = FakeSession(
        open_result=TransportOpenResult(
            TransportOpenStatus.CANCELLED,
            True,
            "BEFORE_SERIAL_OPEN",
        )
    )
    discoveries: list[object] = []
    runtime, _session, _configs = make_runtime(
        session=session,
        discovery=lambda item: discoveries.append(item),
    )

    result = runtime.connect()
    runtime.disconnect()

    assert result.status is TransportOpenStatus.CANCELLED
    assert runtime.is_connected is False
    assert discoveries == []
    assert session.disconnect_calls == 0


def test_discovery_failure_clears_state_and_releases_session() -> None:
    from bootloader_upgrade_tool.operations import OperationErrorInfo, OperationResult, TargetDiscoveryOutcome

    session = FakeSession()
    failure = TargetDiscoveryOutcome(
        OperationResult(
            False,
            "discover_connected_target",
            "discovery",
            "GET_DEVICE_INFO",
            {},
            error=OperationErrorInfo("PROTOCOL_ERROR", "no response", "GET_DEVICE_INFO"),
        ),
        None,
    )
    calls: list[object] = []
    runtime, _session, _configs = make_runtime(
        session=session,
        discovery=lambda item: calls.append(item) or failure,
    )

    runtime.connect()
    assert runtime.discover() is failure
    assert not runtime.is_connected
    with pytest.raises(RuntimeError, match="discovery"):
        runtime.discovered_target
    runtime.disconnect()

    assert calls == [session]
    assert session.disconnect_calls == 1


def test_cancellation_handler_sets_only_the_cooperative_flag_and_restores_handler() -> None:
    source = CancellationSource()
    original = signal.getsignal(signal.SIGINT)

    with cancellation_handler(source):
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        handler(signal.SIGINT, None)
        assert source.is_cancel_requested()

    assert signal.getsignal(signal.SIGINT) == original


def test_cancellation_handler_can_route_sigint_to_current_generation_source() -> None:
    first = CancellationSource()
    second = CancellationSource()
    current = [first]

    with cancellation_handler(first, source_provider=lambda: current[0]):
        handler = signal.getsignal(signal.SIGINT)
        handler(signal.SIGINT, None)
        assert first.requested
        assert not second.requested

        first.reset()
        current[0] = second
        handler(signal.SIGINT, None)
        assert not first.requested
        assert second.requested


def test_cancellation_source_can_be_reset_at_a_shell_command_boundary() -> None:
    source = CancellationSource()

    source.request()
    assert source.requested

    source.reset()

    assert not source.requested


def test_runtime_can_create_two_sequential_connection_generations() -> None:
    sessions = [FakeSession(), FakeSession()]
    created: list[FakeSession] = []
    discoveries: list[FakeSession] = []

    def session_factory(_config):
        session = sessions[len(created)]
        created.append(session)
        return session

    def discovery(session):
        discoveries.append(session)
        return successful_discovery(session)

    runtime, _session, configs = make_runtime(discovery=discovery)
    runtime._session_factory = session_factory

    runtime.connect()
    first = runtime.session
    runtime.discover()
    runtime.disconnect()

    with pytest.raises(RuntimeError, match="discovery"):
        runtime.discovered_target

    runtime.connect()
    second = runtime.session
    runtime.discover()

    assert first is sessions[0]
    assert second is sessions[1]
    assert first is not second
    assert discoveries == sessions
    assert len(configs) == 2


def test_runtime_generations_use_fresh_transport_session_and_target_contexts() -> None:
    transports: list[FakeTransport] = []
    sessions = [FakeSession(), FakeSession()]
    profiles = [
        replace(CPU1_PROFILE, name="target-a"),
        replace(CPU1_PROFILE, name="target-b"),
    ]

    def transport_factory(_config):
        transport = FakeTransport()
        transports.append(transport)
        return transport

    created: list[FakeSession] = []

    def session_factory(_config):
        session = sessions[len(created)]
        created.append(session)
        return session

    def discovery(session):
        index = sessions.index(session)
        profile = profiles[index]
        discovered = DiscoveredTarget(session.client.device_info, profile, "cpu1")
        return TargetDiscoveryOutcome(
            OperationResult(True, "discover_connected_target", "discovery", "RESOLVE_TARGET", {}),
            discovered,
        )

    runtime = CliRuntime(
        CliRuntimeConfig(port="COM7"),
        transport_factory=transport_factory,
        session_factory=session_factory,
        discovery=discovery,
    )

    runtime.connect()
    runtime.discover()
    first_session = runtime.session
    first_source = runtime.cancellation
    first_context = runtime.operation_context()
    first_flash_context = runtime.flash_operation_context(object())
    runtime.disconnect()

    runtime.connect()
    runtime.discover()
    second_source = runtime.cancellation
    second_context = runtime.operation_context()
    second_flash_context = runtime.flash_operation_context(object())

    assert transports[0] is not transports[1]
    assert sessions[0] is not sessions[1]
    assert first_source is not second_source
    assert first_session is sessions[0]
    assert first_context.session is sessions[0]
    assert first_context.target is profiles[0]
    assert first_flash_context.session is sessions[0]
    assert first_flash_context.target is profiles[0]
    assert second_context.session is sessions[1]
    assert second_context.target is profiles[1]
    assert second_context.cancellation is runtime.cancellation
    assert second_flash_context.session is sessions[1]
    assert second_flash_context.target is profiles[1]
    assert second_flash_context.cancellation is runtime.cancellation
    assert runtime.target is profiles[1]


def test_discovery_failure_allows_fresh_generation_retry() -> None:
    transports: list[FakeTransport] = []
    sessions = [FakeSession(), FakeSession()]
    created: list[FakeSession] = []
    discoveries: list[FakeSession] = []
    failure = TargetDiscoveryOutcome(
        OperationResult(
            False,
            "discover_connected_target",
            "discovery",
            "GET_DEVICE_INFO",
            {},
            error=OperationErrorInfo("PROTOCOL_ERROR", "first discovery failed", "GET_DEVICE_INFO"),
        ),
        None,
    )

    def transport_factory(_config):
        transport = FakeTransport()
        transports.append(transport)
        return transport

    def session_factory(_config):
        session = sessions[len(created)]
        created.append(session)
        return session

    def discovery(session):
        discoveries.append(session)
        if len(discoveries) == 1:
            return failure
        return successful_discovery(session)

    runtime = CliRuntime(
        CliRuntimeConfig(port="COM7"),
        transport_factory=transport_factory,
        session_factory=session_factory,
        discovery=discovery,
    )

    runtime.connect()
    assert runtime.discover() is failure
    assert not runtime.is_connected

    runtime.connect()
    assert runtime.discover().result.ok

    assert transports[0] is not transports[1]
    assert sessions[0] is not sessions[1]
    assert discoveries == sessions
    assert runtime.session is sessions[1]


def test_cancelled_connection_generation_does_not_block_the_next_connect() -> None:
    cancelled = FakeSession(
        open_result=TransportOpenResult(
            TransportOpenStatus.CANCELLED,
            True,
            "BEFORE_SERIAL_OPEN",
        )
    )
    opened = FakeSession()
    sessions = [cancelled, opened]
    created: list[FakeSession] = []

    runtime, _session, _configs = make_runtime()
    runtime._session_factory = lambda _config: sessions[len(created)]
    original_factory = runtime._session_factory

    def session_factory(config):
        session = original_factory(config)
        created.append(session)
        return session

    runtime._session_factory = session_factory

    assert runtime.connect().status is TransportOpenStatus.CANCELLED
    first_source = runtime.cancellation
    with pytest.raises(RuntimeError, match="session"):
        runtime.session

    assert runtime.connect().status is TransportOpenStatus.OPENED
    second_source = runtime.cancellation
    assert runtime.session is opened
    assert first_source is not second_source


def test_disconnect_clears_state_even_when_session_close_fails() -> None:
    session = FakeSession(disconnect_error=TransportError("close failed"))
    runtime, _session, _configs = make_runtime(session=session)
    runtime.connect()
    runtime.discover()
    first_source = runtime.cancellation

    with pytest.raises(RuntimeCommunicationError, match="close failed"):
        runtime.disconnect()

    assert not runtime.is_connected
    with pytest.raises(RuntimeError, match="session"):
        runtime.session
    with pytest.raises(RuntimeError, match="discovery"):
        runtime.discovered_target

    assert runtime.connect().status is TransportOpenStatus.OPENED
    assert runtime.cancellation is not first_source


def test_missing_port_is_deferred_until_connection_configuration_is_needed() -> None:
    config = CliRuntimeConfig(port=None)

    with pytest.raises(ValueError, match="--port"):
        config.require_port()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"port": "COM1", "baud": 0}, "baud"),
        ({"port": "COM1", "timeout_ms": 0}, "timeout-ms"),
    ],
)
def test_runtime_configuration_rejects_non_positive_values(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        CliRuntimeConfig(**kwargs)
