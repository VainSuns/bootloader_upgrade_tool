"""Stateless ordered policies for Runtime V2 transitions."""

from __future__ import annotations

from dataclasses import replace

from ..images.models import RamImageIdentity

from .runtime_v2_events import (
    ActiveTargetChanged,
    ConnectionClosed,
    ConnectionGenerationChanged,
    ConnectionOpened,
    DomainEvent,
    OperationStarted,
    OperationSucceeded,
    ProgramImageChanged,
    RamImageChanged,
    SectorSelectionChanged,
    SessionChanged,
    RuntimeOperationType,
)
from .runtime_v2_models import (
    ConnectionRuntimeState,
    ImageParseStatus,
    MemoryRuntimeState,
    RamCrcEvidence,
    RuntimeCpuId,
    RuntimeStateDraft,
    TargetResourceState,
    VerifyEvidence,
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


class VerifyEvidencePolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        if not (
            isinstance(event, OperationSucceeded)
            and event.operation_type is RuntimeOperationType.VERIFY
        ):
            return
        connection = draft.connection
        resource = draft.target_resource(event.cpu_id)
        summary = resource.program_image_summary
        if not (
            connection is not None
            and connection.cpu_id is event.cpu_id
            and connection.generation == event.connection_generation
            and resource.program_image_parse_status is ImageParseStatus.READY
            and summary is not None
            and summary.identity == event.image_identity
        ):
            return
        draft.replace_target_resource(
            event.cpu_id,
            replace(
                resource,
                verify_evidence=VerifyEvidence(
                    event.cpu_id,
                    event.connection_generation,
                    event.image_identity,
                    event.operation_id,
                ),
            ),
        )


class RamCrcEvidencePolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        if not (
            isinstance(event, OperationSucceeded)
            and event.operation_type is RuntimeOperationType.RAM_CRC
            and type(event.image_identity) is RamImageIdentity
        ):
            return
        connection = draft.connection
        resource = draft.target_resource(event.cpu_id)
        summary = resource.ram_image_summary
        if not (
            connection is not None
            and connection.cpu_id is event.cpu_id
            and connection.generation == event.connection_generation
            and resource.ram_image_parse_status is ImageParseStatus.READY
            and summary is not None
            and summary.identity == event.image_identity
        ):
            return
        draft.replace_target_resource(
            event.cpu_id,
            replace(
                resource,
                ram_crc_evidence=RamCrcEvidence(
                    event.cpu_id,
                    event.connection_generation,
                    event.image_identity,
                    event.image_identity.entry_point,
                    event.image_identity.image_crc32,
                    event.operation_id,
                ),
            ),
        )


class SectorSelectionPolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event: DomainEvent, draft: RuntimeStateDraft) -> None:
        if isinstance(event, SectorSelectionChanged):
            current = draft.target_resource(event.cpu_id)
            draft.replace_target_resource(
                event.cpu_id,
                replace(
                    current,
                    erase_scope=event.erase_scope,
                    custom_sector_mask=event.custom_sector_mask,
                ),
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
    VerifyEvidencePolicy(),
    RamCrcEvidencePolicy(),
    SectorSelectionPolicy(),
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
    "RamCrcEvidencePolicy",
    "RamImageStatePolicy",
    "SessionChangeBlockedError",
    "SectorSelectionPolicy",
    "SessionStatePolicy",
    "StaleConnectionEventError",
    "VerifyEvidencePolicy",
]
