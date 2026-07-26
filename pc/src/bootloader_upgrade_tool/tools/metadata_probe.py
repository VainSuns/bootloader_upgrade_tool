"""Read-only metadata regression probe CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Any, Mapping, Sequence

from ..operations import (
    MemoryReadRequest,
    OperationContext,
    OperationResult,
    discover_connected_target,
    get_metadata_summary,
    memory_read,
)
from ..protocol.constants import BootSlot, MetadataRecordType
from ..protocol.models import DeviceInfo, MetadataSummary
from ..session import UpgradeSession, UpgradeSessionConfig
from ..targets import TargetProfile
from ..transport import SerialTransport, SerialTransportConfig, TransportOpenStatus


DEFAULT_METADATA_ADDRESS = 0x082000


@dataclass(frozen=True, slots=True)
class ProbeResult:
    device: dict[str, Any]
    metadata_summary: dict[str, Any]
    raw_metadata: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_u32(value: str) -> int:
    result = int(value, 0)
    if result < 0 or result > 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("value must fit uint32")
    return result


def enum_name(enum_type: type[IntEnum], value: int, *, zero_name: str = "NONE") -> str:
    if value == 0:
        return zero_name
    try:
        return enum_type(value).name
    except ValueError:
        return f"0x{value:04X}"


def device_to_dict(info: DeviceInfo) -> dict[str, Any]:
    return {
        "target_device_id": info.device_id,
        "target_cpu_id": info.cpu_id,
        "protocol_version": info.protocol_ver,
        "max_payload_words": info.max_payload_words,
        "max_data_words": info.max_data_words,
        "feature_flags": info.feature_flags,
        "revision_id": info.revision_id,
        "uid_unique": info.uid_unique,
    }


def metadata_summary_to_dict(summary: MetadataSummary | Mapping[str, Any]) -> dict[str, Any]:
    def value(name: str) -> Any:
        return summary[name] if isinstance(summary, Mapping) else getattr(summary, name)

    return {
        "metadata_valid": bool(value("metadata_valid")),
        "metadata_valid_value": value("metadata_valid"),
        "active_slot": enum_name(BootSlot, value("active_slot")),
        "active_slot_value": value("active_slot"),
        "latest_record_type": enum_name(MetadataRecordType, value("latest_record_type")),
        "latest_record_type_value": value("latest_record_type"),
        "boot_attempt_count": value("boot_attempt_count"),
        "boot_attempt_limit": value("boot_attempt_limit"),
        "app_confirmed": bool(value("app_confirmed")),
        "app_confirmed_value": value("app_confirmed"),
        "entry_point": value("entry_point"),
        "image_size_words": value("image_size_words"),
        "image_crc32": value("image_crc32"),
        "app_version": (
            f"{value('app_version_major')}."
            f"{value('app_version_minor')}."
            f"{value('app_version_patch')}."
            f"{value('app_version_build')}"
        ),
        "app_version_major": value("app_version_major"),
        "app_version_minor": value("app_version_minor"),
        "app_version_patch": value("app_version_patch"),
        "app_version_build": value("app_version_build"),
        "target_device_id": value("target_device_id"),
        "target_cpu_id": value("target_cpu_id"),
        "state": value("state"),
        "valid_record_count": value("valid_record_count"),
        "invalid_record_count": value("invalid_record_count"),
        "erased_record_count": value("erased_record_count"),
        "free_record_count": value("free_record_count"),
        "next_record_index": value("next_record_index"),
    }


class ProbeOperationError(RuntimeError):
    def __init__(self, result: OperationResult) -> None:
        error = result.error
        code = "UNKNOWN" if error is None else error.code
        message = "operation failed" if error is None else error.message
        super().__init__(
            f"operation={result.operation} stage={result.stage} code={code}: {message}"
        )
        self.operation = result.operation
        self.stage = result.stage
        self.code = code
        self.message = message


def _require_success(result: OperationResult) -> OperationResult:
    if not result.ok:
        raise ProbeOperationError(result)
    return result


def collect_probe_result(
    session: UpgradeSession,
    target: TargetProfile,
    *,
    metadata_address: int = DEFAULT_METADATA_ADDRESS,
    raw_words: int = 0,
) -> ProbeResult:
    if raw_words < 0:
        raise ValueError("raw_words must be non-negative")

    device = session.client.device_info
    if not isinstance(device, DeviceInfo):
        raise RuntimeError("target discovery completed without cached DeviceInfo")
    ctx = OperationContext(session=session, target=target)
    summary_result = _require_success(get_metadata_summary(ctx))
    raw_metadata = None
    if raw_words:
        read_result = _require_success(
            memory_read(ctx, MemoryReadRequest(metadata_address, raw_words))
        )
        raw_metadata = {
            "address": metadata_address,
            "words": list(read_result.details["words"]),
        }
    return ProbeResult(
        device_to_dict(device),
        metadata_summary_to_dict(summary_result.summary),
        raw_metadata,
    )


def format_json(result: ProbeResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)


def _hex32(value: int) -> str:
    return f"0x{value:08X}"


def _hex16(value: int) -> str:
    return f"0x{value:04X}"


def _format_raw_words(address: int, words: Sequence[int]) -> list[str]:
    lines: list[str] = []
    for offset in range(0, len(words), 8):
        chunk = words[offset : offset + 8]
        rendered = " ".join(_hex16(word) for word in chunk)
        lines.append(f"  {_hex32(address + offset)}: {rendered}")
    return lines


def format_text(result: ProbeResult) -> str:
    device = result.device
    summary = result.metadata_summary
    lines = [
        "Device:",
        f"  target_device_id: {_hex16(device['target_device_id'])}",
        f"  target_cpu_id: {device['target_cpu_id']}",
        f"  protocol_version: {_hex16(device['protocol_version'])}",
        f"  max_payload_words: {device['max_payload_words']}",
        f"  max_data_words: {device['max_data_words']}",
        "",
        "Metadata Summary:",
        f"  metadata_valid: {summary['metadata_valid_value']}",
        f"  active_slot: {summary['active_slot']}",
        f"  latest_record_type: {summary['latest_record_type']}",
        f"  boot_attempt_count: {summary['boot_attempt_count']}",
        f"  boot_attempt_limit: {summary['boot_attempt_limit']}",
        f"  app_confirmed: {summary['app_confirmed_value']}",
        f"  entry_point: {_hex32(summary['entry_point'])}",
        f"  image_size_words: {summary['image_size_words']}",
        f"  image_crc32: {_hex32(summary['image_crc32'])}",
        f"  app_version: {summary['app_version']}",
        f"  target_device_id: {_hex16(summary['target_device_id'])}",
        f"  target_cpu_id: {summary['target_cpu_id']}",
        f"  state: {summary['state']}",
        f"  valid_record_count: {summary['valid_record_count']}",
        f"  invalid_record_count: {summary['invalid_record_count']}",
        f"  erased_record_count: {summary['erased_record_count']}",
        f"  free_record_count: {summary['free_record_count']}",
        f"  next_record_index: {summary['next_record_index']}",
    ]
    if result.raw_metadata is not None:
        lines.extend(["", "Raw Metadata:"])
        lines.extend(
            _format_raw_words(
                result.raw_metadata["address"],
                result.raw_metadata["words"],
            )
        )
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only boot metadata probe")
    parser.add_argument("--port", required=True, help="COM port")
    parser.add_argument("--baud", type=int, default=9600, help="serial baud rate")
    parser.add_argument("--json", action="store_true", help="print JSON output")
    parser.add_argument(
        "--raw-words",
        type=int,
        default=0,
        help="number of raw metadata words to read",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="request timeout in milliseconds",
    )
    parser.add_argument(
        "--metadata-address",
        type=parse_u32,
        default=DEFAULT_METADATA_ADDRESS,
        help="metadata base address used for optional raw read",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.raw_words < 0:
        parser.error("--raw-words must be non-negative")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")


def run(args: argparse.Namespace) -> ProbeResult:
    transport = SerialTransport(
        SerialTransportConfig(
            port=args.port,
            baudrate=args.baud,
            tx_timeout_ms=args.timeout_ms,
            rx_timeout_ms=args.timeout_ms,
            autobaud_timeout_ms=args.timeout_ms,
        )
    )
    session = UpgradeSession(UpgradeSessionConfig(transport))
    try:
        open_result = session.connect()
        if open_result.status is not TransportOpenStatus.OPENED:
            raise RuntimeError(f"serial connection cancelled at {open_result.stage}")
        discovery = discover_connected_target(session)
        _require_success(discovery.result)
        if discovery.discovered_target is None:
            raise RuntimeError("target discovery succeeded without a TargetProfile")
        return collect_probe_result(
            session,
            discovery.discovered_target.target_profile,
            metadata_address=args.metadata_address,
            raw_words=args.raw_words,
        )
    finally:
        session.disconnect()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    try:
        result = run(args)
    except Exception as exc:
        print(f"FAIL: {exc!r}")
        return 1
    print(format_json(result) if args.json else format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
