from __future__ import annotations

import signal

import pytest

from bootloader_upgrade_tool.cli.runtime import (
    CancellationSource,
    CliRuntime,
    CliRuntimeConfig,
    cancellation_handler,
)
from bootloader_upgrade_tool.operations import (
    DiscoveredTarget,
    OperationResult,
    TargetDiscoveryOutcome,
)
from bootloader_upgrade_tool.protocol.constants import CpuId, DeviceId
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import CPU1_PROFILE
from bootloader_upgrade_tool.transport import TransportOpenResult, TransportOpenStatus


class FakeSession:
    def __init__(self, *, open_result=None) -> None:
        self.client = type("Client", (), {})()
        self.client.device_info = DeviceInfo(
            int(DeviceId.F28377D), int(CpuId.CPU1), 1, 0, 0, 1, 0, 256, 8, 2, 2
        )
        self.open_result = open_result or TransportOpenResult(
            TransportOpenStatus.OPENED, False, "OPEN_COMPLETE"
        )
        self.connect_calls = []
        self.disconnect_calls = 0

    def connect(self, cancellation=None):
        self.connect_calls.append(cancellation)
        return self.open_result

    def disconnect(self) -> None:
        self.disconnect_calls += 1


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
    assert context.target is runtime.discovered_target.target_profile
    assert context.cancellation is source
    assert session.disconnect_calls == 1


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


def test_discovery_failure_is_cached_and_disconnect_still_releases_session() -> None:
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
