"""Attach flash_service_lib and append APP_CONFIRMED metadata."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from ..core import ProtocolClient, UpgradeWorkflow
from ..firmware import parse_flash_service_symbols_from_map, patch_flash_service_image
from ..io import SerialIoDevice, SimulatorIoDevice
from ..protocol.constants import SERVICE_DESCRIPTOR_WORDS
from ..protocol.models import MetadataSummary
from .service_attach_probe import _load_image


@dataclass(frozen=True, slots=True)
class AppConfirmProbeResult:
    metadata: MetadataSummary
    descriptor_address: int
    service_state: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": asdict(self.metadata),
            "descriptor_address": self.descriptor_address,
            "service_state": self.service_state,
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append APP_CONFIRMED metadata record")
    parser.add_argument("--transport", choices=("simulator", "serial"), required=True)
    parser.add_argument("--service-image", required=True)
    parser.add_argument("--service-map", required=True)
    parser.add_argument("--port", help="COM port for serial transport")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--hex2000", help="manual hex2000.exe path or compiler root")
    parser.add_argument("--autobaud-mode", choices=("always", "skip"), default="always")
    parser.add_argument("--json", action="store_true")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.transport == "serial" and not args.port:
        parser.error("--port is required when --transport serial")
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")


def _device(args: argparse.Namespace):
    return SimulatorIoDevice() if args.transport == "simulator" else SerialIoDevice(args.port, baudrate=args.baud)


def run(args: argparse.Namespace) -> AppConfirmProbeResult:
    image, work = _load_image(Path(args.service_image), args.hex2000)
    try:
        symbols = parse_flash_service_symbols_from_map(Path(args.service_map))
        device = _device(args)
        client = ProtocolClient(device, default_timeout_ms=args.timeout_ms, clear_input_before_request=False)
        workflow = UpgradeWorkflow(client)
        try:
            if args.autobaud_mode == "always":
                client.open(
                    wait_slave_timeout_ms=args.timeout_ms,
                    device_info_timeout_ms=args.timeout_ms,
                )
            else:
                client.device.open()
                client.get_device_info(timeout_ms=args.timeout_ms)
            if client.device_info is None:
                raise RuntimeError("device information is not available after connect")
            image = patch_flash_service_image(
                image,
                descriptor_address=symbols.descriptor_address,
                api_table_address=symbols.api_table_address,
                crc_patch_address=symbols.crc_patch_address,
                load_order="descriptor_last",
                descriptor_words=SERVICE_DESCRIPTOR_WORDS,
                max_data_words=client.device_info.max_data_words,
            )
            status = workflow.load_and_attach_service(image, symbols.descriptor_address)
            summary = client.get_metadata_summary(timeout_ms=args.timeout_ms)
            if not summary.metadata_valid:
                raise RuntimeError("IMAGE_VALID metadata is not valid")
            if summary.boot_attempt_count == 0:
                raise RuntimeError("BOOT_ATTEMPT metadata is required before APP_CONFIRMED")
            client.metadata_append_app_confirmed(
                entry_point=summary.entry_point,
                image_size_words=summary.image_size_words,
                image_crc32=summary.image_crc32,
                timeout_ms=args.timeout_ms,
            )
            summary = client.get_metadata_summary(timeout_ms=args.timeout_ms)
            if not summary.app_confirmed:
                raise RuntimeError("APP_CONFIRMED metadata was not written")
            return AppConfirmProbeResult(summary, symbols.descriptor_address, status.service_state)
        finally:
            client.close()
    finally:
        if work is not None:
            work.cleanup()


def _yes(value: bool | int) -> str:
    return "yes" if bool(value) else "no"


def format_text(result: AppConfirmProbeResult) -> str:
    summary = result.metadata
    return "\n".join(
        (
            "PASS: APP_CONFIRMED metadata written",
            "",
            "Metadata:",
            f"  image valid: {_yes(summary.metadata_valid)}",
            f"  boot attempt: {_yes(summary.boot_attempt_count > 0)}",
            f"  app confirmed: {_yes(summary.app_confirmed)}",
            f"  entry point: 0x{summary.entry_point:08X}",
            f"  image CRC32: 0x{summary.image_crc32:08X}",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    try:
        result = run(args)
    except Exception as exc:
        print(f"FAIL: {exc!r}")
        return 1
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True) if args.json else format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
