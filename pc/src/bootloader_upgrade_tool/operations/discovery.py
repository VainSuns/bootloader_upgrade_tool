"""Public target discovery operation."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.client import ProtocolDecodeError
from ..protocol.constants import DeviceId
from ..protocol.models import DeviceInfo
from ..session import UpgradeSession
from ..targets import DISCOVERY_PROFILE, TargetProfile, target_profile_for_key
from .context import OperationContext
from .results import OperationErrorInfo, OperationResult, failure_result
from .status_ops import get_device_info, get_protocol_info

DISCOVERY_OPERATION = "discover_connected_target"
DISCOVERY_STAGE = "RESOLVE_TARGET"


@dataclass(frozen=True, slots=True)
class DiscoveredTarget:
    device_info: DeviceInfo
    target_profile: TargetProfile
    target_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.device_info, DeviceInfo):
            raise TypeError("device_info must be DeviceInfo")
        if not isinstance(self.target_profile, TargetProfile):
            raise TypeError("target_profile must be TargetProfile")
        if not isinstance(self.target_key, str) or not self.target_key:
            raise ValueError("target_key must be a non-empty string")
        if self.target_key != f"cpu{self.device_info.cpu_id}":
            raise ValueError("target_key does not match DeviceInfo")
        if self.target_profile.cpu_id != self.device_info.cpu_id:
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

    cpu_id = int(device_info.cpu_id)
    target_key = f"cpu{cpu_id}"
    identity_details = {
        "device_id": int(device_info.device_id),
        "actual_cpu_id": cpu_id,
        "attempted_target_key": target_key,
    }
    try:
        profile = target_profile_for_key(target_key)
    except Exception as exc:
        return TargetDiscoveryOutcome(
            _discovery_failure(
                "TARGET_PROFILE_RESOLUTION_FAILED",
                f"Target Profile resolution failed: {exc}",
                identity_details,
            ),
            None,
        )
    if profile is None:
        return TargetDiscoveryOutcome(
            _discovery_failure(
                "UNKNOWN_CPU_ID",
                "Connected device reported an unknown CPU ID",
                identity_details,
            ),
            None,
        )
    if not isinstance(profile, TargetProfile):
        return TargetDiscoveryOutcome(
            _discovery_failure(
                "TARGET_PROFILE_INVALID",
                "Target Profile resolver returned an invalid Profile",
                identity_details,
            ),
            None,
        )
    if profile.cpu_id != device_info.cpu_id:
        return TargetDiscoveryOutcome(
            _discovery_failure(
                "TARGET_PROFILE_MISMATCH",
                "Target Profile CPU does not match DeviceInfo",
                identity_details,
            ),
            None,
        )

    result = get_protocol_info(ctx)
    if not result.ok:
        return TargetDiscoveryOutcome(result, None)
    try:
        device_max_payload_words = device_info.max_payload_words
        protocol_info = session.client.protocol_info
        if protocol_info is None:
            raise ProtocolDecodeError("GET_PROTOCOL_INFO succeeded without cached ProtocolInfo")
        protocol_max_payload_words = protocol_info.max_payload_words
        effective_max_payload_words = session.client.effective_max_payload_words
        effective_max_data_words = session.client.effective_max_data_words
        effective_max_write_data_words = session.client.effective_max_write_data_words
    except Exception as exc:
        return TargetDiscoveryOutcome(
            failure_result(ctx, DISCOVERY_OPERATION, "GET_PROTOCOL_INFO", exc),
            None,
        )

    discovered = DiscoveredTarget(device_info, profile, target_key)
    return TargetDiscoveryOutcome(
        OperationResult(
            True,
            DISCOVERY_OPERATION,
            DISCOVERY_PROFILE.name,
            DISCOVERY_STAGE,
            {
                "device_id": int(device_info.device_id),
                "cpu_id": int(device_info.cpu_id),
                "target_key": target_key,
                "device_max_payload_words": device_max_payload_words,
                "protocol_max_payload_words": protocol_max_payload_words,
                "effective_max_payload_words": effective_max_payload_words,
                "effective_max_data_words": effective_max_data_words,
                "effective_max_write_data_words": effective_max_write_data_words,
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
