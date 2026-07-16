"""Stateless ordered policies for Runtime V2 transitions."""

from __future__ import annotations

from .runtime_v2_events import (
    ActiveTargetChanged,
    ConnectionClosed,
    ConnectionGenerationChanged,
    ConnectionOpened,
    DomainEvent,
)
from .runtime_v2_models import ConnectionRuntimeState, RuntimeStateDraft


class StaleConnectionEventError(RuntimeError):
    pass


class DomainPolicy:
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        raise NotImplementedError


class ConnectionGenerationPolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        if isinstance(event, ConnectionOpened):
            previous = draft.connection_generation
            current = previous.next()
            draft.replace_connection_generation(current)
            draft.record(ConnectionGenerationChanged(previous, current))


class ConnectionStatePolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        if isinstance(event, ConnectionOpened):
            if draft.connection_generation == draft.original_connection_generation:
                raise RuntimeError("ConnectionGenerationPolicy must run first")
            connection = ConnectionRuntimeState.from_connection_info(
                event.connection_info, draft.connection_generation
            )
            draft.replace_connection(connection)
            draft.record(ActiveTargetChanged(connection.cpu_id))
        elif isinstance(event, ConnectionClosed):
            connection = draft.connection
            if connection is None:
                raise StaleConnectionEventError("no active Runtime V2 connection")
            if connection.connection_id != event.connection_id:
                raise StaleConnectionEventError("connection ID does not match active connection")
            if connection.generation != event.connection_generation:
                raise StaleConnectionEventError("connection generation is stale")
            draft.replace_connection(None)
            draft.record(ActiveTargetChanged(None))


DEFAULT_DOMAIN_POLICIES: tuple[DomainPolicy, ...] = (
    ConnectionGenerationPolicy(),
    ConnectionStatePolicy(),
)


__all__ = [
    "ConnectionGenerationPolicy",
    "ConnectionStatePolicy",
    "DEFAULT_DOMAIN_POLICIES",
    "DomainPolicy",
    "StaleConnectionEventError",
]
