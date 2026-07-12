"""Immutable GUI requests for the persistent SCI session."""

from __future__ import annotations

from dataclasses import dataclass

from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class SerialConnectRequest:
    port: str
    baudrate: int
    tx_timeout_ms: int
    rx_timeout_ms: int
    autobaud_timeout_ms: int

    def __post_init__(self) -> None:
        port = self.port.strip() if isinstance(self.port, str) else ""
        if not port:
            raise ValueError("port must not be empty")
        object.__setattr__(self, "port", port)
        for name in (
            "baudrate",
            "tx_timeout_ms",
            "rx_timeout_ms",
            "autobaud_timeout_ms",
        ):
            _positive_int(getattr(self, name), name)

    def create_plan(self, task_id: str) -> TaskPlan:
        return TaskPlan(
            task_id,
            "Connect SCI / RS232",
            (
                TaskStepPlan("connect_sci", "Connect SCI / RS232", ProgressMode.INDETERMINATE),
                TaskStepPlan("identify_target", "Identify Connected Target", ProgressMode.INDETERMINATE),
            ),
            TaskConnectionRequirement.NONE,
            False,
            CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS,
        )


@dataclass(frozen=True, slots=True)
class SerialDisconnectRequest:
    def create_plan(self, task_id: str) -> TaskPlan:
        return TaskPlan(
            task_id,
            "Disconnect SCI / RS232",
            (TaskStepPlan("disconnect_sci", "Disconnect SCI / RS232", ProgressMode.INDETERMINATE),),
            TaskConnectionRequirement.CONNECTED,
            False,
            CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS,
        )


__all__ = ["SerialConnectRequest", "SerialDisconnectRequest"]
