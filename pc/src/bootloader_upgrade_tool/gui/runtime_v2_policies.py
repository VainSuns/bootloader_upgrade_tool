"""Stateless ordered policies for Runtime V2 transitions."""

from __future__ import annotations

from dataclasses import replace

from .runtime_v2_events import (
    ActiveTargetChanged,
    ConnectionClosed,
    ConnectionGenerationChanged,
    ConnectionOpened,
    DomainEvent,
    OperationStarted,
    ProgramImageChanged,
    RamImageChanged,
    SessionChanged,
    RuntimeOperationType,
)
from .runtime_v2_models import (
    ConnectionRuntimeState,
    MemoryRuntimeState,
    RuntimeCpuId,
    RuntimeStateDraft,
    TargetResourceState,
)


class StaleConnectionEventError(RuntimeError):
    pass


class SessionChangeBlockedError(RuntimeError):
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


class SessionStatePolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        if not isinstance(event, SessionChanged):
            return
        if draft.connection is not None:
            raise SessionChangeBlockedError("Session change requires no active Runtime V2 connection")
        for cpu_id in RuntimeCpuId:
            draft.replace_target_resource(cpu_id, TargetResourceState(cpu_id))
            draft.replace_memory_state(cpu_id, MemoryRuntimeState(cpu_id))


class EvidenceInvalidationPolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        if isinstance(
            event,
            (
                ConnectionOpened,
                ConnectionClosed,
                ConnectionGenerationChanged,
                ActiveTargetChanged,
                SessionChanged,
            ),
        ):
            for cpu_id in RuntimeCpuId:
                current = draft.target_resource(cpu_id)
                draft.replace_target_resource(
                    cpu_id, replace(current, verify_evidence=None, ram_crc_evidence=None)
                )
            return
        if isinstance(event, OperationStarted):
            current = draft.target_resource(event.cpu_id)
            field = (
                "verify_evidence"
                if event.operation_type
                in (
                    RuntimeOperationType.ERASE,
                    RuntimeOperationType.PROGRAM,
                    RuntimeOperationType.VERIFY,
                )
                else "ram_crc_evidence"
            )
            draft.replace_target_resource(event.cpu_id, replace(current, **{field: None}))
            return
        if isinstance(event, ProgramImageChanged) and event.summary is not None:
            current = draft.target_resource(event.cpu_id)
            evidence = current.verify_evidence
            if evidence is not None and evidence.image_identity != event.summary.identity:
                draft.replace_target_resource(
                    event.cpu_id, replace(current, verify_evidence=None)
                )
        elif isinstance(event, RamImageChanged) and event.summary is not None:
            current = draft.target_resource(event.cpu_id)
            evidence = current.ram_crc_evidence
            if evidence is not None and evidence.ram_image_identity != event.summary.identity:
                draft.replace_target_resource(
                    event.cpu_id, replace(current, ram_crc_evidence=None)
                )


class ProgramImageStatePolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        if isinstance(event, ProgramImageChanged):
            current = draft.target_resource(event.cpu_id)
            draft.replace_target_resource(
                event.cpu_id,
                replace(
                    current,
                    program_image_path=event.path,
                    program_image_summary=event.summary,
                    program_image_parse_status=event.parse_status,
                    program_image_parse_error=event.parse_error,
                ),
            )


class RamImageStatePolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        if isinstance(event, RamImageChanged):
            current = draft.target_resource(event.cpu_id)
            draft.replace_target_resource(
                event.cpu_id,
                replace(
                    current,
                    ram_image_path=event.path,
                    ram_image_summary=event.summary,
                    ram_image_parse_status=event.parse_status,
                    ram_image_parse_error=event.parse_error,
                ),
            )


DEFAULT_DOMAIN_POLICIES: tuple[DomainPolicy, ...] = (
    ConnectionGenerationPolicy(),
    ConnectionStatePolicy(),
    EvidenceInvalidationPolicy(),
    SessionStatePolicy(),
    ProgramImageStatePolicy(),
    RamImageStatePolicy(),
)


__all__ = [
    "ConnectionGenerationPolicy",
    "ConnectionStatePolicy",
    "DEFAULT_DOMAIN_POLICIES",
    "DomainPolicy",
    "EvidenceInvalidationPolicy",
    "ProgramImageStatePolicy",
    "RamImageStatePolicy",
    "SessionChangeBlockedError",
    "SessionStatePolicy",
    "StaleConnectionEventError",
]
