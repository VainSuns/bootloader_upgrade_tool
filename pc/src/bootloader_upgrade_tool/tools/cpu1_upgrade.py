"""Productized CPU1 Flash App upgrade CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile
from typing import Any, Sequence

from ..core import ProtocolClient, UpgradeWorkflow
from ..firmware import (
    FirmwareBlock,
    FirmwareImage,
    build_firmware_image,
    parse_flash_service_symbols_from_map,
    patch_flash_service_image,
    run_hex2000,
    validate_app_firmware_image,
)
from ..protocol.constants import SERVICE_DESCRIPTOR_WORDS, ServiceState
from ..protocol.models import MetadataSummary
from .boot_status_probe import BootStatusResult, collect_boot_status, format_text as format_status_text
from .common_cli import (
    CliToolError,
    add_output_args,
    connect_client,
    envelope,
    make_client,
    normalize_output,
    parse_u32,
    print_envelope,
)


TOOL = "cpu1_upgrade"
DEFAULT_DESCRIPTOR_SYMBOL = "g_boot_flash_service_descriptor"
ALLOWED_ERASE_MASK = 0x00003FFE
SECTORS = (
    (0x080000, 0x082000, 0),
    (0x082000, 0x084000, 1),
    (0x084000, 0x086000, 2),
    (0x086000, 0x088000, 3),
    (0x088000, 0x090000, 4),
    (0x090000, 0x098000, 5),
    (0x098000, 0x0A0000, 6),
    (0x0A0000, 0x0A8000, 7),
    (0x0A8000, 0x0B0000, 8),
    (0x0B0000, 0x0B8000, 9),
    (0x0B8000, 0x0BA000, 10),
    (0x0BA000, 0x0BC000, 11),
    (0x0BC000, 0x0BE000, 12),
    (0x0BE000, 0x0C0000, 13),
)


def _image_sector_mask(image: FirmwareImage) -> int:
    mask = 0
    for block in image.blocks:
        for start, end, bit in SECTORS:
            if block.address < end and block.end_exclusive > start:
                mask |= 1 << bit
    return mask


def validate_sector_mask_for_image(sector_mask: int, image: FirmwareImage) -> None:
    validate_app_firmware_image(image)
    if sector_mask == 0:
        raise ValueError("sector-mask must be nonzero")
    if sector_mask & 0x1:
        raise ValueError("sector-mask must not erase Sector A / bootloader")
    if sector_mask & ~ALLOWED_ERASE_MASK:
        raise ValueError("sector-mask contains sectors outside Slot A App erase mask")
    needed = _image_sector_mask(image)
    if needed == 0 or (needed & ~sector_mask):
        raise ValueError(
            f"sector-mask 0x{sector_mask:08X} does not cover image sectors 0x{needed:08X}"
        )


def _load_image(
    image_path: str,
    *,
    hex2000: str | None,
    sci8_txt: str | None = None,
    keep_sci8_txt: bool = False,
) -> tuple[FirmwareImage, tempfile.TemporaryDirectory[str] | None, str]:
    source = Path(image_path)
    if source.suffix.lower() == ".txt":
        return build_firmware_image(source, source), None, str(source)
    if sci8_txt:
        output = Path(sci8_txt)
        if output.exists():
            return build_firmware_image(source, output), None, str(output)
        run_hex2000(source, output, hex2000_path=hex2000)
        return build_firmware_image(source, output), None, str(output)
    work = None if keep_sci8_txt else tempfile.TemporaryDirectory(prefix="cpu1_upgrade_sci8_")
    output = (
        source.with_suffix(".sci8.txt")
        if keep_sci8_txt
        else Path(work.name) / f"{source.stem}.sci8.txt"  # type: ignore[union-attr]
    )
    try:
        run_hex2000(source, output, hex2000_path=hex2000)
        return build_firmware_image(source, output), work, str(output)
    except Exception:
        if work is not None:
            work.cleanup()
        raise


def _load_service(args: argparse.Namespace, client: ProtocolClient) -> dict[str, Any]:
    if not args.service_image or not args.service_map:
        raise CliToolError("ARGUMENT_ERROR", "--service-image and --service-map are required", stage="PARSE_SERVICE_MAP")
    image, work, _ = _load_image(args.service_image, hex2000=args.hex2000)
    try:
        try:
            symbols = parse_flash_service_symbols_from_map(
                Path(args.service_map), descriptor_symbol=args.service_descriptor_symbol
            )
        except Exception as exc:
            raise CliToolError("SERVICE_MAP_ERROR", str(exc), stage="PARSE_SERVICE_MAP") from exc
        if client.device_info is None:
            raise CliToolError("TRANSPORT_ERROR", "device info is unavailable", stage="SERVICE_ATTACH")
        patched = patch_flash_service_image(
            image,
            descriptor_address=symbols.descriptor_address,
            api_table_address=symbols.api_table_address,
            crc_patch_address=symbols.crc_patch_address,
            load_order="descriptor_last",
            descriptor_words=SERVICE_DESCRIPTOR_WORDS,
            max_data_words=client.device_info.max_data_words,
        )
        status = UpgradeWorkflow(client).load_and_attach_service(patched, symbols.descriptor_address)
        if status.service_state != ServiceState.ATTACHED:
            raise CliToolError("SERVICE_ATTACH_ERROR", "service did not reach ATTACHED", stage="SERVICE_ATTACH")
        return {
            "descriptor_address": symbols.descriptor_address,
            "api_table_address": symbols.api_table_address,
            "crc_patch_address": symbols.crc_patch_address,
            "total_words": patched.total_words,
            "service_state": status.service_state,
            "service_major": status.service_major,
            "service_minor": status.service_minor,
            "capabilities": status.capabilities,
            "loaded_image_crc32": status.loaded_image_crc32,
        }
    finally:
        if work is not None:
            work.cleanup()


def _require_current_attempt(summary: MetadataSummary) -> None:
    if not summary.metadata_valid:
        raise CliToolError("APP_CONFIRM_ERROR", "metadata_valid is required before APP_CONFIRMED", stage="WRITE_APP_CONFIRM")
    if summary.entry_point == 0 or summary.image_size_words == 0 or summary.image_crc32 == 0:
        raise CliToolError("APP_CONFIRM_ERROR", "current IMAGE_VALID is required before APP_CONFIRMED", stage="WRITE_APP_CONFIRM")
    if summary.entry_point % 8:
        raise CliToolError("APP_CONFIRM_ERROR", "current IMAGE_VALID entry point is not 8-word aligned", stage="WRITE_APP_CONFIRM")
    if summary.boot_attempt_count == 0:
        raise CliToolError(
            "BOOT_ATTEMPT_REQUIRED",
            "BOOT_ATTEMPT for current IMAGE_VALID is required before APP_CONFIRMED",
            stage="WRITE_APP_CONFIRM",
            device_reason="FIRST_TRIAL_REQUIRES_PC_RUN",
        )


def _dummy_image_from_summary(summary: MetadataSummary) -> FirmwareImage:
    return FirmwareImage(
        source_out_file="<metadata>",
        generated_hex_file="<metadata>",
        entry_point=summary.entry_point,
        blocks=(FirmwareBlock(summary.entry_point, (0xFFFF,) * 8),),
        file_checksum="metadata",
        format_info={"source": "metadata summary"},
    )


def _confirm_metadata(client: ProtocolClient, timeout_ms: int) -> BootStatusResult:
    summary = client.get_metadata_summary(timeout_ms=timeout_ms)
    _require_current_attempt(summary)
    client.metadata_append_app_confirmed(
        entry_point=summary.entry_point,
        image_size_words=summary.image_size_words,
        image_crc32=summary.image_crc32,
        timeout_ms=timeout_ms,
    )
    status = collect_boot_status(client, timeout_ms=timeout_ms)
    if not status.metadata.app_confirmed:
        raise CliToolError("APP_CONFIRM_ERROR", "APP_CONFIRMED was not written", stage="READ_FINAL_STATUS")
    if status.preview.reason != "APP_CONFIRMED":
        raise CliToolError("APP_CONFIRM_ERROR", "boot policy did not become APP_CONFIRMED", stage="READ_FINAL_STATUS")
    return status


def run_cpu1_status(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    try:
        connect_client(client, args)
        return {"status": collect_boot_status(client, timeout_ms=args.timeout_ms)}
    finally:
        client.close()


def run_cpu1_attach_service(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    try:
        connect_client(client, args)
        return {"service": _load_service(args, client)}
    finally:
        client.close()


def run_cpu1_flash(args: argparse.Namespace) -> dict[str, Any]:
    if args.sector_mask is None:
        raise CliToolError("ARGUMENT_ERROR", "--sector-mask is required", stage="SAFETY_CHECK")
    client = make_client(args)
    work = None
    try:
        connect_client(client, args)
        service = _load_service(args, client)
        image, work, sci8 = _load_image(
            args.app_image,
            hex2000=args.hex2000,
            sci8_txt=args.sci8_txt,
            keep_sci8_txt=args.keep_sci8_txt,
        )
        validate_sector_mask_for_image(args.sector_mask, image)
        UpgradeWorkflow(client).dfu(args.sector_mask, image)
        return {
            "service": service,
            "app": {"entry_point": image.entry_point, "total_words": image.total_words, "generated_sci8_txt": sci8},
            "sector_mask": args.sector_mask,
            "post_flash_status": collect_boot_status(client, timeout_ms=args.timeout_ms),
        }
    finally:
        if work is not None:
            work.cleanup()
        client.close()


def run_cpu1_run(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    try:
        connect_client(client, args)
        status = collect_boot_status(client, timeout_ms=args.timeout_ms)
        image = _dummy_image_from_summary(status.metadata)
        UpgradeWorkflow(client).run(image)
        return {"pre_run_status": status, "run_sent": True}
    finally:
        client.close()


def run_cpu1_confirm(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    try:
        connect_client(client, args)
        service = _load_service(args, client)
        return {"service": service, "final_status": _confirm_metadata(client, args.timeout_ms)}
    finally:
        client.close()


def run_cpu1_upgrade(args: argparse.Namespace) -> dict[str, Any]:
    if args.dry_run:
        image, work, sci8 = _load_image(args.app_image, hex2000=args.hex2000, sci8_txt=args.sci8_txt, keep_sci8_txt=args.keep_sci8_txt)
        try:
            validate_sector_mask_for_image(args.sector_mask, image)
            return {"dry_run": True, "entry_point": image.entry_point, "total_words": image.total_words, "generated_sci8_txt": sci8}
        finally:
            if work is not None:
                work.cleanup()
    result = run_cpu1_flash(args)
    if args.no_run:
        return result | {"run_sent": False, "app_confirmed": False}
    run_result = run_cpu1_run(args)
    result["run"] = run_result
    if args.no_confirm:
        result["app_confirmed"] = False
        return result
    try:
        result["confirm"] = run_cpu1_confirm(args)
        result["app_confirmed"] = True
    except Exception as exc:
        result["app_confirmed"] = False
        result["confirm_deferred"] = f"RUN may have jumped to App; re-enter bootloader and run confirm: {exc}"
    return result


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--transport", choices=("serial",), default="serial", help="transport backend; Phase 10.7 implements serial only")
    parser.add_argument("--port", required=True, help="serial COM port, for example COM10")
    parser.add_argument("--baud", type=int, default=9600, help="serial baud rate (default: 9600)")
    parser.add_argument(
        "--autobaud-mode",
        choices=("always", "skip"),
        default="always",
        help="always: perform SCI 'A' autobaud; skip: open serial and query protocol directly",
    )
    parser.add_argument("--timeout-ms", type=int, default=5000, help="request/autobaud timeout in milliseconds")
    parser.add_argument("--verbose", action="store_true", help="reserved for extra diagnostics")
    add_output_args(parser)


def _add_service(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--service-image", help="flash_service_lib .out or SCI8 TXT image")
    parser.add_argument("--service-map", help="flash_service_lib linker .map used to locate descriptor symbols")
    parser.add_argument(
        "--service-descriptor-symbol",
        default=DEFAULT_DESCRIPTOR_SYMBOL,
        help=f"descriptor symbol name in --service-map (default: {DEFAULT_DESCRIPTOR_SYMBOL})",
    )


def _add_app(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-image", help="CPU1 Flash App .out or SCI8 TXT image")
    parser.add_argument("--hex2000", help="hex2000.exe path or TI C2000 compiler root/bin directory")
    parser.add_argument("--sci8-txt", help="existing or generated SCI8 TXT path")
    parser.add_argument("--hex-file", dest="sci8_txt", help="compatibility alias of --sci8-txt")
    parser.add_argument("--keep-sci8-txt", action="store_true", help="keep generated SCI8 TXT next to the .out file")
    parser.add_argument("--keep-hex", dest="keep_sci8_txt", action="store_true", help="compatibility alias of --keep-sci8-txt")
    parser.add_argument("--sector-mask", type=parse_u32, help="uint32 erase sector mask; Sector A bit0 is forbidden")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CPU1 Flash App upgrade tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  cpu1_upgrade status --port COM10\n"
            "  cpu1_upgrade attach-service --port COM10 --service-image service.out --service-map service.map\n"
            "  cpu1_upgrade flash --port COM10 --service-image service.out --service-map service.map --app-image app.out --hex2000 <path> --sector-mask 0x00003FFE\n"
            "  cpu1_upgrade run --port COM10\n"
            "  cpu1_upgrade confirm --port COM10 --service-image service.out --service-map service.map\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, help="operation to execute")
    descriptions = {
        "status": "read metadata summary and preview confirmed-only boot policy",
        "attach-service": "load flash_service_lib into RAM and SERVICE_ATTACH it",
        "flash": "attach service, erase/program/verify App, then write IMAGE_VALID",
        "run": "append BOOT_ATTEMPT when needed and send RUN FLASH_APP",
        "confirm": "attach service and append APP_CONFIRMED for current IMAGE_VALID",
        "upgrade": "one-shot flash flow with optional RUN and APP_CONFIRM",
    }
    for name in ("status", "attach-service", "flash", "run", "confirm", "upgrade"):
        cmd = sub.add_parser(name, description=descriptions[name], help=descriptions[name])
        _add_common(cmd)
        if name in {"attach-service", "flash", "confirm", "upgrade"}:
            _add_service(cmd)
        if name in {"flash", "upgrade"}:
            _add_app(cmd)
        if name == "upgrade":
            cmd.add_argument("--no-run", action="store_true", help="stop after Flash DFU and IMAGE_VALID")
            cmd.add_argument("--no-confirm", action="store_true", help="send RUN but do not append APP_CONFIRMED")
            cmd.add_argument("--dry-run", action="store_true", help="parse and validate inputs without touching the device")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")
    if args.command in {"flash", "upgrade"} and not args.app_image:
        parser.error("--app-image is required")
    if args.command in {"flash", "upgrade"} and args.sector_mask is None:
        parser.error("--sector-mask is required")
    if args.command in {"attach-service", "flash", "confirm", "upgrade"}:
        if not args.service_image or not args.service_map:
            parser.error("--service-image and --service-map are required")


def format_text(command: str, result: dict[str, Any]) -> str:
    if command == "status":
        return format_status_text(result["status"])
    lines = [f"PASS: cpu1_upgrade {command}"]
    if "sector_mask" in result:
        lines.append(f"Sector mask: 0x{result['sector_mask']:08X}")
    if "app" in result:
        lines.append(f"App entry: 0x{result['app']['entry_point']:08X}")
        lines.append(f"Generated SCI8 TXT: {result['app']['generated_sci8_txt']}")
    if "service" in result:
        lines.append(f"Service descriptor: 0x{result['service']['descriptor_address']:08X}")
    if result.get("confirm_deferred"):
        lines.append(f"APP_CONFIRM deferred: {result['confirm_deferred']}")
    return "\n".join(lines)


def run_command(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "status": run_cpu1_status,
        "attach-service": run_cpu1_attach_service,
        "flash": run_cpu1_flash,
        "run": run_cpu1_run,
        "confirm": run_cpu1_confirm,
        "upgrade": run_cpu1_upgrade,
    }[args.command](args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    normalize_output(args)
    validate_args(parser, args)
    try:
        result = run_command(args)
    except CliToolError as exc:
        data = envelope(ok=False, tool=TOOL, command=args.command, stage=exc.stage, error_code=exc.error_code, message=str(exc), device_reason=exc.device_reason)
        print_envelope(data) if args.output == "json" else print(f"FAIL[{exc.stage}/{exc.error_code}]: {exc}")
        return 1
    except Exception as exc:
        data = envelope(ok=False, tool=TOOL, command=args.command, stage="FAILED", error_code="PROTOCOL_ERROR", message=str(exc))
        print_envelope(data) if args.output == "json" else print(f"FAIL: {exc!r}")
        return 1
    data = envelope(ok=True, tool=TOOL, command=args.command, stage="DONE", result=result)
    print_envelope(data) if args.output == "json" else print(format_text(args.command, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
