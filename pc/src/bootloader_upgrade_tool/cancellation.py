"""Read-only cooperative cancellation contract."""

from __future__ import annotations

from typing import Protocol


class CancellationToken(Protocol):
    def is_cancel_requested(self) -> bool: ...


def cancellation_requested(cancellation: CancellationToken | None) -> bool:
    return cancellation is not None and bool(cancellation.is_cancel_requested())
