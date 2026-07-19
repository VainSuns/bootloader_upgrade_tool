from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo
from bootloader_upgrade_tool.gui.runtime_v2_events import (
    ActiveTargetChanged,
    ConnectionClosed,
    ConnectionGenerationChanged,
    ConnectionOpened,
    DomainEvent,
    OperationFailed,
    OperationStarted,
    OperationSucceeded,
    ProgramImageChanged,
    RamImageChanged,
    SectorSelectionChanged,
    SessionChanged,
    RuntimeOperationType,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration,
    EraseScope,
    ImageParseStatus,
    FlashImageSummary,
    RamImageSummary,
    RuntimeCpuId,
    RuntimeStateStore,
    TargetResourceState,
    MemoryRuntimeState,
    VerifyEvidence,
    RamCrcEvidence,
)
from bootloader_upgrade_tool.images import ImageIdentity
from bootloader_upgrade_tool.images.models import RamImageIdentity
from bootloader_upgrade_tool.gui.runtime_v2_policies import (
    ConnectionGenerationPolicy,
    ConnectionStatePolicy,
    DEFAULT_DOMAIN_POLICIES,
    DomainPolicy,
    DiagnosticsFreshnessPolicy,
    EvidenceInvalidationPolicy,
    MetadataFreshnessPolicy,
    SessionChangeBlockedError,
    SessionStatePolicy,
    ProgramImageStatePolicy,
    RamCrcEvidencePolicy,
    RamImageStatePolicy,
    SectorSelectionPolicy,
    StaleConnectionEventError,
    VerifyEvidencePolicy,
)
from bootloader_upgrade_tool.gui.runtime_v2_transition import (
    DomainEventDispatcher,
    DomainTransitionError,
)

FLASH_ID = ImageIdentity(0x82400, 8, 0x1234, 0x82407)
OTHER_FLASH_ID = replace(FLASH_ID, image_crc32=0x5678)
RAM_ID = RamImageIdentity(0x8000, 8, 0x1234)
OTHER_RAM_ID = replace(RAM_ID, image_crc32=0x5678)


def _info(cpu: str = "cpu1", connection_id: str = "connection-1") -> ConnectionInfo:
    return ConnectionInfo(
        connection_id,
        "SCI / RS232",
        "COM3",
        datetime.now(timezone.utc),
        cpu,
    )


EVENTS = (
    ActiveTargetChanged(RuntimeCpuId.CPU1),
    ProgramImageChanged(RuntimeCpuId.CPU1, "", ImageParseStatus.EMPTY),
    RamImageChanged(RuntimeCpuId.CPU2, "", ImageParseStatus.EMPTY),
    ConnectionOpened(_info()),
    ConnectionClosed("connection-1", ConnectionGeneration(1)),
    ConnectionGenerationChanged(ConnectionGeneration(0), ConnectionGeneration(1)),
    OperationStarted(
        "operation", RuntimeOperationType.ERASE, RuntimeCpuId.CPU1, ConnectionGeneration(1)
    ),
    OperationSucceeded(
        "operation",
        RuntimeOperationType.PROGRAM,
        RuntimeCpuId.CPU1,
        ConnectionGeneration(1),
        ImageIdentity(1, 2, 3, 4),
    ),
    OperationFailed(
        "operation",
        RuntimeOperationType.RAM_CRC,
        RuntimeCpuId.CPU2,
        ConnectionGeneration(1),
        RamImageIdentity(1, 2, 3),
        "FAILED",
    ),
    SessionChanged(),
    SectorSelectionChanged(RuntimeCpuId.CPU1, EraseScope.CUSTOM, 2),
)


@pytest.mark.parametrize("event", EVENTS)
def test_events_are_typed_frozen_and_slotted(event) -> None:
    assert isinstance(event, DomainEvent) and is_dataclass(event)
    assert "__dict__" not in dir(event)
    field = fields(event)[0] if fields(event) else None
    if field is not None:
        with pytest.raises(FrozenInstanceError):
            setattr(event, field.name, getattr(event, field.name))


@pytest.mark.parametrize(
    "factory",
    (
        lambda: ActiveTargetChanged("cpu1"),
        lambda: ProgramImageChanged("cpu1", "", ImageParseStatus.EMPTY),
        lambda: RamImageChanged(None, "", ImageParseStatus.EMPTY),
        lambda: ConnectionClosed("", ConnectionGeneration()),
        lambda: ConnectionClosed("id", 1),
        lambda: OperationStarted(
            "", RuntimeOperationType.ERASE, RuntimeCpuId.CPU1, ConnectionGeneration()
        ),
        lambda: OperationStarted(
            "id", "erase", RuntimeCpuId.CPU1, ConnectionGeneration()
        ),
        lambda: OperationSucceeded(
            "id", RuntimeOperationType.ERASE, "cpu1", ConnectionGeneration()
        ),
        lambda: OperationFailed(
            "id",
            RuntimeOperationType.ERASE,
            RuntimeCpuId.CPU1,
            1,
            None,
            "FAILED",
        ),
        lambda: OperationFailed(
            "id",
            RuntimeOperationType.ERASE,
            RuntimeCpuId.CPU1,
            ConnectionGeneration(),
            None,
            "",
        ),
        lambda: ConnectionOpened(_info(connection_id="")),
    ),
)
def test_events_reject_invalid_identifiers_cpu_and_generations(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_generation_change_requires_exact_increment() -> None:
    with pytest.raises(ValueError, match="previous_generation"):
        ConnectionGenerationChanged(ConnectionGeneration(1), ConnectionGeneration(3))


def test_event_payloads_exclude_images_and_live_resources() -> None:
    forbidden = {"session", "transport", "client", "qobject", "lock", "callback"}
    assert all(
        not any(word in field.name.lower() for word in forbidden)
        for event in EVENTS
        for field in fields(event)
    )


def test_runtime_v2_infrastructure_has_no_pyside_dependency() -> None:
    root = Path(__file__).parents[2] / "pc/src/bootloader_upgrade_tool/gui"
    for name in ("runtime_v2_events.py", "runtime_v2_policies.py", "runtime_v2_transition.py"):
        assert "PySide6" not in (root / name).read_text(encoding="utf-8")


def test_default_policy_order_is_fixed_and_policies_are_stateless() -> None:
    assert isinstance(DEFAULT_DOMAIN_POLICIES, tuple)
    assert tuple(type(policy) for policy in DEFAULT_DOMAIN_POLICIES) == (
        ConnectionGenerationPolicy,
        ConnectionStatePolicy,
        MetadataFreshnessPolicy,
        DiagnosticsFreshnessPolicy,
        EvidenceInvalidationPolicy,
        VerifyEvidencePolicy,
        RamCrcEvidencePolicy,
        SectorSelectionPolicy,
        SessionStatePolicy,
        ProgramImageStatePolicy,
        RamImageStatePolicy,
    )
    assert all(not hasattr(policy, "__dict__") for policy in DEFAULT_DOMAIN_POLICIES)


@pytest.mark.parametrize(
    "factory",
    (
        lambda: SectorSelectionChanged("cpu1", EraseScope.CUSTOM, 0),
        lambda: SectorSelectionChanged(RuntimeCpuId.CPU1, "custom", 0),
        lambda: SectorSelectionChanged(RuntimeCpuId.CPU1, EraseScope.CUSTOM, True),
        lambda: SectorSelectionChanged(RuntimeCpuId.CPU1, EraseScope.CUSTOM, -1),
    ),
)
def test_sector_selection_event_is_strict(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.parametrize("cpu_id", tuple(RuntimeCpuId))
def test_sector_selection_policy_updates_one_cpu_and_preserves_everything_else(cpu_id) -> None:
    store = RuntimeStateStore()
    other = RuntimeCpuId.CPU2 if cpu_id is RuntimeCpuId.CPU1 else RuntimeCpuId.CPU1
    original = TargetResourceState(
        cpu_id,
        program_image_path="app.txt",
        program_image_summary=FlashImageSummary(FLASH_ID, 2),
        program_image_parse_status=ImageParseStatus.READY,
        verify_evidence=VerifyEvidence(cpu_id, ConnectionGeneration(1), FLASH_ID, "verify"),
        ram_crc_evidence=RamCrcEvidence(
            cpu_id, ConnectionGeneration(1), RAM_ID, RAM_ID.entry_point,
            RAM_ID.image_crc32, "crc",
        ),
    )
    store.replace_target_resource(cpu_id, original)
    before_other = store.snapshot().target_resources[other]
    result = DomainEventDispatcher(store).dispatch(
        SectorSelectionChanged(cpu_id, EraseScope.CUSTOM, 6)
    )
    assert result.snapshot.target_resources[cpu_id] == replace(
        original, erase_scope=EraseScope.CUSTOM, custom_sector_mask=6
    )
    assert result.snapshot.target_resources[other] == before_other


@pytest.mark.parametrize("cpu_id", tuple(RuntimeCpuId))
def test_ram_crc_success_creates_exact_cpu_generic_evidence(cpu_id) -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    dispatcher.dispatch(ConnectionOpened(_info(cpu_id.value)))
    generation = store.snapshot().connection_generation
    store.replace_target_resource(
        cpu_id,
        TargetResourceState(
            cpu_id,
            ram_image_path="ram.txt",
            ram_image_summary=RamImageSummary(RAM_ID),
            ram_image_parse_status=ImageParseStatus.READY,
        ),
    )
    state = dispatcher.dispatch(OperationSucceeded(
        "crc-operation", RuntimeOperationType.RAM_CRC, cpu_id, generation, RAM_ID
    )).snapshot.target_resources[cpu_id]
    assert state.ram_crc_evidence == RamCrcEvidence(
        cpu_id, generation, RAM_ID, RAM_ID.entry_point, RAM_ID.image_crc32, "crc-operation"
    )


@pytest.mark.parametrize(
    "event",
    (
        OperationSucceeded("load", RuntimeOperationType.RAM_LOAD, RuntimeCpuId.CPU1, ConnectionGeneration(1), RAM_ID),
        OperationSucceeded("verify", RuntimeOperationType.VERIFY, RuntimeCpuId.CPU1, ConnectionGeneration(1), FLASH_ID),
        OperationFailed("crc", RuntimeOperationType.RAM_CRC, RuntimeCpuId.CPU1, ConnectionGeneration(1), RAM_ID, "FAILED"),
        OperationSucceeded("stale", RuntimeOperationType.RAM_CRC, RuntimeCpuId.CPU1, ConnectionGeneration(2), RAM_ID),
        OperationSucceeded("wrong", RuntimeOperationType.RAM_CRC, RuntimeCpuId.CPU2, ConnectionGeneration(1), RAM_ID),
        OperationSucceeded("mismatch", RuntimeOperationType.RAM_CRC, RuntimeCpuId.CPU1, ConnectionGeneration(1), RamImageIdentity(1, 2, 3)),
    ),
)
def test_noncurrent_ram_crc_completion_creates_no_evidence(event) -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    dispatcher.dispatch(ConnectionOpened(_info()))
    store.replace_target_resource(
        RuntimeCpuId.CPU1,
        TargetResourceState(
            RuntimeCpuId.CPU1,
            ram_image_path="ram.txt",
            ram_image_summary=RamImageSummary(RAM_ID),
            ram_image_parse_status=ImageParseStatus.READY,
        ),
    )
    dispatcher.dispatch(event)
    assert all(resource.ram_crc_evidence is None for resource in store.snapshot().target_resources.values())


@pytest.mark.parametrize("cpu_id", tuple(RuntimeCpuId))
def test_verify_success_creates_exact_cpu_generic_evidence(cpu_id) -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    dispatcher.dispatch(ConnectionOpened(_info(cpu_id.value)))
    generation = store.snapshot().connection_generation
    store.replace_target_resource(
        cpu_id,
        TargetResourceState(
            cpu_id,
            program_image_path="app.txt",
            program_image_summary=FlashImageSummary(FLASH_ID, 3),
            program_image_parse_status=ImageParseStatus.READY,
            custom_sector_mask=7,
        ),
    )
    before = store.snapshot().target_resources[cpu_id]
    result = dispatcher.dispatch(
        OperationSucceeded(
            "verify-operation",
            RuntimeOperationType.VERIFY,
            cpu_id,
            generation,
            FLASH_ID,
        )
    )
    state = result.snapshot.target_resources[cpu_id]
    assert state.verify_evidence == VerifyEvidence(
        cpu_id, generation, FLASH_ID, "verify-operation"
    )
    assert replace(state, verify_evidence=None) == before


@pytest.mark.parametrize(
    "event_factory",
    (
        lambda generation: OperationSucceeded(
            "program", RuntimeOperationType.PROGRAM, RuntimeCpuId.CPU1, generation, FLASH_ID
        ),
        lambda generation: OperationFailed(
            "verify", RuntimeOperationType.VERIFY, RuntimeCpuId.CPU1, generation, FLASH_ID, "FAILED"
        ),
        lambda generation: OperationSucceeded(
            "stale", RuntimeOperationType.VERIFY, RuntimeCpuId.CPU1,
            ConnectionGeneration(generation.value + 1), FLASH_ID
        ),
        lambda generation: OperationSucceeded(
            "wrong-cpu", RuntimeOperationType.VERIFY, RuntimeCpuId.CPU2, generation, FLASH_ID
        ),
        lambda generation: OperationSucceeded(
            "mismatch", RuntimeOperationType.VERIFY, RuntimeCpuId.CPU1, generation, OTHER_FLASH_ID
        ),
    ),
)
def test_invalid_or_nonverify_completion_creates_no_evidence(event_factory) -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    dispatcher.dispatch(ConnectionOpened(_info()))
    generation = store.snapshot().connection_generation
    store.replace_target_resource(
        RuntimeCpuId.CPU1,
        TargetResourceState(
            RuntimeCpuId.CPU1,
            program_image_path="app.txt",
            program_image_summary=FlashImageSummary(FLASH_ID, 3),
            program_image_parse_status=ImageParseStatus.READY,
        ),
    )
    result = dispatcher.dispatch(event_factory(generation))
    assert all(
        resource.verify_evidence is None
        for resource in result.snapshot.target_resources.values()
    )


def test_verify_start_clears_old_and_success_creates_new_evidence() -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    dispatcher.dispatch(ConnectionOpened(_info()))
    generation = store.snapshot().connection_generation
    store.replace_target_resource(
        RuntimeCpuId.CPU1,
        TargetResourceState(
            RuntimeCpuId.CPU1,
            program_image_path="app.txt",
            program_image_summary=FlashImageSummary(FLASH_ID, 3),
            program_image_parse_status=ImageParseStatus.READY,
            verify_evidence=VerifyEvidence(RuntimeCpuId.CPU1, generation, FLASH_ID, "old"),
        ),
    )
    started = dispatcher.dispatch(OperationStarted(
        "new", RuntimeOperationType.VERIFY, RuntimeCpuId.CPU1, generation, FLASH_ID
    ))
    assert started.snapshot.target_resources[RuntimeCpuId.CPU1].verify_evidence is None
    succeeded = dispatcher.dispatch(OperationSucceeded(
        "new", RuntimeOperationType.VERIFY, RuntimeCpuId.CPU1, generation, FLASH_ID
    ))
    assert succeeded.snapshot.target_resources[RuntimeCpuId.CPU1].verify_evidence.operation_id == "new"


@pytest.mark.parametrize("connected", (False, True))
def test_verify_success_without_connection_or_ready_summary_is_ignored(connected) -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    if connected:
        dispatcher.dispatch(ConnectionOpened(_info()))
    generation = store.snapshot().connection_generation
    store.replace_target_resource(
        RuntimeCpuId.CPU1,
        TargetResourceState(
            RuntimeCpuId.CPU1,
            program_image_path="app.txt",
            program_image_parse_status=ImageParseStatus.PARSING,
            custom_sector_mask=9,
        ),
    )
    result = dispatcher.dispatch(OperationSucceeded(
        "verify", RuntimeOperationType.VERIFY, RuntimeCpuId.CPU1, generation, FLASH_ID
    ))
    state = result.snapshot.target_resources[RuntimeCpuId.CPU1]
    assert state.verify_evidence is None
    assert state.custom_sector_mask == 9


@pytest.mark.parametrize(
    ("status", "path", "summary", "error"),
    (
        (ImageParseStatus.EMPTY, "", None, None),
        (ImageParseStatus.PARSING, "ram.txt", None, None),
        (
            ImageParseStatus.READY,
            "ram.txt",
            RamImageSummary(RamImageIdentity(0x8000, 8, 0x12345678)),
            None,
        ),
        (ImageParseStatus.ERROR, "ram.txt", None, "failed"),
    ),
)
def test_ram_image_changed_accepts_only_valid_parse_states(status, path, summary, error) -> None:
    event = RamImageChanged(RuntimeCpuId.CPU1, path, status, summary, error)
    assert event.parse_status is status


@pytest.mark.parametrize(
    "args",
    (
        (RuntimeCpuId.CPU1, "ram.txt", ImageParseStatus.EMPTY, None, "error"),
        (RuntimeCpuId.CPU1, "", ImageParseStatus.PARSING, None, None),
        (RuntimeCpuId.CPU1, "ram.txt", ImageParseStatus.READY, None, None),
        (RuntimeCpuId.CPU1, "ram.txt", ImageParseStatus.ERROR, None, ""),
        (RuntimeCpuId.CPU1, "ram.txt", "ready", None, None),
        (RuntimeCpuId.CPU1, "ram.txt", ImageParseStatus.READY, object(), None),
    ),
)
def test_ram_image_changed_rejects_invalid_parse_states(args) -> None:
    with pytest.raises((TypeError, ValueError)):
        RamImageChanged(*args)


def test_ram_image_policy_updates_one_cpu_and_preserves_other_fields() -> None:
    store = RuntimeStateStore()
    identity = ImageIdentity(0x8000, 8, 0x1234, 0x8007)
    original = replace(
        TargetResourceState(RuntimeCpuId.CPU1),
        program_image_path="app.txt",
        program_image_summary=FlashImageSummary(identity, 1),
        program_image_parse_status=ImageParseStatus.READY,
        custom_sector_mask=3,
    )
    store.replace_target_resource(RuntimeCpuId.CPU1, original)
    cpu2 = store.snapshot().target_resources[RuntimeCpuId.CPU2]
    summary = RamImageSummary(RamImageIdentity(0x9000, 16, 0xAABBCCDD))

    result = DomainEventDispatcher(store).dispatch(
        RamImageChanged(RuntimeCpuId.CPU1, "ram.txt", ImageParseStatus.READY, summary)
    )

    updated = result.snapshot.target_resources[RuntimeCpuId.CPU1]
    assert replace(
        updated,
        ram_image_path="",
        ram_image_summary=None,
        ram_image_parse_status=ImageParseStatus.EMPTY,
    ) == original
    assert result.snapshot.target_resources[RuntimeCpuId.CPU2] == cpu2
    assert result.derived_events == ()


def test_session_change_resets_both_cpu_resources_and_memory_without_changing_generation() -> None:
    store = RuntimeStateStore()
    for cpu in RuntimeCpuId:
        store.replace_target_resource(cpu, replace(TargetResourceState(cpu), program_image_path="old"))
    before = store.snapshot()
    result = DomainEventDispatcher(store).dispatch(SessionChanged())
    assert result.derived_events == ()
    assert result.snapshot.connection_generation == before.connection_generation
    assert result.snapshot.target_resources == {
        cpu: TargetResourceState(cpu) for cpu in RuntimeCpuId
    }
    assert result.snapshot.memory_states == {cpu: MemoryRuntimeState(cpu) for cpu in RuntimeCpuId}


def test_connected_session_change_fails_atomically() -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    dispatcher.dispatch(ConnectionOpened(_info()))
    before = store.snapshot()
    with pytest.raises(DomainTransitionError) as caught:
        dispatcher.dispatch(SessionChanged())
    assert isinstance(caught.value.cause, SessionChangeBlockedError)
    assert store.snapshot() == before


class _SpyPolicy(DomainPolicy):
    __slots__ = ("name", "calls")

    def __init__(self, name, calls) -> None:
        self.name, self.calls = name, calls

    def apply(self, event, draft) -> None:
        self.calls.append(self.name)


def test_custom_policies_execute_in_tuple_order() -> None:
    calls = []
    dispatcher = DomainEventDispatcher(
        RuntimeStateStore(), (_SpyPolicy("first", calls), _SpyPolicy("second", calls))
    )
    dispatcher.dispatch(SessionChanged())
    assert calls == ["first", "second"]


def test_reversed_connection_policies_cannot_commit_open() -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(
        store, (ConnectionStatePolicy(), ConnectionGenerationPolicy())
    )
    before = store.snapshot()
    with pytest.raises(DomainTransitionError) as caught:
        dispatcher.dispatch(ConnectionOpened(_info()))
    assert caught.value.policy_name == "ConnectionStatePolicy"
    assert store.snapshot() == before


def test_open_commits_once_with_ordered_derived_events() -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    seen = []
    dispatcher.subscribe(seen.append)
    result = dispatcher.dispatch(ConnectionOpened(_info()))
    assert result.snapshot.connection_generation == ConnectionGeneration(1)
    assert result.snapshot.connection.connection_id == "connection-1"
    assert tuple(type(event) for event in result.derived_events) == (
        ConnectionGenerationChanged,
        ActiveTargetChanged,
    )
    assert len(seen) == 1 and seen[0].snapshot == result.snapshot


class _ModifyPolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event, draft) -> None:
        draft.replace_target_resource(
            RuntimeCpuId.CPU1,
            replace(TargetResourceState(RuntimeCpuId.CPU1), program_image_path="changed"),
        )


class _FailPolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event, draft) -> None:
        raise LookupError("policy failed")


class _InvalidCandidatePolicy(DomainPolicy):
    __slots__ = ()

    def apply(self, event, draft) -> None:
        draft._connection_generation = "invalid"


@pytest.mark.parametrize(
    ("policies", "policy_name"),
    (((_ModifyPolicy(), _FailPolicy()), "_FailPolicy"), ((_InvalidCandidatePolicy(),), "RuntimeV2Snapshot")),
)
def test_policy_or_candidate_failure_rolls_back_and_publishes_nothing(policies, policy_name) -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store, policies)
    seen = []
    dispatcher.subscribe(seen.append)
    before = store.snapshot()
    with pytest.raises(DomainTransitionError) as caught:
        dispatcher.dispatch(SessionChanged())
    assert caught.value.policy_name == policy_name
    assert store.snapshot() == before and seen == []


def test_matching_close_clears_connection_preserves_generation_and_publishes_once() -> None:
    dispatcher = DomainEventDispatcher(RuntimeStateStore())
    opened = dispatcher.dispatch(ConnectionOpened(_info()))
    seen = []
    dispatcher.subscribe(seen.append)
    result = dispatcher.dispatch(ConnectionClosed("connection-1", ConnectionGeneration(1)))
    assert result.snapshot.connection is None
    assert result.snapshot.connection_generation == ConnectionGeneration(1)
    assert result.derived_events == (ActiveTargetChanged(None),)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "event",
    (
        ConnectionClosed("wrong", ConnectionGeneration(1)),
        ConnectionClosed("connection-1", ConnectionGeneration(0)),
    ),
)
def test_stale_close_fails_atomically_without_publication(event) -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    dispatcher.dispatch(ConnectionOpened(_info()))
    seen = []
    dispatcher.subscribe(seen.append)
    before = store.snapshot()
    with pytest.raises(DomainTransitionError) as caught:
        dispatcher.dispatch(event)
    assert isinstance(caught.value.cause, StaleConnectionEventError)
    assert store.snapshot() == before and seen == []


def test_close_without_active_connection_fails_clearly() -> None:
    store = RuntimeStateStore()
    with pytest.raises(DomainTransitionError) as caught:
        DomainEventDispatcher(store).dispatch(ConnectionClosed("id", ConnectionGeneration()))
    assert isinstance(caught.value.cause, StaleConnectionEventError)
    assert store.snapshot().connection is None


def test_listener_registry_order_unsubscribe_and_failure_isolation() -> None:
    dispatcher = DomainEventDispatcher(RuntimeStateStore())
    calls = []

    def first(result):
        calls.append("first")
        raise ValueError("listener boom")

    def second(result):
        calls.append("second")

    dispatcher.subscribe(first)
    dispatcher.subscribe(first)
    dispatcher.subscribe(second)
    dispatcher.unsubscribe(lambda result: None)
    result = dispatcher.dispatch(ConnectionOpened(_info()))
    assert calls == ["first", "second"]
    assert result.snapshot.connection is not None
    assert len(result.listener_failures) == 1
    failure = result.listener_failures[0]
    assert failure.listener_name.endswith("first")
    assert (failure.exception_type, failure.message) == ("ValueError", "listener boom")
    dispatcher.unsubscribe(first)
    dispatcher.dispatch(ConnectionClosed("connection-1", ConnectionGeneration(1)))
    assert calls == ["first", "second", "second"]


def test_program_image_event_validation_and_policy_update_one_cpu_only() -> None:
    summary = FlashImageSummary(ImageIdentity(0x82400, 8, 1, 0x82408), 2)
    event = ProgramImageChanged(
        RuntimeCpuId.CPU2, "cpu2.txt", ImageParseStatus.READY, summary
    )
    assert is_dataclass(event) and event.__dataclass_params__.frozen
    store = RuntimeStateStore()
    cpu2 = replace(
        store.snapshot().target_resources[RuntimeCpuId.CPU2],
        ram_image_path="ram.txt",
        custom_sector_mask=7,
    )
    store.replace_target_resource(RuntimeCpuId.CPU2, cpu2)
    before_cpu1 = store.snapshot().target_resources[RuntimeCpuId.CPU1]
    result = DomainEventDispatcher(store).dispatch(event)
    changed = result.snapshot.target_resources[RuntimeCpuId.CPU2]
    assert result.snapshot.target_resources[RuntimeCpuId.CPU1] == before_cpu1
    assert changed.program_image_path == "cpu2.txt"
    assert changed.program_image_summary == summary
    assert changed.ram_image_path == "ram.txt" and changed.custom_sector_mask == 7
    assert result.derived_events == ()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: ProgramImageChanged(RuntimeCpuId.CPU1, "", ImageParseStatus.PARSING),
        lambda: ProgramImageChanged(RuntimeCpuId.CPU1, "x", ImageParseStatus.READY),
        lambda: ProgramImageChanged(RuntimeCpuId.CPU1, "x", ImageParseStatus.ERROR),
        lambda: ProgramImageChanged(RuntimeCpuId.CPU1, "", ImageParseStatus.EMPTY, parse_error="bad"),
    ),
)
def test_program_image_event_rejects_invalid_state_combinations(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_runtime_operation_type_values_and_exports() -> None:
    assert [(item.name, item.value) for item in RuntimeOperationType] == [
        ("ERASE", "erase"),
        ("PROGRAM", "program"),
        ("VERIFY", "verify"),
        ("RAM_LOAD", "ram_load"),
        ("RAM_CRC", "ram_crc"),
    ]
    from bootloader_upgrade_tool.gui import runtime_v2_events, runtime_v2_policies

    assert "RuntimeOperationType" in runtime_v2_events.__all__
    assert "EvidenceInvalidationPolicy" in runtime_v2_policies.__all__


def test_operation_event_fields_are_strict_and_correlated() -> None:
    correlated = [
        "operation_id",
        "operation_type",
        "cpu_id",
        "connection_generation",
        "image_identity",
    ]
    assert [field.name for field in fields(OperationStarted)] == correlated
    assert [field.name for field in fields(OperationSucceeded)] == correlated
    assert [field.name for field in fields(OperationFailed)] == [*correlated, "error_code"]


class _DuckIdentity:
    entry_point = 1
    total_words = 2
    image_crc32 = 3


@pytest.mark.parametrize("event_type", (OperationStarted, OperationSucceeded))
@pytest.mark.parametrize(
    ("operation_type", "identity"),
    (
        (RuntimeOperationType.ERASE, None),
        (RuntimeOperationType.ERASE, FLASH_ID),
        (RuntimeOperationType.PROGRAM, FLASH_ID),
        (RuntimeOperationType.VERIFY, FLASH_ID),
        (RuntimeOperationType.RAM_LOAD, RAM_ID),
        (RuntimeOperationType.RAM_CRC, RAM_ID),
    ),
)
def test_operation_events_accept_only_matching_canonical_identity(
    event_type, operation_type, identity
) -> None:
    event = event_type(
        "operation", operation_type, RuntimeCpuId.CPU1, ConnectionGeneration(1), identity
    )
    assert event.image_identity is identity


@pytest.mark.parametrize("event_type", (OperationStarted, OperationSucceeded))
@pytest.mark.parametrize(
    ("operation_type", "identity"),
    (
        (RuntimeOperationType.ERASE, RAM_ID),
        (RuntimeOperationType.PROGRAM, None),
        (RuntimeOperationType.PROGRAM, RAM_ID),
        (RuntimeOperationType.VERIFY, RAM_ID),
        (RuntimeOperationType.RAM_LOAD, FLASH_ID),
        (RuntimeOperationType.RAM_CRC, None),
        (RuntimeOperationType.RAM_CRC, {"image_crc32": 1}),
        (RuntimeOperationType.RAM_CRC, (1, 2, 3)),
        (RuntimeOperationType.RAM_CRC, _DuckIdentity()),
    ),
)
def test_operation_events_reject_mismatched_or_noncanonical_identity(
    event_type, operation_type, identity
) -> None:
    with pytest.raises(TypeError):
        event_type(
            "operation", operation_type, RuntimeCpuId.CPU1, ConnectionGeneration(1), identity
        )


@pytest.mark.parametrize(
    ("operation_type", "identity"),
    (
        (RuntimeOperationType.ERASE, None),
        (RuntimeOperationType.PROGRAM, FLASH_ID),
        (RuntimeOperationType.VERIFY, FLASH_ID),
        (RuntimeOperationType.RAM_LOAD, RAM_ID),
        (RuntimeOperationType.RAM_CRC, RAM_ID),
    ),
)
def test_operation_failed_uses_same_identity_rules(operation_type, identity) -> None:
    event = OperationFailed(
        "operation",
        operation_type,
        RuntimeCpuId.CPU1,
        ConnectionGeneration(1),
        identity,
        "FAILED",
    )
    assert event.error_code == "FAILED"


@pytest.mark.parametrize("error_code", ("", None, 1, True))
def test_operation_failed_requires_exact_nonempty_error_code(error_code) -> None:
    with pytest.raises((TypeError, ValueError)):
        OperationFailed(
            "operation",
            RuntimeOperationType.ERASE,
            RuntimeCpuId.CPU1,
            ConnectionGeneration(1),
            None,
            error_code,
        )


def _seed_evidence_store() -> RuntimeStateStore:
    store = RuntimeStateStore()
    generation = ConnectionGeneration(1)
    for cpu_id in RuntimeCpuId:
        store.replace_target_resource(
            cpu_id,
            replace(
                TargetResourceState(cpu_id),
                program_image_path=f"{cpu_id.value}.txt",
                program_image_summary=FlashImageSummary(FLASH_ID, 3),
                program_image_parse_status=ImageParseStatus.READY,
                ram_image_path=f"{cpu_id.value}-ram.txt",
                ram_image_summary=RamImageSummary(RAM_ID),
                ram_image_parse_status=ImageParseStatus.READY,
                custom_sector_mask=5,
                verify_evidence=VerifyEvidence(cpu_id, generation, FLASH_ID, f"v-{cpu_id.value}"),
                ram_crc_evidence=RamCrcEvidence(
                    cpu_id,
                    generation,
                    RAM_ID,
                    RAM_ID.entry_point,
                    RAM_ID.image_crc32,
                    f"r-{cpu_id.value}",
                ),
            ),
        )
    return store


@pytest.mark.parametrize("cpu_id", tuple(RuntimeCpuId))
@pytest.mark.parametrize("operation_type", tuple(RuntimeOperationType))
def test_operation_start_invalidates_only_selected_cpu_evidence_type(
    cpu_id, operation_type
) -> None:
    store = _seed_evidence_store()
    before = store.snapshot().target_resources
    flash = operation_type in {
        RuntimeOperationType.ERASE,
        RuntimeOperationType.PROGRAM,
        RuntimeOperationType.VERIFY,
    }
    identity = None if operation_type is RuntimeOperationType.ERASE else FLASH_ID if flash else RAM_ID
    result = DomainEventDispatcher(store).dispatch(
        OperationStarted("operation", operation_type, cpu_id, ConnectionGeneration(1), identity)
    )
    changed = result.snapshot.target_resources[cpu_id]
    assert (changed.verify_evidence is None) is flash
    assert (changed.ram_crc_evidence is None) is not flash
    other_cpu = RuntimeCpuId.CPU2 if cpu_id is RuntimeCpuId.CPU1 else RuntimeCpuId.CPU1
    assert result.snapshot.target_resources[other_cpu] == before[other_cpu]
    assert replace(
        changed,
        verify_evidence=before[cpu_id].verify_evidence,
        ram_crc_evidence=before[cpu_id].ram_crc_evidence,
    ) == before[cpu_id]
    assert DomainEventDispatcher(store).dispatch(
        OperationStarted("again", operation_type, cpu_id, ConnectionGeneration(1), identity)
    ).snapshot.target_resources[cpu_id] == changed


@pytest.mark.parametrize("status", (ImageParseStatus.EMPTY, ImageParseStatus.PARSING, ImageParseStatus.ERROR))
@pytest.mark.parametrize("ram", (False, True))
def test_nonready_image_states_preserve_evidence(status, ram) -> None:
    store = _seed_evidence_store()
    event_type = RamImageChanged if ram else ProgramImageChanged
    args = (RuntimeCpuId.CPU1, "image.txt" if status is not ImageParseStatus.EMPTY else "", status)
    if status is ImageParseStatus.ERROR:
        event = event_type(*args, parse_error="failed")
    else:
        event = event_type(*args)
    before = store.snapshot().target_resources[RuntimeCpuId.CPU1]
    after = DomainEventDispatcher(store).dispatch(event).snapshot.target_resources[RuntimeCpuId.CPU1]
    assert after.verify_evidence == before.verify_evidence
    assert after.ram_crc_evidence == before.ram_crc_evidence


@pytest.mark.parametrize("ram", (False, True))
@pytest.mark.parametrize("same_identity", (True, False))
def test_ready_image_identity_preserves_same_and_invalidates_changed(ram, same_identity) -> None:
    store = _seed_evidence_store()
    if ram:
        identity = RAM_ID if same_identity else OTHER_RAM_ID
        event = RamImageChanged(
            RuntimeCpuId.CPU1, "renamed.txt", ImageParseStatus.READY, RamImageSummary(identity)
        )
    else:
        identity = FLASH_ID if same_identity else OTHER_FLASH_ID
        event = ProgramImageChanged(
            RuntimeCpuId.CPU1, "renamed.txt", ImageParseStatus.READY, FlashImageSummary(identity, 9)
        )
    before = store.snapshot().target_resources
    after = DomainEventDispatcher(store).dispatch(event).snapshot.target_resources
    evidence = after[RuntimeCpuId.CPU1].ram_crc_evidence if ram else after[RuntimeCpuId.CPU1].verify_evidence
    assert (evidence is not None) is same_identity
    assert after[RuntimeCpuId.CPU2] == before[RuntimeCpuId.CPU2]


@pytest.mark.parametrize(
    "identity",
    (
        replace(FLASH_ID, entry_point=FLASH_ID.entry_point + 1),
        replace(FLASH_ID, image_size_words=FLASH_ID.image_size_words + 1),
        replace(FLASH_ID, image_crc32=FLASH_ID.image_crc32 + 1),
        replace(FLASH_ID, app_end=FLASH_ID.app_end + 1),
    ),
)
def test_each_complete_program_identity_change_invalidates_verify(identity) -> None:
    store = _seed_evidence_store()
    event = ProgramImageChanged(
        RuntimeCpuId.CPU1, "same.txt", ImageParseStatus.READY, FlashImageSummary(identity, 3)
    )
    state = DomainEventDispatcher(store).dispatch(event).snapshot.target_resources[RuntimeCpuId.CPU1]
    assert state.verify_evidence is None and state.ram_crc_evidence is not None


@pytest.mark.parametrize(
    "identity",
    (
        replace(RAM_ID, entry_point=RAM_ID.entry_point + 1),
        replace(RAM_ID, total_words=RAM_ID.total_words + 1),
        replace(RAM_ID, image_crc32=RAM_ID.image_crc32 + 1),
    ),
)
def test_each_complete_ram_identity_change_invalidates_crc(identity) -> None:
    store = _seed_evidence_store()
    event = RamImageChanged(
        RuntimeCpuId.CPU1, "same.txt", ImageParseStatus.READY, RamImageSummary(identity)
    )
    state = DomainEventDispatcher(store).dispatch(event).snapshot.target_resources[RuntimeCpuId.CPU1]
    assert state.ram_crc_evidence is None and state.verify_evidence is not None


@pytest.mark.parametrize(
    "event",
    (
        ConnectionOpened(_info()),
        ConnectionGenerationChanged(ConnectionGeneration(0), ConnectionGeneration(1)),
        ActiveTargetChanged(RuntimeCpuId.CPU1),
        ActiveTargetChanged(RuntimeCpuId.CPU2),
        ActiveTargetChanged(None),
    ),
)
def test_connection_generation_and_target_events_clear_all_evidence_preserving_images(event) -> None:
    store = _seed_evidence_store()
    before = store.snapshot().target_resources
    after = DomainEventDispatcher(store).dispatch(event).snapshot.target_resources
    for cpu_id in RuntimeCpuId:
        assert after[cpu_id].verify_evidence is None
        assert after[cpu_id].ram_crc_evidence is None
        assert replace(
            after[cpu_id],
            verify_evidence=before[cpu_id].verify_evidence,
            ram_crc_evidence=before[cpu_id].ram_crc_evidence,
        ) == before[cpu_id]


def test_connection_close_and_session_clear_all_evidence() -> None:
    store = RuntimeStateStore()
    dispatcher = DomainEventDispatcher(store)
    dispatcher.dispatch(ConnectionOpened(_info()))
    seeded = _seed_evidence_store().snapshot().target_resources
    for cpu_id in RuntimeCpuId:
        store.replace_target_resource(cpu_id, seeded[cpu_id])
    closed = dispatcher.dispatch(
        ConnectionClosed("connection-1", ConnectionGeneration(1))
    ).snapshot
    assert all(
        resource.verify_evidence is None and resource.ram_crc_evidence is None
        for resource in closed.target_resources.values()
    )
    for cpu_id in RuntimeCpuId:
        store.replace_target_resource(cpu_id, seeded[cpu_id])
    session = dispatcher.dispatch(SessionChanged()).snapshot
    assert session.target_resources == {
        cpu_id: TargetResourceState(cpu_id) for cpu_id in RuntimeCpuId
    }
