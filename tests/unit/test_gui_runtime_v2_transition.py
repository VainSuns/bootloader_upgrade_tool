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
    SessionChanged,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration,
    RuntimeCpuId,
    RuntimeStateStore,
    TargetResourceState,
    MemoryRuntimeState,
)
from bootloader_upgrade_tool.gui.runtime_v2_policies import (
    ConnectionGenerationPolicy,
    ConnectionStatePolicy,
    DEFAULT_DOMAIN_POLICIES,
    DomainPolicy,
    SessionChangeBlockedError,
    SessionStatePolicy,
    StaleConnectionEventError,
)
from bootloader_upgrade_tool.gui.runtime_v2_transition import (
    DomainEventDispatcher,
    DomainTransitionError,
)


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
    ProgramImageChanged(RuntimeCpuId.CPU1),
    RamImageChanged(RuntimeCpuId.CPU2),
    ConnectionOpened(_info()),
    ConnectionClosed("connection-1", ConnectionGeneration(1)),
    ConnectionGenerationChanged(ConnectionGeneration(0), ConnectionGeneration(1)),
    OperationStarted("operation"),
    OperationSucceeded("operation", RuntimeCpuId.CPU1, ConnectionGeneration(1)),
    OperationFailed("operation", error_code="FAILED"),
    SessionChanged(),
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
        lambda: ProgramImageChanged("cpu1"),
        lambda: RamImageChanged(None),
        lambda: ConnectionClosed("", ConnectionGeneration()),
        lambda: ConnectionClosed("id", 1),
        lambda: OperationStarted(""),
        lambda: OperationStarted("id", "cpu1"),
        lambda: OperationSucceeded("id", connection_generation=1),
        lambda: OperationFailed("id", error_code=""),
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
    forbidden = {"image", "session", "transport", "client", "qobject", "lock", "callback"}
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
        SessionStatePolicy,
    )
    assert all(not hasattr(policy, "__dict__") for policy in DEFAULT_DOMAIN_POLICIES)


def test_session_change_resets_both_cpu_resources_and_memory_without_changing_generation() -> None:
    store = RuntimeStateStore()
    for cpu in RuntimeCpuId:
        store.replace_target_resource(cpu, replace(TargetResourceState(cpu), program_image_path="old"))
    before = store.snapshot()
    result = DomainEventDispatcher(store).dispatch(SessionChanged())
    assert result.derived_events == ()
    assert result.snapshot.connection_generation == before.connection_generation
    assert result.snapshot.target_resources == {cpu: TargetResourceState(cpu) for cpu in RuntimeCpuId}
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
