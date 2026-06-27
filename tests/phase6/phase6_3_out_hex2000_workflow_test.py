#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 6.3 real .out -> hex2000 -> FirmwareImage Program/Verify test."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

from bootloader_upgrade_tool.core import ProtocolClient, UpgradeWorkflow
from bootloader_upgrade_tool.core import workflow as workflow_module
from bootloader_upgrade_tool.firmware import (
    FirmwareImage,
    build_firmware_image,
    locate_hex2000,
    run_hex2000,
)
from bootloader_upgrade_tool.io import SerialIoDevice
from bootloader_upgrade_tool.protocol.alignment import pad_write_data, validate_write_data
from bootloader_upgrade_tool.protocol.constants import Command


APP_START = 0x082000
APP_END_EXCLUSIVE = 0x0C0000
ALLOWED_ERASE_MASK = 0x00003FFE

SECTORS = (
    ("FLASHA", 0x080000, 0x082000, 0),
    ("FLASHB", 0x082000, 0x084000, 1),
    ("FLASHC", 0x084000, 0x086000, 2),
    ("FLASHD", 0x086000, 0x088000, 3),
    ("FLASHE", 0x088000, 0x090000, 4),
    ("FLASHF", 0x090000, 0x098000, 5),
    ("FLASHG", 0x098000, 0x0A0000, 6),
    ("FLASHH", 0x0A0000, 0x0A8000, 7),
    ("FLASHI", 0x0A8000, 0x0B0000, 8),
    ("FLASHJ", 0x0B0000, 0x0B8000, 9),
    ("FLASHK", 0x0B8000, 0x0BA000, 10),
    ("FLASHL", 0x0BA000, 0x0BC000, 11),
    ("FLASHM", 0x0BC000, 0x0BE000, 12),
    ("FLASHN", 0x0BE000, 0x0C0000, 13),
)


def parse_int(text: str) -> int:
    return int(text, 0)


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data) or "<empty>"


def resolve_hex2000(path: str | None, c200_cg_root: str | None) -> Path:
    if path:
        return locate_hex2000(path)
    if c200_cg_root:
        return locate_hex2000(environ={"C200_CG_ROOT": c200_cg_root})
    aliases = {
        "C200_CG_ROOT": os.environ.get("C200_CG_ROOT"),
        "C2000_CG_ROOT": os.environ.get("C2000_CG_ROOT"),
        "C2000_CGT_ROOT": os.environ.get("C2000_CGT_ROOT"),
    }
    for value in aliases.values():
        if value:
            try:
                return locate_hex2000(value)
            except Exception:
                pass
    return locate_hex2000()


def block_ranges(image: FirmwareImage) -> list[tuple[int, int]]:
    return [(block.address, block.end_exclusive) for block in image.blocks]


def validate_image_range(image: FirmwareImage, start: int, end: int) -> None:
    if not (start <= image.entry_point < end):
        raise ValueError(f"entry point 0x{image.entry_point:08X} is outside app Flash range")
    if image.entry_point % 8:
        raise ValueError(f"entry point 0x{image.entry_point:08X} is not 8-word aligned")
    for block_start, block_end in block_ranges(image):
        if block_start < start or block_end > end:
            raise ValueError(
                f"block 0x{block_start:08X}-0x{block_end - 1:08X} is outside app Flash range"
            )


def calculate_sector_mask(image: FirmwareImage) -> int:
    mask = 0
    for block_start, block_end in block_ranges(image):
        for name, sector_start, sector_end, bit in SECTORS:
            if block_start < sector_end and block_end > sector_start:
                print(f"Sector touched: {name} bit{bit}")
                mask |= 1 << bit
    if mask & 0x1:
        raise ValueError("calculated sector_mask includes Sector A")
    if mask == 0:
        raise ValueError("image does not touch any known Flash sector")
    if mask & ~ALLOWED_ERASE_MASK:
        raise ValueError(f"calculated sector_mask 0x{mask:08X} exceeds allowed app mask")
    return mask


def validate_packets(image: FirmwareImage, max_data_words: int) -> None:
    for block in sorted(image.blocks, key=lambda item: item.address):
        offset = 0
        while offset < len(block.words):
            raw = block.words[offset : offset + max_data_words]
            address = block.address + offset
            packet = pad_write_data(raw, max_data_words=max_data_words)
            if address % 8:
                raise ValueError(f"ProgramData address 0x{address:08X} is not 8-word aligned")
            validate_write_data(packet, max_data_words=max_data_words)
            offset += len(raw)


def print_summary(out_file: Path, hex_file: Path, image: FirmwareImage) -> None:
    print(f"OUT: {out_file}")
    print(f"HEX: {hex_file}")
    print(f"Entry point: 0x{image.entry_point:08X}")
    print(f"Total words: {image.total_words}")
    print(f"Block count: {len(image.blocks)}")
    for index, block in enumerate(image.blocks):
        print(
            f"  Block {index}: address=0x{block.address:08X}, "
            f"words={len(block.words)}, end_exclusive=0x{block.end_exclusive:08X}"
        )


def convert_image(args: argparse.Namespace) -> tuple[Path, Path, FirmwareImage, tempfile.TemporaryDirectory[str] | None]:
    out_file = Path(args.out_file)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.hex_file:
        hex_file = Path(args.hex_file)
    elif args.keep_hex:
        hex_file = out_file.with_suffix(".sci8.txt")
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="phase6_3_hex_")
        hex_file = Path(temp_dir.name) / (out_file.stem + ".sci8.txt")

    hex2000 = resolve_hex2000(args.hex2000, args.c200_cg_root)
    print(f"hex2000: {hex2000}")
    run_hex2000(out_file, hex_file, hex2000_path=hex2000)
    image = build_firmware_image(out_file, hex_file)
    if args.keep_hex:
        print(f"Keeping generated hex: {hex_file}")
    return out_file, hex_file, image, temp_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 6.3 real .out SCI workflow test")
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--out-file", required=True)
    parser.add_argument("--hex-file")
    parser.add_argument("--hex2000")
    parser.add_argument("--c200-cg-root")
    parser.add_argument("--sector-mask", type=parse_int)
    parser.add_argument("--address-start", type=parse_int, default=APP_START)
    parser.add_argument("--address-end", type=parse_int, default=APP_END_EXCLUSIVE)
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--erase-timeout-ms", type=int, default=60000)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-hex", action="store_true")
    args = parser.parse_args()

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    device: SerialIoDevice | None = None
    try:
        out_file, hex_file, image, temp_dir = convert_image(args)
        print_summary(out_file, hex_file, image)
        validate_image_range(image, args.address_start, args.address_end)
        calculated_mask = calculate_sector_mask(image)
        sector_mask = calculated_mask if args.sector_mask is None else args.sector_mask
        if sector_mask & 0x1:
            raise ValueError("sector_mask includes Sector A")
        if sector_mask & ~ALLOWED_ERASE_MASK:
            raise ValueError(f"sector_mask 0x{sector_mask:08X} exceeds allowed app mask")
        print(f"Calculated sector_mask: 0x{calculated_mask:08X}")
        print(f"Using sector_mask:       0x{sector_mask:08X}")

        if args.dry_run:
            print("PASS: Phase 6.3 dry-run succeeded")
            return 0

        device = SerialIoDevice(args.port, baudrate=args.baud)
        client = ProtocolClient(
            device,
            default_timeout_ms=args.timeout_ms,
            clear_input_before_request=False,
        )
        client.trace_bytes = lambda label, data: print(f"PROTO: {label}: {hex_bytes(data)}")
        workflow_module._COMMAND_TIMEOUT_MS[Command.ERASE] = args.erase_timeout_ms
        workflow = UpgradeWorkflow(client)

        print(f"OPEN {args.port} @ {args.baud} without autobaud")
        device.open()
        info = client.get_device_info(timeout_ms=args.timeout_ms)
        print(f"DeviceInfo: {info!r}")
        validate_packets(image, info.max_data_words)

        if args.verify_only:
            print("Mode: verify-only")
            workflow.verify(image)
            print("PASS: Phase 6.3 verify-only succeeded")
            return 0

        print("Mode: erase + program + verify")
        workflow.erase(sector_mask)
        print("INFO: Erase complete")
        workflow.program(image)
        print("INFO: Program complete")
        workflow.verify(image)
        print("INFO: Verify complete")
        print("PASS: Phase 6.3 .out workflow succeeded")
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
