"""Transport contracts for byte-stream protocol clients."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from ..cancellation import CancellationToken


class TransportError(RuntimeError):
    pass


class TransportTimeoutError(TransportError):
    pass


class TransportClosedError(TransportError):
    pass


class TransportOpenStatus(Enum):
    OPENED = "opened"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TransportOpenResult:
    status: TransportOpenStatus
    resource_released: bool
    stage: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage:
            raise ValueError("stage must be a non-empty string")
        if self.status is TransportOpenStatus.OPENED and self.resource_released:
            raise ValueError("OPENED requires resource_released=False")
        if self.status is TransportOpenStatus.CANCELLED and not self.resource_released:
            raise ValueError("CANCELLED requires resource_released=True")


class ByteTransport(Protocol):
    def open(
        self,
        cancellation: CancellationToken | None = None,
    ) -> TransportOpenResult: ...
    def close(self) -> None: ...
    def write_all(self, data: bytes) -> None: ...
    def read_some(self, max_bytes: int) -> bytes: ...
