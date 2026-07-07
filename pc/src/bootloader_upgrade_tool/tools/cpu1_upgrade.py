"""Productized CPU1 Flash App upgrade CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile
from typing import Any, Sequence

from ..core import ProtocolClient, UpgradeWorkflow
from ..core.workflow import calculate_programmed_image_crc32, _programmed_image_size_and_end
from ..firmware import (
    FirmwareImage,
    build_firmware_image,
    calculate_service_ram_load_crc32_descriptor_last,
    parse_flash_service_symbols_from_map,
    patch_flash_service_image,
    run_hex2000,
)
from ..firmware.flash_layout import (
    ALLOWED_ERASE_MASK,
    METADATA_SECTOR_MASK,
    calculate_app_sector_mask,
    resolve_dfu_erase_masks,
    resolve_manual_erase_masks,
    validate_sector_mask_for_image,
)
from ..protocol.constants import (
    Command,
    SERVICE_ABI_MAJOR,
    SERVICE_ABI_MINOR,
    SERVICE_DESCRIPTOR_WORDS,
    SERVICE_REQUIRED_CAPABILITIES,
    ServiceState,
    Target,
)
from ..protocol.models import MetadataSummary, ServiceStatus, split_u32
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
WARNING_ATTEMPT_WITHOUT_CONFIRM = "BOOT_ATTEMPT_WITHOUT_APP_CONFIRMED"


def calculate_app_identity(image: FirmwareImage, max_data_words: int) -> dict[str, int]:
    image_size_words, app_end = _programmed_image_size_and_end(image, max_data_words)
    return {
        "entry_point": image.entry_point,
        "image_size_words": image_size_words,
        "image_crc32": calculate_programmed_image_crc32(image, max_data_words),
        "app_end": app_end,
    }


def same_image(summary: MetadataSummary, identity: dict[str, int]) -> bool:
    return bool(
        summary.metadata_valid
        and summary.entry_point == identity["entry_point"]
        and summary.image_size_words == identity["image_size_words"]
        and summary.image_crc32 == identity["image_crc32"]
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


def _service_result(
    symbols: Any,
    status: ServiceStatus,
    total_words: int,
    *,
    reused: bool,
    attach_performed: bool,
) -> dict[str, Any]:
    return {
        "descriptor_address": symbols.descriptor_address,
        "api_table_address": symbols.api_table_address,
        "crc_patch_address": symbols.crc_patch_address,
        "total_words": total_words,
        "service_state": status.service_state,
        "service_major": status.service_major,
        "service_minor": status.service_minor,
        "capabilities": status.capabilities,
        "loaded_image_crc32": status.loaded_image_crc32,
        "reused": reused,
        "attach_performed": attach_performed,
    }


def _service_matches(
    status: ServiceStatus,
    *,
    expected_crc32: int,
    expected_total_words: int,
    required_capabilities: int,
) -> bool:
    return bool(
        status.service_state == ServiceState.ATTACHED
        and status.loaded_image_crc32 == expected_crc32
        and status.loaded_image_words == expected_total_words
        and status.abi_major == SERVICE_ABI_MAJOR
        and status.abi_minor == SERVICE_ABI_MINOR
        and (status.capabilities & required_capabilities) == required_capabilities
    )


def _prepare_service_image(args: argparse.Namespace, client: ProtocolClient) -> tuple[Any, FirmwareImage, tempfile.TemporaryDirectory[str] | None, int]:
    if not args.service_image or not args.service_map:
        raise CliToolError("ARGUMENT_ERROR", "--service-image and --service-map are required", stage="PARSE_SERVICE_MAP")
    work = None
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
        expected_crc32 = calculate_service_ram_load_crc32_descriptor_last(
            patched,
            symbols.descriptor_address,
            SERVICE_DESCRIPTOR_WORDS,
            client.device_info.max_data_words,
        )
        return symbols, patched, work, expected_crc32
    except Exception:
        if work is not None:
            work.cleanup()
        raise


def _load_service(
    args: argparse.Namespace,
    client: ProtocolClient,
    *,
    required_capabilities: int = int(SERVICE_REQUIRED_CAPABILITIES),
) -> dict[str, Any]:
    symbols, patched, work, expected_crc32 = _prepare_service_image(args, client)
    try:
        status = UpgradeWorkflow(client).load_and_attach_service(patched, symbols.descriptor_address)
        if not _service_matches(
            status,
            expected_crc32=expected_crc32,
            expected_total_words=patched.total_words,
            required_capabilities=required_capabilities,
        ):
            raise CliToolError("SERVICE_CAPABILITY_ERROR", "attached service does not satisfy required ABI/capabilities", stage="SERVICE_ATTACH")
        return _service_result(symbols, status, patched.total_words, reused=False, attach_performed=True)
    finally:
        if work is not None:
            work.cleanup()


def ensure_service_attached(
    args: argparse.Namespace,
    client: ProtocolClient,
    required_capabilities: int = int(SERVICE_REQUIRED_CAPABILITIES),
) -> dict[str, Any]:
    symbols, patched, work, expected_crc32 = _prepare_service_image(args, client)
    try:
        if not getattr(args, "force_service_attach", False):
            status = client.get_service_status(timeout_ms=args.timeout_ms)
            if _service_matches(
                status,
                expected_crc32=expected_crc32,
                expected_total_words=patched.total_words,
                required_capabilities=required_capabilities,
            ):
                return _service_result(symbols, status, patched.total_words, reused=True, attach_performed=False)
        status = UpgradeWorkflow(client).load_and_attach_service(patched, symbols.descriptor_address)
        if not _service_matches(
            status,
            expected_crc32=expected_crc32,
            expected_total_words=patched.total_words,
            required_capabilities=required_capabilities,
        ):
            raise CliToolError("SERVICE_CAPABILITY_ERROR", "attached service does not satisfy required ABI/capabilities", stage="SERVICE_ATTACH")
        return _service_result(symbols, status, patched.total_words, reused=False, attach_performed=True)
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


def _require_current_image_for_run(summary: MetadataSummary) -> None:
    if not summary.metadata_valid:
        raise CliToolError("RUN_ERROR", "valid IMAGE_VALID metadata is required before RUN", stage="RUN_APP")
    if summary.entry_point == 0 or summary.image_size_words == 0 or summary.image_crc32 == 0:
        raise CliToolError("RUN_ERROR", "current IMAGE_VALID is required before RUN", stage="RUN_APP")
    if summary.entry_point % 8:
        raise CliToolError("RUN_ERROR", "current IMAGE_VALID entry point is not 8-word aligned", stage="RUN_APP")


def _confirm_metadata(client: ProtocolClient, timeout_ms: int) -> BootStatusResult:
    summary = client.get_metadata_summary(timeout_ms=timeout_ms)
    return write_app_confirmed_and_verify(client, summary, timeout_ms)


def read_confirmable_summary(client: ProtocolClient, timeout_ms: int) -> MetadataSummary:
    summary = client.get_metadata_summary(timeout_ms=timeout_ms)
    _require_current_attempt(summary)
    return summary


def write_app_confirmed_and_verify(
    client: ProtocolClient,
    summary: MetadataSummary,
    timeout_ms: int,
) -> BootStatusResult:
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


def load_service_if_needed(
    args: argparse.Namespace,
    client: ProtocolClient,
    loaded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return loaded if loaded is not None else ensure_service_attached(args, client)


def perform_dfu_erase(workflow: UpgradeWorkflow, masks: dict[str, int]) -> list[int]:
    erased = [masks["first_erase_mask"]]
    workflow.erase(masks["first_erase_mask"])
    if masks["second_erase_mask"]:
        erased.append(masks["second_erase_mask"])
        workflow.erase(masks["second_erase_mask"])
    return erased


def program_app(workflow: UpgradeWorkflow, image: FirmwareImage) -> None:
    workflow.program(image)


def verify_app_and_write_image_valid(
    client: ProtocolClient,
    workflow: UpgradeWorkflow,
    image: FirmwareImage,
    identity: dict[str, int],
    timeout_ms: int,
) -> None:
    workflow.verify(image)
    client.metadata_append_image_valid(
        entry_point=identity["entry_point"],
        image_size_words=identity["image_size_words"],
        image_crc32=identity["image_crc32"],
        app_end=identity["app_end"],
        timeout_ms=timeout_ms,
    )


def send_run(client: ProtocolClient, summary: MetadataSummary) -> None:
    _require_current_image_for_run(summary)
    entry_low, entry_high = split_u32(summary.entry_point)
    client.transact(Command.RUN, (Target.FLASH_APP, entry_low, entry_high, 0), timeout_ms=5000)


def ensure_boot_attempt(
    args: argparse.Namespace,
    client: ProtocolClient,
    summary: MetadataSummary,
    *,
    service: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    _require_current_image_for_run(summary)
    if summary.app_confirmed or summary.boot_attempt_count > 0:
        return False, service
    if summary.boot_attempt_count >= summary.boot_attempt_limit:
        raise CliToolError("RUN_ERROR", "boot attempt limit reached", stage="WRITE_BOOT_ATTEMPT")
    service = load_service_if_needed(args, client, service)
    client.metadata_append_boot_attempt(
        entry_point=summary.entry_point,
        image_size_words=summary.image_size_words,
        image_crc32=summary.image_crc32,
        timeout_ms=args.timeout_ms,
    )
    return True, service


def run_flash_flow(
    args: argparse.Namespace,
    client: ProtocolClient,
    image: FirmwareImage,
    identity: dict[str, int],
    current_status: BootStatusResult,
) -> dict[str, Any]:
    masks = resolve_dfu_erase_masks(image, args.sector_mask)
    if same_image(current_status.metadata, identity) and not args.force:
        return {
            "action": "skipped",
            "reason": "IMAGE_VALID_ALREADY_MATCHES_INPUT",
            "image_valid_written": False,
            "force_hint": "use --force to erase/program/verify again",
            "sector_masks": masks,
            "service": None,
            "post_flash_status": current_status,
        }
    service = ensure_service_attached(args, client)
    workflow = UpgradeWorkflow(client)
    erased = perform_dfu_erase(workflow, masks)
    program_app(workflow, image)
    verify_app_and_write_image_valid(client, workflow, image, identity, args.timeout_ms)
    return {
        "action": "flashed",
        "image_valid_written": True,
        "service": service,
        "sector_masks": masks,
        "erased_masks": erased,
        "post_flash_status": collect_boot_status(client, timeout_ms=args.timeout_ms),
    }


def run_upgrade_flow(
    args: argparse.Namespace,
    client: ProtocolClient,
    image: FirmwareImage,
    identity: dict[str, int],
    initial_status: BootStatusResult,
) -> dict[str, Any]:
    flash = run_flash_flow(args, client, image, identity, initial_status)
    summary = flash["post_flash_status"].metadata
    service = flash.get("service")
    boot_attempt_written = False
    warning = None
    if not same_image(initial_status.metadata, identity) or args.force:
        boot_attempt_written, service = ensure_boot_attempt(args, client, summary, service=service)
    elif summary.app_confirmed:
        pass
    elif summary.boot_attempt_count > 0:
        warning = {
            "code": WARNING_ATTEMPT_WITHOUT_CONFIRM,
            "message": (
                "Current IMAGE_VALID already has BOOT_ATTEMPT but no APP_CONFIRMED; "
                "the App may have run before without confirmation."
            ),
        }
    else:
        boot_attempt_written, service = ensure_boot_attempt(args, client, summary, service=service)
    send_run(client, summary)
    return {
        **flash,
        "service": service,
        "boot_attempt_written": boot_attempt_written,
        "run_sent": True,
        "app_confirm": "already confirmed" if summary.app_confirmed else "pending / not verified",
        "warning": warning,
    }


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
        return {"service": ensure_service_attached(args, client)}
    finally:
        client.close()


def run_cpu1_erase(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    try:
        masks = resolve_manual_erase_masks(args.sector_mask)
        connect_client(client, args)
        service = ensure_service_attached(args, client)
        workflow = UpgradeWorkflow(client)
        erased: list[int] = []
        for mask in masks["erased_masks"]:
            workflow.erase(mask)
            erased.append(mask)
        return {
            "service": service,
            "erase": {
                "requested_mask": masks["requested_mask"],
                "erased_masks": erased,
            },
        }
    finally:
        client.close()


def run_cpu1_program(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    work = None
    try:
        image, work, sci8 = _load_image(
            args.app_image,
            hex2000=args.hex2000,
            sci8_txt=args.sci8_txt,
            keep_sci8_txt=args.keep_sci8_txt,
        )
        calculate_app_sector_mask(image)
        connect_client(client, args)
        service = ensure_service_attached(args, client)
        program_app(UpgradeWorkflow(client), image)
        return {
            "app": {"entry_point": image.entry_point, "total_words": image.total_words, "generated_sci8_txt": sci8},
            "service": service,
            "program": {"programmed": True},
        }
    finally:
        if work is not None:
            work.cleanup()
        client.close()


def run_cpu1_verify(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    work = None
    try:
        image, work, sci8 = _load_image(
            args.app_image,
            hex2000=args.hex2000,
            sci8_txt=args.sci8_txt,
            keep_sci8_txt=args.keep_sci8_txt,
        )
        calculate_app_sector_mask(image)
        connect_client(client, args)
        if client.device_info is None:
            raise CliToolError("TRANSPORT_ERROR", "device info is unavailable", stage="VERIFY_APP")
        identity = calculate_app_identity(image, client.device_info.max_data_words)
        service = ensure_service_attached(args, client)
        verify_app_and_write_image_valid(client, UpgradeWorkflow(client), image, identity, args.timeout_ms)
        return {
            "app": {"entry_point": image.entry_point, "total_words": image.total_words, "generated_sci8_txt": sci8},
            "identity": identity,
            "service": service,
            "verify": {"verified": True, "image_valid_written": True},
        }
    finally:
        if work is not None:
            work.cleanup()
        client.close()


def run_cpu1_flash(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    work = None
    try:
        image, work, sci8 = _load_image(
            args.app_image,
            hex2000=args.hex2000,
            sci8_txt=args.sci8_txt,
            keep_sci8_txt=args.keep_sci8_txt,
        )
        connect_client(client, args)
        if client.device_info is None:
            raise CliToolError("TRANSPORT_ERROR", "device info is unavailable", stage="READ_INITIAL_STATUS")
        identity = calculate_app_identity(image, client.device_info.max_data_words)
        status = collect_boot_status(client, timeout_ms=args.timeout_ms)
        flash = run_flash_flow(args, client, image, identity, status)
        return {
            "app": {"entry_point": image.entry_point, "total_words": image.total_words, "generated_sci8_txt": sci8},
            "identity": identity,
            **flash,
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
        boot_attempt_written, service = ensure_boot_attempt(args, client, status.metadata)
        send_run(client, status.metadata)
        return {
            "pre_run_status": status,
            "service": service,
            "boot_attempt_written": boot_attempt_written,
            "run_sent": True,
        }
    finally:
        client.close()


def run_cpu1_confirm(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    try:
        connect_client(client, args)
        summary = read_confirmable_summary(client, args.timeout_ms)
        service = ensure_service_attached(args, client)
        return {"service": service, "final_status": write_app_confirmed_and_verify(client, summary, args.timeout_ms)}
    finally:
        client.close()


def run_cpu1_upgrade(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    work = None
    if args.dry_run:
        image, work, sci8 = _load_image(args.app_image, hex2000=args.hex2000, sci8_txt=args.sci8_txt, keep_sci8_txt=args.keep_sci8_txt)
        try:
            masks = resolve_dfu_erase_masks(image, args.sector_mask)
            return {"dry_run": True, "entry_point": image.entry_point, "total_words": image.total_words, "generated_sci8_txt": sci8, "sector_masks": masks}
        finally:
            if work is not None:
                work.cleanup()
    try:
        image, work, sci8 = _load_image(
            args.app_image,
            hex2000=args.hex2000,
            sci8_txt=args.sci8_txt,
            keep_sci8_txt=args.keep_sci8_txt,
        )
        connect_client(client, args)
        if client.device_info is None:
            raise CliToolError("TRANSPORT_ERROR", "device info is unavailable", stage="READ_INITIAL_STATUS")
        identity = calculate_app_identity(image, client.device_info.max_data_words)
        status = collect_boot_status(client, timeout_ms=args.timeout_ms)
        if args.no_run:
            flash = run_flash_flow(args, client, image, identity, status)
            return {
                "app": {"entry_point": image.entry_point, "total_words": image.total_words, "generated_sci8_txt": sci8},
                "identity": identity,
                **flash,
                "run_sent": False,
                "boot_attempt_written": False,
                "app_confirm": "not verified",
            }
        return {
            "app": {"entry_point": image.entry_point, "total_words": image.total_words, "generated_sci8_txt": sci8},
            "identity": identity,
            **run_upgrade_flow(args, client, image, identity, status),
        }
    finally:
        if work is not None:
            work.cleanup()
        client.close()


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
    parser.add_argument("--force-service-attach", action="store_true", help="reload flash_service_lib even if the attached service already matches")
    parser.add_argument(
        "--service-descriptor-symbol",
        default=DEFAULT_DESCRIPTOR_SYMBOL,
        help=f"descriptor symbol name in --service-map (default: {DEFAULT_DESCRIPTOR_SYMBOL})",
    )


def _add_hex2000(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hex2000", help="hex2000.exe path or TI C2000 compiler root/bin directory")


def _add_app_image(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-image", help="CPU1 Flash App .out or SCI8 TXT image")
    parser.add_argument("--sci8-txt", help="existing or generated SCI8 TXT path")
    parser.add_argument("--hex-file", dest="sci8_txt", help="compatibility alias of --sci8-txt")
    parser.add_argument("--keep-sci8-txt", action="store_true", help="keep generated SCI8 TXT next to the .out file")
    parser.add_argument("--keep-hex", dest="keep_sci8_txt", action="store_true", help="compatibility alias of --keep-sci8-txt")


def _add_app(parser: argparse.ArgumentParser) -> None:
    _add_app_image(parser)
    parser.add_argument("--sector-mask", type=parse_u32, help="uint32 erase sector mask; Sector A bit0 is forbidden")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CPU1 Flash App upgrade tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  cpu1_upgrade status --port COM10\n"
            "  cpu1_upgrade attach-service --port COM10 --service-image service.out --service-map service.map\n"
            "  cpu1_upgrade erase --port COM10 --service-image service.out --service-map service.map --sector-mask 0x00000002\n"
            "  cpu1_upgrade program --port COM10 --service-image service.out --service-map service.map --app-image app.out --hex2000 <path>\n"
            "  cpu1_upgrade verify --port COM10 --service-image service.out --service-map service.map --app-image app.out --hex2000 <path>\n"
            "  cpu1_upgrade flash --port COM10 --service-image service.out --service-map service.map --app-image app.out --hex2000 <path> --sector-mask 0x00003FFE\n"
            "  cpu1_upgrade run --port COM10\n"
            "  cpu1_upgrade confirm --port COM10 --service-image service.out --service-map service.map\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, help="operation to execute")
    descriptions = {
        "status": "read metadata summary and preview confirmed-only boot policy",
        "attach-service": "load flash_service_lib into RAM and SERVICE_ATTACH it",
        "erase": "attach service and erase a manual sector mask; metadata is not written",
        "program": "attach service and Program CPU1 Flash App only; metadata is not written",
        "verify": "attach service, Verify CPU1 Flash App, then write IMAGE_VALID on success",
        "flash": "attach service, erase/program/verify App, then write IMAGE_VALID",
        "run": "append BOOT_ATTEMPT when needed and send RUN FLASH_APP",
        "confirm": "attach service and append APP_CONFIRMED for current IMAGE_VALID",
        "upgrade": "one-shot flash flow with optional RUN and APP_CONFIRM",
    }
    for name in ("status", "attach-service", "erase", "program", "verify", "flash", "run", "confirm", "upgrade"):
        cmd = sub.add_parser(name, description=descriptions[name], help=descriptions[name])
        _add_common(cmd)
        if name in {"attach-service", "erase", "program", "verify", "flash", "run", "confirm", "upgrade"}:
            _add_hex2000(cmd)
            _add_service(cmd)
        if name in {"program", "verify"}:
            _add_app_image(cmd)
        if name == "erase":
            cmd.add_argument("--sector-mask", type=parse_u32, help="uint32 erase sector mask; Sector A bit0 is forbidden")
        if name in {"flash", "upgrade"}:
            _add_app(cmd)
            cmd.add_argument("--force", action="store_true", help="force erase/program/verify even when IMAGE_VALID already matches input")
        if name == "upgrade":
            cmd.add_argument("--no-run", action="store_true", help="stop after Flash DFU and IMAGE_VALID")
            cmd.add_argument("--no-confirm", action="store_true", help="accepted for compatibility; upgrade no longer writes APP_CONFIRMED by default")
            cmd.add_argument("--dry-run", action="store_true", help="parse and validate inputs without touching the device")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")
    if args.command in {"program", "verify", "flash", "upgrade"} and not args.app_image:
        parser.error("--app-image is required")
    if args.command == "erase" and args.sector_mask is None:
        parser.error("--sector-mask is required")
    if args.command in {"attach-service", "erase", "program", "verify", "confirm"}:
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
    if result.get("service"):
        lines.append(f"Service descriptor: 0x{result['service']['descriptor_address']:08X}")
        lines.append(f"Service reused: {'yes' if result['service'].get('reused') else 'no'}")
        lines.append(f"Service attach performed: {'yes' if result['service'].get('attach_performed') else 'no'}")
    if "erase" in result:
        lines.append(f"Erase requested mask: 0x{result['erase']['requested_mask']:08X}")
        masks = ", ".join(f"0x{mask:08X}" for mask in result["erase"]["erased_masks"])
        lines.append(f"Erased masks: {masks}")
    if "program" in result:
        lines.append("Program: complete" if result["program"].get("programmed") else "Program: not complete")
    if "verify" in result:
        lines.append("Verify: complete" if result["verify"].get("verified") else "Verify: not complete")
        lines.append(
            "IMAGE_VALID: written"
            if result["verify"].get("image_valid_written")
            else "IMAGE_VALID: not written"
        )
    warning = result.get("warning")
    if warning:
        lines.append(f"WARNING[{warning['code']}]: {warning['message']}")
    if result.get("confirm_deferred"):
        lines.append(f"APP_CONFIRM deferred: {result['confirm_deferred']}")
    return "\n".join(lines)


def run_command(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "status": run_cpu1_status,
        "attach-service": run_cpu1_attach_service,
        "erase": run_cpu1_erase,
        "program": run_cpu1_program,
        "verify": run_cpu1_verify,
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
    except ValueError as exc:
        data = envelope(ok=False, tool=TOOL, command=args.command, stage="SAFETY_CHECK", error_code="SAFETY_ERROR", message=str(exc))
        print_envelope(data) if args.output == "json" else print(f"FAIL[SAFETY_CHECK/SAFETY_ERROR]: {exc}")
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
