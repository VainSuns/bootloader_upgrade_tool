"""One-shot runtime for the formal CLI."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import signal
from threading import Event
from typing import Callable, Iterator

from ..cancellation import CancellationToken
from ..images import PreparedServiceImage
from ..operations import (
    DiscoveredTarget,
    FlashOperationContext,
    OperationContext,
    TargetDiscoveryOutcome,
    discover_connected_target,
)
from ..session import UpgradeSession, UpgradeSessionConfig
from ..transport import (
    ByteTransport,
    SerialTransport,
    SerialTransportConfig,
    TransportError,
    TransportOpenResult,
    TransportOpenStatus,
)


class CliConfigurationError(ValueError):
    """The command cannot be run with the supplied connection configuration."""


class RuntimeCommunicationError(RuntimeError):
    """A transport/session lifecycle failure that maps to exit code 3."""


class CancellationSource:
    """Mutable CLI-owned source implementing the read-only token contract."""

    def __init__(self) -> None:
        self._event = Event()

    def request_cancellation(self) -> None:
        self._event.set()

    def request(self) -> None:
        self.request_cancellation()

    def is_cancel_requested(self) -> bool:
        return self._event.is_set()

    @property
    def requested(self) -> bool:
        return self.is_cancel_requested()


@contextmanager
def cancellation_handler(source: CancellationSource) -> Iterator[CancellationSource]:
    """Install a cooperative SIGINT handler for one one-shot command."""

    previous = signal.getsignal(signal.SIGINT)

    def handle(_signum: int, _frame: object) -> None:
        source.request_cancellation()

    signal.signal(signal.SIGINT, handle)
    try:
        yield source
    finally:
        signal.signal(signal.SIGINT, previous)


install_cancellation_handler = cancellation_handler


@dataclass(frozen=True, slots=True)
class CliRuntimeConfig:
    transport: str = "serial"
    port: str | None = None
    baud: int = 9600
    timeout_ms: int | None = None

    def __post_init__(self) -> None:
        if self.transport != "serial":
            raise CliConfigurationError("only the serial transport is supported")
        if self.port is not None and not isinstance(self.port, str):
            raise CliConfigurationError("serial port must be a string")
        if type(self.baud) is not int or self.baud <= 0:
            raise CliConfigurationError("baud must be a positive integer")
        if self.timeout_ms is not None and (
            type(self.timeout_ms) is not int or self.timeout_ms <= 0
        ):
            raise CliConfigurationError("timeout-ms must be a positive integer")

    def require_port(self) -> str:
        if not self.port or not self.port.strip():
            raise CliConfigurationError("--port is required for command execution")
        return self.port

    def serial_transport_config(self) -> SerialTransportConfig:
        """Build only transport timeouts; protocol command timeouts stay untouched."""

        port = self.require_port()
        if self.timeout_ms is None:
            return SerialTransportConfig(port=port, baudrate=self.baud)
        return SerialTransportConfig(
            port=port,
            baudrate=self.baud,
            tx_timeout_ms=self.timeout_ms,
            rx_timeout_ms=self.timeout_ms,
            autobaud_timeout_ms=self.timeout_ms,
        )


TransportFactory = Callable[[SerialTransportConfig], ByteTransport]
SessionFactory = Callable[[UpgradeSessionConfig], UpgradeSession]
DiscoveryFunction = Callable[[UpgradeSession], TargetDiscoveryOutcome]


def create_serial_transport(config: SerialTransportConfig) -> ByteTransport:
    return SerialTransport(config)


def create_upgrade_session(config: UpgradeSessionConfig) -> UpgradeSession:
    return UpgradeSession(config)


class CliRuntime:
    """Small connection/discovery owner for one CLI invocation."""

    def __init__(
        self,
        config: CliRuntimeConfig,
        *,
        transport_factory: TransportFactory | None = None,
        session_factory: SessionFactory | None = None,
        discovery: DiscoveryFunction = discover_connected_target,
        cancellation_source: CancellationSource | None = None,
    ) -> None:
        self.config = config
        self.cancellation_source = cancellation_source or CancellationSource()
        self._transport_factory = transport_factory or create_serial_transport
        self._session_factory = session_factory or create_upgrade_session
        self._discovery = discovery
        self._session: UpgradeSession | None = None
        self._connected = False
        self._disconnect_attempted = False
        self._discovery_attempted = False
        self._discovery_outcome: TargetDiscoveryOutcome | None = None
        self._cancellation: CancellationToken = self.cancellation_source

    @property
    def session(self) -> UpgradeSession:
        if self._session is None:
            raise RuntimeError("CLI session has not been created")
        return self._session

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def discovery_outcome(self) -> TargetDiscoveryOutcome | None:
        return self._discovery_outcome

    @property
    def discovered_target(self) -> DiscoveredTarget:
        outcome = self._discovery_outcome
        if outcome is None or outcome.discovered_target is None:
            raise RuntimeError("CLI target discovery has not succeeded")
        return outcome.discovered_target

    @property
    def target(self):
        return self.discovered_target.target_profile

    @property
    def cancellation(self) -> CancellationToken:
        return self._cancellation

    def connect(self, cancellation: CancellationToken | None = None) -> TransportOpenResult:
        if self._session is not None:
            raise RuntimeError("CLI runtime can connect only once")
        self.config.require_port()
        self._cancellation = cancellation or self.cancellation_source
        try:
            transport = self._transport_factory(self.config.serial_transport_config())
            session = self._session_factory(UpgradeSessionConfig(transport))
            self._session = session
            result = session.connect(self._cancellation)
        except TransportError as exc:
            raise RuntimeCommunicationError(str(exc)) from exc
        if result.status is TransportOpenStatus.OPENED:
            self._connected = True
        elif result.status is TransportOpenStatus.CANCELLED:
            # The transport owns cleanup for a CANCELLED open result.
            self._connected = False
        else:
            raise RuntimeError(f"unknown transport open status: {result.status!r}")
        return result

    def discover(self) -> TargetDiscoveryOutcome:
        if not self._connected:
            raise RuntimeError("CLI runtime must be connected before discovery")
        if self._discovery_attempted:
            if self._discovery_outcome is None:
                raise RuntimeError("CLI discovery completed without an outcome")
            return self._discovery_outcome
        self._discovery_attempted = True
        try:
            outcome = self._discovery(self.session)
        except TransportError as exc:
            raise RuntimeCommunicationError(str(exc)) from exc
        self._discovery_outcome = outcome
        return outcome

    def operation_context(self, progress=None) -> OperationContext:  # type: ignore[no-untyped-def]
        return OperationContext(
            session=self.session,
            target=self.target,
            progress=progress,
            cancellation=self._cancellation,
        )

    def flash_operation_context(
        self,
        service: PreparedServiceImage,
        progress=None,
    ) -> FlashOperationContext:  # type: ignore[no-untyped-def]
        return FlashOperationContext(
            session=self.session,
            target=self.target,
            progress=progress,
            cancellation=self._cancellation,
            service=service,
            force_service_attach=False,
        )

    def disconnect(self) -> None:
        if not self._connected or self._disconnect_attempted:
            return
        self._disconnect_attempted = True
        self._connected = False
        try:
            self.session.disconnect()
        except TransportError as exc:
            raise RuntimeCommunicationError(str(exc)) from exc


__all__ = [
    "CancellationSource",
    "CliConfigurationError",
    "CliRuntime",
    "CliRuntimeConfig",
    "RuntimeCommunicationError",
    "cancellation_handler",
    "create_serial_transport",
    "create_upgrade_session",
    "install_cancellation_handler",
]
