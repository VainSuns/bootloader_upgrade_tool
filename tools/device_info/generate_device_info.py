"""Narrow development tool for converting linker MEMORY to device_info.json."""

from __future__ import annotations

import argparse
from pathlib import Path

from bootloader_upgrade_tool.firmware import (
    build_device_info,
    parse_memory_file,
    write_device_info,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate CPU1 device_info.json from a TI linker command file MEMORY block."
    )
    parser.add_argument("linker_cmd", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--device", default="F28377D")
    parser.add_argument(
        "--flash-region",
        action="append",
        dest="flash_regions",
        help="Flash region name in sector-mask order; repeat for each sector.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    regions = parse_memory_file(args.linker_cmd)
    device_info = build_device_info(
        regions,
        device=args.device,
        cpu="CPU1",
        flash_region_names=args.flash_regions,
    )
    write_device_info(args.output_json, device_info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

