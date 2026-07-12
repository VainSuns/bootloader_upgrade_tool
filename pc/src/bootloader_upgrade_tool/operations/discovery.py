"""Public target discovery operation."""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol.constants import CpuId, DeviceId
from ..protocol.models import DeviceInfo
from ..session import UpgradeSession
from ..targets import CPU1_PROFILE, CPU2_PROFILE, DISCOVERY_PROFILE, TargetProfile
from .context import OperationContext
from .results import OperationErrorInfo, OperationResult
from .status_ops import get_device_info

DISCOVERY_OPERATION = "discover_connected_target"
DISCOVERY_STAGE = "RESOLVE_TARGET"


@dataclass(frozen=True, slots=True)
class DiscoveredTarget:
    device_info: DeviceInfo
    target_profile: TargetProfile
    target_key: str

    def __post_init__(self) -> None:
        if self.target_key not in {"cpu1", "cpu2"}:
            raise ValueError("target_key must be 'cpu1' or 'cpu2'")
        if int(self.target_profile.cpu_id) != int(self.device_info.cpu_id):
            raise ValueError("target profile CPU does not match DeviceInfo")


@dataclass(frozen=True, slots=True)
class TargetDiscoveryOutcome:
    result: OperationResult
    discovered_target: DiscoveredTarget | None

    def __post_init__(self) -> None:
        if self.result.ok != (self.discovered_target is not None):
            raise ValueError("discovery result and target must agree")


def discover_connected_target(session: UpgradeSession) -> TargetDiscoveryOutcome:
    """Read DeviceInfo once and resolve the connected CPU in the operation layer."""

    ctx = OperationContext(session=session, target=DISCOVERY_PROFILE)
    result = get_device_info(ctx)
    if not result.ok:
        return TargetDiscoveryOutcome(result, None)

    device_info = session.client.device_info
    if not isinstance(device_info, DeviceInfo):
        raise RuntimeError("get_device_info succeeded without typed DeviceInfo")

    if int(device_info.device_id) != int(DeviceId.F28377D):
        return TargetDiscoveryOutcome(
            _discovery_failure(
                "UNSUPPORTED_DEVICE",
                "Connected device is not a supported TMS320F28377D",
                {
                    "actual_device_id": int(device_info.device_id),
                    "expected_device_id": int(DeviceId.F28377D),
                },
            ),
            None,
        )

    if int(device_info.cpu_id) == int(CpuId.CPU1):
        profile, key = CPU1_PROFILE, "cpu1"
    elif int(device_info.cpu_id) == int(CpuId.CPU2):
        profile, key = CPU2_PROFILE, "cpu2"
    else:
        return TargetDiscoveryOutcome(
            _discovery_failure(
                "UNKNOWN_CPU_ID",
                "Connected device reported an unknown CPU ID",
                {
                    "actual_cpu_id": int(device_info.cpu_id),
                    "expected_cpu_ids": [int(CpuId.CPU1), int(CpuId.CPU2)],
                },
            ),
            None,
        )

    discovered = DiscoveredTarget(device_info, profile, key)
    return TargetDiscoveryOutcome(
        OperationResult(
            True,
            DISCOVERY_OPERATION,
            DISCOVERY_PROFILE.name,
            DISCOVERY_STAGE,
            {
                "device_id": int(device_info.device_id),
                "cpu_id": int(device_info.cpu_id),
                "target_key": key,
            },
        ),
        discovered,
    )


def _discovery_failure(code: str, message: str, details: dict[str, object]) -> OperationResult:
    return OperationResult(
        False,
        DISCOVERY_OPERATION,
        DISCOVERY_PROFILE.name,
        DISCOVERY_STAGE,
        {},
        error=OperationErrorInfo(code, message, DISCOVERY_STAGE, True, details),
    )


__all__ = [
    "DISCOVERY_OPERATION",
    "DISCOVERY_STAGE",
    "DiscoveredTarget",
    "TargetDiscoveryOutcome",
    "discover_connected_target",
]
