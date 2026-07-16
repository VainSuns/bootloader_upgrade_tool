"""Atomic Runtime V2 domain-event dispatch and listener publication."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from threading import Lock

from .runtime_v2_events import DomainEvent
from .runtime_v2_models import RuntimeStateStore, RuntimeV2Snapshot
from .runtime_v2_policies import DEFAULT_DOMAIN_POLICIES, DomainPolicy


class DomainTransitionError(RuntimeError):
    def __init__(self, policy_name: str, cause: BaseException) -> None:
        self.policy_name = policy_name
        self.cause = cause
        super().__init__(f"{policy_name} failed: {cause}")


@dataclass(frozen=True, slots=True)
class TransitionListenerFailure:
    listener_name: str
    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class RuntimeTransitionResult:
    source_event: DomainEvent
    derived_events: tuple[DomainEvent, ...]
    snapshot: RuntimeV2Snapshot
    listener_failures: tuple[TransitionListenerFailure, ...] = ()


TransitionListener = Callable[[RuntimeTransitionResult], None]


class DomainEventDispatcher:
    def __init__(
        self,
        store: RuntimeStateStore,
        policies: Iterable[DomainPolicy] = DEFAULT_DOMAIN_POLICIES,
    ) -> None:
        if not isinstance(store, RuntimeStateStore):
            raise TypeError("store must be RuntimeStateStore")
        self._store = store
        self._policies = tuple(policies)
        if any(not isinstance(policy, DomainPolicy) for policy in self._policies):
            raise TypeError("policies must contain only DomainPolicy instances")
        self._listener_lock = Lock()
        self._listeners: list[TransitionListener] = []

    @property
    def policies(self) -> tuple[DomainPolicy, ...]:
        return self._policies

    def subscribe(self, listener: TransitionListener) -> None:
        if not callable(listener):
            raise TypeError("listener must be callable")
        with self._listener_lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def unsubscribe(self, listener: TransitionListener) -> None:
        with self._listener_lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def dispatch(self, event: DomainEvent) -> RuntimeTransitionResult:
        if not isinstance(event, DomainEvent):
            raise TypeError("event must be DomainEvent")
        snapshot, derived_events = self._store.transition(event, self._policies)
        result = RuntimeTransitionResult(event, derived_events, snapshot)
        with self._listener_lock:
            listeners = tuple(self._listeners)
        failures = []
        for listener in listeners:
            try:
                listener(result)
            except Exception as exc:
                failures.append(
                    TransitionListenerFailure(
                        getattr(listener, "__qualname__", type(listener).__qualname__),
                        type(exc).__name__,
                        str(exc),
                    )
                )
        return replace(result, listener_failures=tuple(failures)) if failures else result


__all__ = [
    "DomainEventDispatcher",
    "DomainTransitionError",
    "RuntimeTransitionResult",
    "TransitionListenerFailure",
]
