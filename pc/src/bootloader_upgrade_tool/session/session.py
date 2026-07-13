"""Connection lifecycle wrapper around a ByteTransport and protocol client."""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol.boot_protocol_client import BootProtocolClient
from ..protocol.frame_reader import FrameReader
from ..transport.base import ByteTransport


@dataclass
class UpgradeSessionConfig:
    transport: ByteTransport


class UpgradeSession:
    def __init__(self, config: UpgradeSessionConfig) -> None:
        self.config = config
        self._client = BootProtocolClient(config.transport, FrameReader(config.transport))

    def connect(self) -> None:
        self._client.clear_capabilities()
        self.config.transport.open()

    def disconnect(self) -> None:
        self.config.transport.close()

    @property
    def client(self) -> BootProtocolClient:
        return self._client
