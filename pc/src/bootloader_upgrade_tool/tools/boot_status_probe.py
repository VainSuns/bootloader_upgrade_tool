"""Read-only boot status and policy preview CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from ..core import ProtocolClient
from ..io import SerialIoDevice, SimulatorIoDevice
from ..protocol.constants import ServiceState
from ..protocol.models import MetadataSummary, ServiceStatus


APP_START = 0x082400
APP_END_EXCLUSIVE = 0x0C0000
POLICY_NAME = "IMAGE_VALID_BOOT_ATTEMPT_APP_CONFIRMED"


@dataclass(frozen=True, slots=True)
class BootPolicyPreview:
    automatic_boot_allowed: bool
    reason: str
    policy: str = POLICY_NAME


@dataclass(frozen=True, slots=True)
class FlashServicePreview:
    ready: str
    reason: str


@dataclass(frozen=True, slots=True)
class BootStatusResult:
    metadata: MetadataSummary
    preview: BootPolicyPreview
    flash_service: FlashServicePreview

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": asdict(self.metadata),
            "preview": asdict(self.preview),
            "flash_service": asdict(self.flash_service),
        }


def _has_image_valid(summary: MetadataSummary) -> bool:
    return bool(
        summary.metadata_valid
        and summary.entry_point != 0
        and summary.image_size_words != 0
        and summary.image_crc32 != 0
    )


def _bad_entry(summary: MetadataSummary) -> bool:
    return not (
        APP_START <= summary.entry_point < APP_END_EXCLUSIVE
        and (summary.entry_point % 8) == 0
    )


def preview_flash_service(status: ServiceStatus | None) -> FlashServicePreview:
    if status is None:
        return FlashServicePreview("unknown", "NOT_CHECKED")
    if status.service_state == ServiceState.ATTACHED:
        return FlashServicePreview("yes", "ATTACHED")
    if status.service_state == ServiceState.DETACHED:
        return FlashServicePreview("no", "DETACHED")
    if status.service_state == ServiceState.ERROR:
        return FlashServicePreview("no", "ERROR")
    return FlashServicePreview("no", "RAM_LOADED")


def preview_boot_policy(
    summary: MetadataSummary,
    flash_service: FlashServicePreview | None = None,
) -> BootPolicyPreview:
    service_ready = flash_service is not None and flash_service.ready == "yes"
    if not summary.metadata_valid:
        if summary.state == 0:
            return BootPolicyPreview(False, "NO_IMAGE_VALID")
        return BootPolicyPreview(False, "METADATA_INVALID")
    if not _has_image_valid(summary):
        return BootPolicyPreview(False, "NO_IMAGE_VALID")
    if _bad_entry(summary):
        return BootPolicyPreview(False, "BAD_ENTRY")
    if summary.boot_attempt_count == 0 and not summary.app_confirmed:
        return BootPolicyPreview(service_ready, "RUN_FIRST_TRIAL" if service_ready else "SERVICE_NOT_READY")
    if summary.boot_attempt_count > 0 and not summary.app_confirmed:
        return BootPolicyPreview(False, "WAIT_APP_CONFIRM")
    if summary.boot_attempt_count > 0 and summary.app_confirmed:
        return BootPolicyPreview(True, "APP_CONFIRMED")
    return BootPolicyPreview(False, "METADATA_INVALID")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read boot status and preview boot policy")
    parser.add_argument("--transport", choices=("simulator", "serial"), required=True)
    parser.add_argument("--port", help="COM port for serial transport")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--json", action="store_true")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.transport == "serial" and not args.port:
        parser.error("--port is required when --transport serial")
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")


def create_device(args: argparse.Namespace):
    if args.transport == "simulator":
        return SimulatorIoDevice()
    return SerialIoDevice(args.port, baudrate=args.baud)


def collect_boot_status(client: ProtocolClient, *, timeout_ms: int = 5000) -> BootStatusResult:
    summary = client.get_metadata_summary(timeout_ms=timeout_ms)
    try:
        service_status = client.get_service_status(timeout_ms=timeout_ms)
    except Exception:
        service_status = None
    flash_service = preview_flash_service(service_status)
    return BootStatusResult(summary, preview_boot_policy(summary, flash_service), flash_service)


def _yes(value: bool | int) -> str:
    return "yes" if bool(value) else "no"


def _state_name(value: int) -> str:
    names = {0: "EMPTY", 1: "VALID", 2: "INVALID", 3: "DUPLICATE_SEQUENCE"}
    return names.get(value, f"0x{value:04X}")


def format_text(result: BootStatusResult) -> str:
    summary = result.metadata
    preview = result.preview
    return "\n".join(
        (
            "PASS: boot status read",
            "",
            "Metadata:",
            f"  valid: {_yes(summary.metadata_valid)}",
            f"  state: {_state_name(summary.state)}",
            f"  image valid: {_yes(_has_image_valid(summary))}",
            f"  boot attempt: {_yes(summary.boot_attempt_count > 0)}",
            f"  app confirmed: {_yes(summary.app_confirmed)}",
            f"  boot attempts: {summary.boot_attempt_count} / {summary.boot_attempt_limit}",
            f"  next record index: {summary.next_record_index}",
            "",
            "App:",
            f"  entry point: 0x{summary.entry_point:08X}",
            f"  image CRC32: 0x{summary.image_crc32:08X}",
            f"  image words: {summary.image_size_words}",
            (
                "  version: "
                f"{summary.app_version_major}.{summary.app_version_minor}."
                f"{summary.app_version_patch}.{summary.app_version_build}"
            ),
            f"  target: device 0x{summary.target_device_id:04X} CPU{summary.target_cpu_id}",
            "",
            "Flash service:",
            f"  ready: {result.flash_service.ready}",
            f"  reason: {result.flash_service.reason}",
            "",
            "Decision preview:",
            f"  automatic boot allowed: {_yes(preview.automatic_boot_allowed)}",
            f"  reason: {preview.reason}",
            f"  policy: {preview.policy}",
        )
    )


def format_json(result: BootStatusResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True)


def run(args: argparse.Namespace) -> BootStatusResult:
    device = create_device(args)
    client = ProtocolClient(
        device,
        default_timeout_ms=args.timeout_ms,
        clear_input_before_request=False,
    )
    device.open()
    try:
        return collect_boot_status(client, timeout_ms=args.timeout_ms)
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
