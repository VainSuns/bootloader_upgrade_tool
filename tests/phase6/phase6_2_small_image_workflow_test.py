#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 6.2 small synthetic FirmwareImage Program/Verify workflow test."""

from __future__ import annotations

import argparse
import sys

from bootloader_upgrade_tool.core import ProtocolClient, UpgradeWorkflow
from bootloader_upgrade_tool.core import workflow as workflow_module
from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.io import SerialIoDevice
from bootloader_upgrade_tool.protocol.constants import Command


def parse_int(text: str) -> int:
    return int(text, 0)


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data) or "<empty>"


def make_image(address: int, word_count: int) -> FirmwareImage:
    words = tuple(range(0x1000, 0x1000 + word_count))
    return FirmwareImage(
        source_out_file="<synthetic-phase6.2>",
        generated_hex_file="<none>",
        entry_point=address,
        blocks=[FirmwareBlock(address, words)],
        file_checksum="synthetic",
        format_info={
            "source": "phase6.2 synthetic small image",
            "words": len(words),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 6.2 synthetic FirmwareImage Program/Verify SCI test"
    )
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--words", type=int, default=16)
    parser.add_argument("--sector-mask", type=parse_int, default=0x00000002)
    parser.add_argument("--address", type=parse_int, default=0x082000)
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--erase-timeout-ms", type=int, default=60000)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    device = SerialIoDevice(args.port, baudrate=args.baud)
    client = ProtocolClient(
        device,
        default_timeout_ms=args.timeout_ms,
        clear_input_before_request=False,
    )
    client.trace_bytes = lambda label, data: print(f"PROTO: {label}: {hex_bytes(data)}")

    workflow_module._COMMAND_TIMEOUT_MS[Command.ERASE] = args.erase_timeout_ms
    workflow = UpgradeWorkflow(client)
    image = make_image(args.address, args.words)

    try:
        print(f"OPEN {args.port} @ {args.baud} without autobaud")
        device.open()

        info = client.get_device_info(timeout_ms=args.timeout_ms)
        print(f"DeviceInfo: {info!r}")
        print(
            f"Synthetic image: address=0x{args.address:08X}, "
            f"words={args.words}, sector_mask=0x{args.sector_mask:08X}"
        )

        if args.verify_only:
            print("Mode: verify-only")
            workflow.verify(image)
            print("PASS: Phase 6.2 verify-only succeeded")
            return 0

        print("Mode: erase + program + verify")
        workflow.erase(args.sector_mask)
        print("INFO: Erase complete")
        workflow.program(image)
        print("INFO: Program complete")
        workflow.verify(image)
        print("INFO: Verify complete")
        print("PASS: Phase 6.2 small image workflow succeeded")
        return 0

    except Exception as exc:
        print(f"FAIL: {exc!r}", file=sys.stderr)
        detail = workflow.last_error_detail
        if detail is not None:
            print(f"LastErrorDetail: {detail!r}", file=sys.stderr)
        return 1
    finally:
        device.close()


if __name__ == "__main__":
    raise SystemExit(main())
