"""Read-only metadata regression probe CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Any, Sequence

from ..core import ProtocolClient
from ..io import SerialIoDevice, SimulatorIoDevice
from ..protocol.constants import BootSlot, MetadataRecordType
from ..protocol.models import DeviceInfo, MetadataSummary


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


def metadata_summary_to_dict(summary: MetadataSummary) -> dict[str, Any]:
    return {
        "metadata_valid": bool(summary.metadata_valid),
        "metadata_valid_value": summary.metadata_valid,
        "active_slot": enum_name(BootSlot, summary.active_slot),
        "active_slot_value": summary.active_slot,
        "latest_record_type": enum_name(MetadataRecordType, summary.latest_record_type),
        "latest_record_type_value": summary.latest_record_type,
        "boot_attempt_count": summary.boot_attempt_count,
        "boot_attempt_limit": summary.boot_attempt_limit,
        "app_confirmed": bool(summary.app_confirmed),
        "app_confirmed_value": summary.app_confirmed,
        "entry_point": summary.entry_point,
        "image_size_words": summary.image_size_words,
        "image_crc32": summary.image_crc32,
        "app_version": (
            f"{summary.app_version_major}."
            f"{summary.app_version_minor}."
            f"{summary.app_version_patch}."
            f"{summary.app_version_build}"
        ),
        "app_version_major": summary.app_version_major,
        "app_version_minor": summary.app_version_minor,
        "app_version_patch": summary.app_version_patch,
        "app_version_build": summary.app_version_build,
        "target_device_id": summary.target_device_id,
        "target_cpu_id": summary.target_cpu_id,
        "state": summary.state,
        "valid_record_count": summary.valid_record_count,
        "invalid_record_count": summary.invalid_record_count,
        "erased_record_count": summary.erased_record_count,
        "free_record_count": summary.free_record_count,
        "next_record_index": summary.next_record_index,
    }


def collect_probe_result(
    client: ProtocolClient,
    *,
    metadata_address: int = DEFAULT_METADATA_ADDRESS,
    raw_words: int = 0,
    timeout_ms: int = 5000,
) -> ProbeResult:
    if raw_words < 0:
        raise ValueError("raw_words must be non-negative")

    client.ping(timeout_ms=timeout_ms)
    device = client.get_device_info(timeout_ms=timeout_ms)
    summary = client.get_metadata_summary(timeout_ms=timeout_ms)
    raw_metadata = None
    if raw_words:
        raw_metadata = {
            "address": metadata_address,
            "words": list(
                client.flash_read_metadata(
                    metadata_address,
                    raw_words,
                    timeout_ms=timeout_ms,
                )
            ),
        }
    return ProbeResult(device_to_dict(device), metadata_summary_to_dict(summary), raw_metadata)


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
    parser.add_argument(
        "--transport",
        choices=("simulator", "serial"),
        required=True,
        help="IO transport to use",
    )
    parser.add_argument("--port", help="COM port for serial transport")
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
    if args.transport == "serial" and not args.port:
        parser.error("--port is required when --transport serial")
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.raw_words < 0:
        parser.error("--raw-words must be non-negative")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")


def create_device(args: argparse.Namespace):
    if args.transport == "simulator":
        return SimulatorIoDevice()
    return SerialIoDevice(args.port, baudrate=args.baud)


def run(args: argparse.Namespace) -> ProbeResult:
    device = create_device(args)
    client = ProtocolClient(
        device,
        default_timeout_ms=args.timeout_ms,
        clear_input_before_request=False,
    )
    device.open()
    try:
        return collect_probe_result(
            client,
            metadata_address=args.metadata_address,
            raw_words=args.raw_words,
            timeout_ms=args.timeout_ms,
        )
    finally:
        client.close()


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
