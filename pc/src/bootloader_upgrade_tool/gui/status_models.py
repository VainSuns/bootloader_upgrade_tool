"""Read-only status task requests used by the GUI runtime."""

from __future__ import annotations

from dataclasses import dataclass

from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)

_STATUS_TASKS = {
    "get_device_info": ("Read Device Info", "read_device_info", "Read Device Info"),
    "get_protocol_info": ("Read Protocol Info", "read_protocol_info", "Read Protocol Info"),
    "get_last_error": ("Get Last Error", "get_last_error", "Get Last Error"),
    "get_metadata_summary": ("Refresh Metadata", "refresh_metadata", "Refresh Metadata"),
}


@dataclass(frozen=True, slots=True)
class StatusRequest:
    """A target-neutral read-only operation request."""

    operation: str
    automatic: bool = False

    def __post_init__(self) -> None:
        if self.operation not in _STATUS_TASKS:
            raise ValueError(f"unsupported status operation: {self.operation!r}")
        if not isinstance(self.automatic, bool):
            raise TypeError("automatic must be bool")

    def create_plan(self, task_id: str) -> TaskPlan:
        title, step_id, step_title = _STATUS_TASKS[self.operation]
        return TaskPlan(
            task_id,
            title,
            (TaskStepPlan(step_id, step_title, ProgressMode.INDETERMINATE),),
            TaskConnectionRequirement.CONNECTED,
            False,
            CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS,
        )


@dataclass(frozen=True, slots=True, init=False)
class MetadataRefreshRequest(StatusRequest):
    def __init__(self, automatic: bool = False) -> None:
        object.__setattr__(self, "operation", "get_metadata_summary")
        object.__setattr__(self, "automatic", automatic)
        StatusRequest.__post_init__(self)


@dataclass(frozen=True, slots=True, init=False)
class DeviceInfoRequest(StatusRequest):
    def __init__(self) -> None:
        object.__setattr__(self, "operation", "get_device_info")
        object.__setattr__(self, "automatic", False)
        StatusRequest.__post_init__(self)


@dataclass(frozen=True, slots=True, init=False)
class ProtocolInfoRequest(StatusRequest):
    def __init__(self) -> None:
        object.__setattr__(self, "operation", "get_protocol_info")
        object.__setattr__(self, "automatic", False)
        StatusRequest.__post_init__(self)


@dataclass(frozen=True, slots=True, init=False)
class LastErrorRequest(StatusRequest):
    def __init__(self) -> None:
        object.__setattr__(self, "operation", "get_last_error")
        object.__setattr__(self, "automatic", False)
        StatusRequest.__post_init__(self)


__all__ = [
    "DeviceInfoRequest",
    "LastErrorRequest",
    "MetadataRefreshRequest",
    "ProtocolInfoRequest",
    "StatusRequest",
]
