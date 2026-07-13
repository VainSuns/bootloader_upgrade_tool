"""Connection lifecycle wrapper around a ByteTransport and protocol client."""

from __future__ import annotations

from dataclasses import dataclass

from ..cancellation import CancellationToken
from ..protocol.boot_protocol_client import BootProtocolClient
from ..protocol.frame_reader import FrameReader
from ..transport.base import ByteTransport, TransportOpenResult


@dataclass
class UpgradeSessionConfig:
    transport: ByteTransport


class UpgradeSession:
    def __init__(self, config: UpgradeSessionConfig) -> None:
        self.config = config
        self._client = BootProtocolClient(config.transport, FrameReader(config.transport))

    def connect(
        self,
        cancellation: CancellationToken | None = None,
    ) -> TransportOpenResult:
        self._client.reset_connection_state()
        return self.config.transport.open(cancellation)

    def disconnect(self) -> None:
        self.config.transport.close()

    @property
    def client(self) -> BootProtocolClient:
        return self._client
