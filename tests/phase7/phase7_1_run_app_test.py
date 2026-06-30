#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 7.1 real .out RUN command test."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

from bootloader_upgrade_tool.core import ProtocolClient, UpgradeWorkflow
from bootloader_upgrade_tool.firmware import (
    FirmwareImage,
    build_firmware_image,
    locate_hex2000,
    run_hex2000,
    validate_app_firmware_image,
)
from bootloader_upgrade_tool.io import SerialIoDevice


APP_START = 0x082400
APP_END_EXCLUSIVE = 0x0C0000


def parse_int(text: str) -> int:
    return int(text, 0)


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data) or "<empty>"


def resolve_hex2000(path: str | None, c200_cg_root: str | None) -> Path:
    if path:
        return locate_hex2000(path)
    if c200_cg_root:
        return locate_hex2000(environ={"C200_CG_ROOT": c200_cg_root})
    for name in ("C200_CG_ROOT", "C2000_CG_ROOT", "C2000_CGT_ROOT"):
        value = os.environ.get(name)
        if value:
            try:
                return locate_hex2000(environ={"C200_CG_ROOT": value})
            except Exception:
                pass
    return locate_hex2000()


def validate_image(image: FirmwareImage, start: int, end: int) -> None:
    validate_app_firmware_image(image)
    if not (start <= image.entry_point < end):
        raise ValueError(f"entry point 0x{image.entry_point:08X} is outside app Flash range")
    if image.entry_point % 8:
        raise ValueError(f"entry point 0x{image.entry_point:08X} is not 8-word aligned")
    for block in image.blocks:
        if block.address < start or block.end_exclusive > end:
            raise ValueError(
                f"block 0x{block.address:08X}-0x{block.end_exclusive - 1:08X} "
                "is outside app Flash range"
            )


def convert_image(args: argparse.Namespace) -> tuple[Path, Path, FirmwareImage, tempfile.TemporaryDirectory[str] | None]:
    out_file = Path(args.out_file)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.hex_file:
        hex_file = Path(args.hex_file)
    elif args.keep_hex:
        hex_file = out_file.with_suffix(".sci8.txt")
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="phase7_1_hex_")
        hex_file = Path(temp_dir.name) / (out_file.stem + ".sci8.txt")

    hex2000 = resolve_hex2000(args.hex2000, args.c200_cg_root)
    print(f"hex2000: {hex2000}")
    run_hex2000(out_file, hex_file, hex2000_path=hex2000)
    return out_file, hex_file, build_firmware_image(out_file, hex_file), temp_dir


def print_summary(out_file: Path, hex_file: Path, image: FirmwareImage) -> None:
    print(f"OUT: {out_file}")
    print(f"HEX: {hex_file}")
    print(f"Entry point: 0x{image.entry_point:08X}")
    print(f"Total words: {image.total_words}")
    print(f"Block count: {len(image.blocks)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 7.1 RUN real .out test")
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--out-file", required=True)
    parser.add_argument("--hex-file")
    parser.add_argument("--hex2000")
    parser.add_argument("--c200-cg-root")
    parser.add_argument("--address-start", type=parse_int, default=APP_START)
    parser.add_argument("--address-end", type=parse_int, default=APP_END_EXCLUSIVE)
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--keep-hex", action="store_true")
    args = parser.parse_args()

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    device: SerialIoDevice | None = None
    try:
        out_file, hex_file, image, temp_dir = convert_image(args)
        print_summary(out_file, hex_file, image)
        validate_image(image, args.address_start, args.address_end)

        device = SerialIoDevice(args.port, baudrate=args.baud)
        client = ProtocolClient(
            device,
            default_timeout_ms=args.timeout_ms,
            clear_input_before_request=False,
        )
        client.trace_bytes = lambda label, data: print(f"PROTO: {label}: {hex_bytes(data)}")
        workflow = UpgradeWorkflow(client)

        print(f"OPEN {args.port} @ {args.baud} without autobaud")
        device.open()
        info = client.get_device_info(timeout_ms=args.timeout_ms)
        print(f"DeviceInfo: {info!r}")
        workflow.run(image)
        print("PASS: Phase 7.1 RUN command succeeded")
        return 0

    except Exception as exc:
        print(f"FAIL: {exc!r}", file=sys.stderr)
        return 1
    finally:
        if device is not None:
            device.close()
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
