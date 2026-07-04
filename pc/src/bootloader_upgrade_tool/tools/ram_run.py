"""Load, CRC-check, and run a RAM image through the bootloader protocol."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from ..core import ProtocolClient, UpgradeWorkflow
from ..firmware import FirmwareImage, build_firmware_image, run_hex2000
from ..io import SerialIoDevice, SimulatorIoDevice


@dataclass(frozen=True, slots=True)
class RamRunResult:
    entry_point: int
    total_words: int
    crc32: int
    packet_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_image(path: Path, hex2000: str | None) -> tuple[FirmwareImage, tempfile.TemporaryDirectory[str] | None]:
    if path.suffix.lower() == ".txt":
        return build_firmware_image(path, path), None
    work = tempfile.TemporaryDirectory(prefix="ram_run_hex_")
    try:
        output = Path(work.name) / f"{path.stem}.sci8.txt"
        run_hex2000(path, output, hex2000_path=hex2000)
        return build_firmware_image(path, output), work
    except Exception:
        work.cleanup()
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAM_LOAD + RAM_CHECK_CRC + RUN_RAM test tool")
    parser.add_argument("--transport", choices=("simulator", "serial"), required=True)
    parser.add_argument("--image", required=True, help=".out file, or .txt sci8 file for tests")
    parser.add_argument("--port", help="COM port for serial transport")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--hex2000", help="manual hex2000.exe path or compiler root")
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


def run(args: argparse.Namespace) -> RamRunResult:
    image, work = _load_image(Path(args.image), args.hex2000)
    try:
        device = _device(args)
        client = ProtocolClient(device, default_timeout_ms=args.timeout_ms, clear_input_before_request=False)
        workflow = UpgradeWorkflow(client)
        device.open()
        try:
            client.get_device_info(timeout_ms=args.timeout_ms)
            crc = workflow.run_ram_image(image)
            info = client.device_info
            assert info is not None
            packet_count = (image.total_words + info.max_data_words - 1) // info.max_data_words
            return RamRunResult(image.entry_point, image.total_words, crc, packet_count)
        finally:
            client.close()
    finally:
        if work is not None:
            work.cleanup()


def format_text(result: RamRunResult) -> str:
    return "\n".join(
        (
            "PASS: RAM image loaded, CRC checked, and RUN_RAM accepted",
            f"Entry point: 0x{result.entry_point:08X}",
            f"Total words: {result.total_words}",
            f"CRC32: 0x{result.crc32:08X}",
            f"Packet count: {result.packet_count}",
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
