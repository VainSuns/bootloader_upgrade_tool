"""RAM_LOAD + RAM_CHECK_CRC + SERVICE_ATTACH probe tool."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from ..core import ProtocolClient, UpgradeWorkflow
from ..firmware import (
    FirmwareImage,
    build_firmware_image,
    parse_flash_service_symbols_from_map,
    patch_flash_service_image,
    run_hex2000,
)
from ..io import SerialIoDevice, SimulatorIoDevice


@dataclass(frozen=True, slots=True)
class ServiceAttachProbeResult:
    header_address: int
    total_words: int
    service_state: int
    abi_major: int
    abi_minor: int
    capabilities: int
    loaded_image_crc32: int
    load_order: str = "address"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_image(path: Path, hex2000: str | None) -> tuple[FirmwareImage, tempfile.TemporaryDirectory[str] | None]:
    if path.suffix.lower() == ".txt":
        return build_firmware_image(path, path), None
    work = tempfile.TemporaryDirectory(prefix="service_attach_hex_")
    try:
        output = Path(work.name) / f"{path.stem}.sci8.txt"
        run_hex2000(path, output, hex2000_path=hex2000)
        return build_firmware_image(path, output), work
    except Exception:
        work.cleanup()
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Downloaded flash_service_lib SERVICE_ATTACH probe")
    parser.add_argument("--transport", choices=("simulator", "serial"), required=True)
    parser.add_argument("--image", required=True, help=".out file, or .txt sci8 file for tests")
    parser.add_argument("--map", required=True, help="flash_service_lib_cpu01.map path")
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


def run(args: argparse.Namespace) -> ServiceAttachProbeResult:
    image, work = _load_image(Path(args.image), args.hex2000)
    try:
        symbols = parse_flash_service_symbols_from_map(Path(args.map))
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
                device.open()
                client.get_device_info(timeout_ms=args.timeout_ms)
            if client.device_info is None:
                raise RuntimeError("device information is not available after connect")
            image = patch_flash_service_image(
                image,
                symbols=symbols,
            )
            status = workflow.load_and_attach_service(image, symbols.header_address)
            return ServiceAttachProbeResult(
                header_address=symbols.header_address,
                total_words=image.total_words,
                service_state=status.service_state,
                abi_major=status.abi_major,
                abi_minor=status.abi_minor,
                capabilities=status.capabilities,
                loaded_image_crc32=status.loaded_image_crc32,
            )
        finally:
            client.close()
    finally:
        if work is not None:
            work.cleanup()


def format_text(result: ServiceAttachProbeResult) -> str:
    return "\n".join(
        (
            "PASS: RAM image loaded, CRC checked, and SERVICE_ATTACH accepted",
            f"Header address: 0x{result.header_address:08X}",
            f"Total words: {result.total_words}",
            f"Loaded CRC32: 0x{result.loaded_image_crc32:08X}",
            f"Service state: {result.service_state}",
            f"Service ABI: {result.abi_major}.{result.abi_minor}",
            f"Capabilities: 0x{result.capabilities:08X}",
            f"Load order: {result.load_order}",
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
