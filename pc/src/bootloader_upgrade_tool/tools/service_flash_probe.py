"""Downloaded flash_service_lib Flash erase/program/verify probe tool."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from ..core import ProtocolClient, UpgradeWorkflow
from ..firmware import parse_flash_service_symbols_from_map, patch_flash_service_image, validate_app_firmware_image
from ..io import SerialIoDevice, SimulatorIoDevice
from ..protocol.constants import SERVICE_DESCRIPTOR_WORDS
from .service_attach_probe import _load_image


DEFAULT_SECTOR_MASK = 0x00003FFE


@dataclass(frozen=True, slots=True)
class ServiceFlashProbeResult:
    descriptor_address: int
    api_table_address: int
    crc_patch_address: int
    service_words: int
    service_crc32: int
    service_state: int
    service_major: int
    service_minor: int
    capabilities: int
    app_image: str
    app_entry_point: int
    app_total_words: int
    sector_mask: int
    run: bool
    descriptor_write_order: str = "last"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _uint32(value: str) -> int:
    parsed = int(value, 0)
    if parsed < 0 or parsed > 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("value must fit uint32")
    return parsed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Downloaded flash_service_lib erase/program/verify probe")
    parser.add_argument("--transport", choices=("simulator", "serial"), required=True)
    parser.add_argument("--port", help="COM port for serial transport")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--service-image", required=True, help="flash_service_lib .out or .txt image")
    parser.add_argument("--service-map", required=True, help="flash_service_lib .map path")
    parser.add_argument("--app-image", required=True, help="application .out or .txt image")
    parser.add_argument("--hex2000", help="manual hex2000.exe path or compiler root")
    parser.add_argument("--sector-mask", type=_uint32, default=DEFAULT_SECTOR_MASK)
    parser.add_argument("--autobaud-mode", choices=("always", "skip"), default="always")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.transport == "serial" and not args.port:
        parser.error("--port is required when --transport serial")
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")
    if args.sector_mask == 0:
        parser.error("--sector-mask must be nonzero")


def _device(args: argparse.Namespace):
    return SimulatorIoDevice() if args.transport == "simulator" else SerialIoDevice(args.port, baudrate=args.baud)


def run(args: argparse.Namespace) -> ServiceFlashProbeResult:
    service_image, service_work = _load_image(Path(args.service_image), args.hex2000)
    app_image, app_work = _load_image(Path(args.app_image), args.hex2000)
    try:
        validate_app_firmware_image(app_image)
        symbols = parse_flash_service_symbols_from_map(Path(args.service_map))
        client = ProtocolClient(_device(args), default_timeout_ms=args.timeout_ms, clear_input_before_request=False)
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
            service_image = patch_flash_service_image(
                service_image,
                descriptor_address=symbols.descriptor_address,
                api_table_address=symbols.api_table_address,
                crc_patch_address=symbols.crc_patch_address,
                load_order="descriptor_last",
                descriptor_words=SERVICE_DESCRIPTOR_WORDS,
                max_data_words=client.device_info.max_data_words,
            )
            status = workflow.load_and_attach_service(service_image, symbols.descriptor_address)
            workflow.dfu(args.sector_mask, app_image)
            if args.run:
                workflow.run(app_image)
            return ServiceFlashProbeResult(
                descriptor_address=symbols.descriptor_address,
                api_table_address=symbols.api_table_address,
                crc_patch_address=symbols.crc_patch_address,
                service_words=service_image.total_words,
                service_crc32=status.loaded_image_crc32,
                service_state=status.service_state,
                service_major=status.service_major,
                service_minor=status.service_minor,
                capabilities=status.capabilities,
                app_image=str(args.app_image),
                app_entry_point=app_image.entry_point,
                app_total_words=app_image.total_words,
                sector_mask=args.sector_mask,
                run=args.run,
            )
        finally:
            client.close()
    finally:
        if service_work is not None:
            service_work.cleanup()
        if app_work is not None:
            app_work.cleanup()


def format_text(result: ServiceFlashProbeResult) -> str:
    return "\n".join(
        (
            "PASS: SERVICE_ATTACH + ERASE + PROGRAM + VERIFY completed",
            "",
            "Service:",
            f"Descriptor address: 0x{result.descriptor_address:08X}",
            f"API table address: 0x{result.api_table_address:08X}",
            f"CRC patch address: 0x{result.crc_patch_address:08X}",
            f"Service words: {result.service_words}",
            f"Service CRC32: 0x{result.service_crc32:08X}",
            f"Service state: {result.service_state}",
            f"Service version: {result.service_major}.{result.service_minor}",
            f"Capabilities: 0x{result.capabilities:08X}",
            f"Descriptor write order: {result.descriptor_write_order}",
            "",
            "App:",
            f"Image: {result.app_image}",
            f"Entry point: 0x{result.app_entry_point:08X}",
            f"Total words: {result.app_total_words}",
            f"Sector mask: 0x{result.sector_mask:08X}",
            "Program/Verify: PASS",
            "Metadata IMAGE_VALID: PASS",
            f"Run: {'PASS' if result.run else 'SKIPPED'}",
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
