"""Productized CPU1 RAM App quick-run CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile
from typing import Sequence

from ..core import ProtocolClient, UpgradeWorkflow
from ..firmware import build_firmware_image, run_hex2000
from ..io import SerialIoDevice, SimulatorIoDevice
from . import ram_run
from .common_cli import add_output_args, envelope, normalize_output, print_envelope


TOOL = "cpu1_ram_run"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CPU1 RAM_LOAD + RAM_CHECK_CRC + RUN_RAM tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  cpu1_ram_run --transport simulator --sci8-txt ram.sci8.txt\n"
            "  cpu1_ram_run --transport serial --port COM10 --image ram_app.out --hex2000 <path>\n"
        ),
    )
    parser.add_argument("--transport", choices=("simulator", "serial"), required=True, help="IO backend; serial for hardware, simulator for tests")
    parser.add_argument("--port", help="serial COM port, required with --transport serial")
    parser.add_argument("--baud", type=int, default=9600, help="serial baud rate (default: 9600)")
    parser.add_argument(
        "--autobaud-mode",
        choices=("always", "skip"),
        default="always",
        help="always: perform SCI 'A' autobaud; skip: open serial and query protocol directly",
    )
    parser.add_argument("--timeout-ms", type=int, default=5000, help="request/autobaud timeout in milliseconds")
    parser.add_argument("--image", help="RAM App .out or SCI8 TXT image")
    parser.add_argument("--hex2000", help="hex2000.exe path or TI C2000 compiler root/bin directory")
    parser.add_argument("--sci8-txt", help="existing SCI8 TXT input path")
    parser.add_argument("--hex-file", dest="sci8_txt", help="compatibility alias of --sci8-txt")
    parser.add_argument("--keep-sci8-txt", action="store_true", help="keep generated SCI8 TXT next to the .out file")
    parser.add_argument("--keep-hex", dest="keep_sci8_txt", action="store_true", help="compatibility alias of --keep-sci8-txt")
    add_output_args(parser)
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.transport == "serial" and not args.port:
        parser.error("--port is required when --transport serial")
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")
    if not args.image and not args.sci8_txt:
        parser.error("--image or --sci8-txt is required")


def run_cpu1_ram_run(args: argparse.Namespace) -> ram_run.RamRunResult:
    image_path = Path(args.sci8_txt or args.image)
    work = None
    if image_path.suffix.lower() == ".txt":
        image = build_firmware_image(image_path, image_path)
    elif args.keep_sci8_txt:
        output = image_path.with_suffix(".sci8.txt")
        run_hex2000(image_path, output, hex2000_path=args.hex2000)
        image = build_firmware_image(image_path, output)
    else:
        work = tempfile.TemporaryDirectory(prefix="cpu1_ram_run_sci8_")
        output = Path(work.name) / f"{image_path.stem}.sci8.txt"
        run_hex2000(image_path, output, hex2000_path=args.hex2000)
        image = build_firmware_image(image_path, output)
    try:
        device = SimulatorIoDevice() if args.transport == "simulator" else SerialIoDevice(args.port, baudrate=args.baud)
        client = ProtocolClient(device, default_timeout_ms=args.timeout_ms, clear_input_before_request=False)
        workflow = UpgradeWorkflow(client)
        try:
            if args.autobaud_mode == "always":
                info = client.open(wait_slave_timeout_ms=args.timeout_ms, device_info_timeout_ms=args.timeout_ms)
            else:
                device.open()
                info = client.get_device_info(timeout_ms=args.timeout_ms)
            crc = workflow.run_ram_image(image)
            packet_count = (image.total_words + info.max_data_words - 1) // info.max_data_words
            return ram_run.RamRunResult(image.entry_point, image.total_words, crc, packet_count)
        finally:
            client.close()
    finally:
        if work is not None:
            work.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    normalize_output(args)
    validate_args(parser, args)
    try:
        result = run_cpu1_ram_run(args)
    except Exception as exc:
        data = envelope(ok=False, tool=TOOL, command="run", stage="FAILED", error_code="RUN_RAM_ERROR", message=str(exc))
        print_envelope(data) if args.output == "json" else print(f"FAIL: {exc!r}")
        return 1
    data = envelope(ok=True, tool=TOOL, command="run", stage="DONE", result=result)
    print_envelope(data) if args.output == "json" else print(ram_run.format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
