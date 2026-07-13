"""Connection-bound requests and immutable results for read-only status tasks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, IntEnum

from ..operations import OperationResult
from ..protocol.boot_protocol_client import ProtocolInfo
from ..protocol.models import DeviceInfo, ErrorDetail, MetadataSummary
from .runtime_models import (
    CompletionPolicy,
    ProgressMode,
    TaskConnectionRequirement,
    TaskPlan,
    TaskStepPlan,
)


class LoadedImageMatch(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NO_PREPARED_IMAGE = "no_prepared_image"
    NO_VALID_TARGET_IMAGE = "no_valid_target_image"


class MetadataScanState(IntEnum):
    EMPTY = 0
    VALID = 1
    INVALID = 2
    DUPLICATE_SEQUENCE = 3


def _status_plan(task_id: str, title: str, step_id: str) -> TaskPlan:
    return TaskPlan(
        task_id,
        title,
        (TaskStepPlan(step_id, title, ProgressMode.INDETERMINATE),),
        TaskConnectionRequirement.CONNECTED,
        False,
        CompletionPolicy.AUTO_CLOSE_ON_CLEAN_SUCCESS,
    )


@dataclass(frozen=True, slots=True)
class StatusRequest(ABC):
    """Public base for a status request tied to one live connection."""

    connection_id: str

    def __post_init__(self) -> None:
        connection_id = self.connection_id.strip() if isinstance(self.connection_id, str) else ""
        if not connection_id:
            raise ValueError("connection_id must not be empty")
        object.__setattr__(self, "connection_id", connection_id)

    @abstractmethod
    def create_plan(self, task_id: str) -> TaskPlan:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class MetadataRefreshRequest(StatusRequest):
    automatic: bool = False

    def __post_init__(self) -> None:
        super(MetadataRefreshRequest, self).__post_init__()
        if not isinstance(self.automatic, bool):
            raise TypeError("automatic must be bool")

    def create_plan(self, task_id: str) -> TaskPlan:
        return _status_plan(task_id, "Refresh Metadata", "refresh_metadata")


@dataclass(frozen=True, slots=True)
class DeviceInfoRequest(StatusRequest):
    def create_plan(self, task_id: str) -> TaskPlan:
        return _status_plan(task_id, "Read Device Info", "read_device_info")


@dataclass(frozen=True, slots=True)
class ProtocolInfoRequest(StatusRequest):
    def create_plan(self, task_id: str) -> TaskPlan:
        return _status_plan(task_id, "Read Protocol Info", "read_protocol_info")


@dataclass(frozen=True, slots=True)
class LastErrorRequest(StatusRequest):
    def create_plan(self, task_id: str) -> TaskPlan:
        return _status_plan(task_id, "Get Last Error", "get_last_error")


def _validate_snapshot(connection_id: str, target_key: str, result: OperationResult) -> None:
    if not isinstance(connection_id, str) or not connection_id.strip():
        raise ValueError("connection_id must not be empty")
    if target_key not in {"cpu1", "cpu2"}:
        raise ValueError("target_key must be 'cpu1' or 'cpu2'")
    if not isinstance(result, OperationResult):
        raise TypeError("operation_result must be OperationResult")


@dataclass(frozen=True, slots=True)
class MetadataStatusSnapshot:
    connection_id: str
    target_key: str
    operation_result: OperationResult
    raw_metadata: MetadataSummary
    metadata_valid: bool
    image_valid: bool
    entry_point_valid: bool
    boot_attempt_present: bool
    app_confirmed: bool
    confirmed_bootable: bool
    loaded_image_match: LoadedImageMatch
    automatic: bool

    def __post_init__(self) -> None:
        _validate_snapshot(self.connection_id, self.target_key, self.operation_result)
        if not isinstance(self.raw_metadata, MetadataSummary):
            raise TypeError("raw_metadata must be MetadataSummary")
        if not isinstance(self.loaded_image_match, LoadedImageMatch):
            raise TypeError("loaded_image_match must be LoadedImageMatch")


@dataclass(frozen=True, slots=True)
class DeviceInfoStatusSnapshot:
    connection_id: str
    target_key: str
    operation_result: OperationResult
    device_info: DeviceInfo

    def __post_init__(self) -> None:
        _validate_snapshot(self.connection_id, self.target_key, self.operation_result)
        if not isinstance(self.device_info, DeviceInfo):
            raise TypeError("device_info must be DeviceInfo")


@dataclass(frozen=True, slots=True)
class ProtocolInfoStatusSnapshot:
    connection_id: str
    target_key: str
    operation_result: OperationResult
    protocol_info: ProtocolInfo

    def __post_init__(self) -> None:
        _validate_snapshot(self.connection_id, self.target_key, self.operation_result)
        if not isinstance(self.protocol_info, ProtocolInfo):
            raise TypeError("protocol_info must be ProtocolInfo")


@dataclass(frozen=True, slots=True)
class LastErrorStatusSnapshot:
    connection_id: str
    target_key: str
    operation_result: OperationResult
    last_error: ErrorDetail

    def __post_init__(self) -> None:
        _validate_snapshot(self.connection_id, self.target_key, self.operation_result)
        if not isinstance(self.last_error, ErrorDetail):
            raise TypeError("last_error must be ErrorDetail")


__all__ = [
    "DeviceInfoRequest",
    "DeviceInfoStatusSnapshot",
    "LastErrorRequest",
    "LastErrorStatusSnapshot",
    "LoadedImageMatch",
    "MetadataRefreshRequest",
    "MetadataScanState",
    "MetadataStatusSnapshot",
    "ProtocolInfoRequest",
    "ProtocolInfoStatusSnapshot",
    "StatusRequest",
]
