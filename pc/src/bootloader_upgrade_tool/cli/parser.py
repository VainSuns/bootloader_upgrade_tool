"""Argument parsing for the formal CLI."""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path
import tomllib
from typing import Sequence


COMMANDS = (
    "status",
    "device-info",
    "protocol-info",
    "last-error",
    "erase",
    "program",
    "verify",
    "metadata status",
    "metadata image-valid",
    "metadata boot-attempt",
    "metadata app-confirmed",
    "service status",
    "service attach",
    "memory read",
    "run",
)

_UINT32_MAX = 0xFFFFFFFF


class CliUsageError(SystemExit):
    """A parser error that can be rendered without contaminating JSON stdout."""

    def __init__(self, message: str, parser: argparse.ArgumentParser) -> None:
        super().__init__(2)
        self.message = message
        self.parser = parser


class CliArgumentParser(argparse.ArgumentParser):
    """Argparse parser with deferred, caller-owned error rendering."""

    def error(self, message: str) -> None:
        raise CliUsageError(message, self)

    def parse_args(self, args=None, namespace=None):  # type: ignore[no-untyped-def]
        parsed = super().parse_args(args, namespace)
        if getattr(parsed, "command", None) == "memory read":
            address = parsed.address
            words = parsed.words
            if address + words - 1 > _UINT32_MAX:
                self.error("memory read exceeds the uint32 address space")
        return parsed


def positive_int(value: str) -> int:
    """Parse a strictly positive integer."""

    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def uint32(value: str) -> int:
    """Parse an integer in the inclusive uint32 range."""

    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a uint32 integer") from exc
    if not 0 <= parsed <= _UINT32_MAX:
        raise argparse.ArgumentTypeError("must fit uint32")
    return parsed


def _positive_uint32(value: str) -> int:
    parsed = positive_int(value)
    if parsed > _UINT32_MAX:
        raise argparse.ArgumentTypeError("must fit uint32")
    return parsed


def _add_global_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "--transport",
        choices=("serial",),
        default="serial" if not suppress_defaults else default,
        help="transport provider (currently only serial)",
    )
    parser.add_argument(
        "--port",
        default=default,
        help="serial port (required for command execution)",
    )
    parser.add_argument(
        "--baud",
        type=positive_int,
        default=9600 if not suppress_defaults else default,
        help="serial baud rate (default: 9600)",
    )
    parser.add_argument(
        "--timeout-ms",
        dest="timeout_ms",
        type=positive_int,
        default=None if not suppress_defaults else default,
        help="override serial TX/RX/autobaud timeouts",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if not suppress_defaults else default,
        help="render the final result as JSON",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False if not suppress_defaults else default,
        help="include verbose diagnostics on stderr",
    )


def _leaf_parser(
    parent: argparse.ArgumentParser,
    name: str,
    command: str,
    *,
    help_text: str,
) -> argparse.ArgumentParser:
    parser = parent.add_parser(name, help=help_text, description=help_text)
    _add_global_options(parser, suppress_defaults=True)
    parser.set_defaults(command=command)
    return parser


def _add_service_resource_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--flash-service-image",
        required=True,
        help="Flash Service image path",
    )
    parser.add_argument(
        "--flash-service-map",
        required=True,
        help="Flash Service map path",
    )


def build_parser(*, prog: str = "bootloader-cli", version: str | None = None) -> CliArgumentParser:
    """Build the formal CLI command tree."""

    parser = CliArgumentParser(
        prog=prog,
        description="CLI commands for the DSP28377D bootloader",
    )
    _add_global_options(parser, suppress_defaults=False)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version or project_version()}",
    )
    subparsers = parser.add_subparsers(dest="command_group", required=True, metavar="COMMAND")

    for name, help_text in (
        ("status", "show target and metadata status"),
        ("device-info", "show cached discovered device information"),
        ("protocol-info", "show cached discovered protocol information"),
        ("last-error", "read the bootloader's last operation error"),
    ):
        _leaf_parser(subparsers, name, name, help_text=help_text)

    metadata_parser = subparsers.add_parser(
        "metadata",
        help="metadata commands",
        description="Metadata diagnostics",
    )
    _add_global_options(metadata_parser, suppress_defaults=True)
    metadata_parser.set_defaults(command_group="metadata")
    metadata_subparsers = metadata_parser.add_subparsers(dest="subcommand", required=True, metavar="COMMAND")
    _leaf_parser(
        metadata_subparsers,
        "status",
        "metadata status",
        help_text="show metadata summary",
    )
    image_valid_parser = _leaf_parser(
        metadata_subparsers,
        "image-valid",
        "metadata image-valid",
        help_text="publish IMAGE_VALID for a Flash App image",
    )
    image_valid_parser.add_argument("--image", required=True, help="Flash App image path")
    _add_service_resource_options(image_valid_parser)
    image_valid_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive confirmation",
    )
    boot_attempt_parser = _leaf_parser(
        metadata_subparsers,
        "boot-attempt",
        "metadata boot-attempt",
        help_text="append one BOOT_ATTEMPT for the current IMAGE_VALID",
    )
    _add_service_resource_options(boot_attempt_parser)
    boot_attempt_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive confirmation",
    )
    app_confirmed_parser = _leaf_parser(
        metadata_subparsers,
        "app-confirmed",
        "metadata app-confirmed",
        help_text="append APP_CONFIRMED for the current IMAGE_VALID",
    )
    _add_service_resource_options(app_confirmed_parser)
    app_confirmed_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive confirmation",
    )

    service_parser = subparsers.add_parser(
        "service",
        help="Flash Service commands",
        description="Flash Service diagnostics",
    )
    _add_global_options(service_parser, suppress_defaults=True)
    service_parser.set_defaults(command_group="service")
    service_subparsers = service_parser.add_subparsers(dest="subcommand", required=True, metavar="COMMAND")
    _leaf_parser(
        service_subparsers,
        "status",
        "service status",
        help_text="read Flash Service status",
    )
    service_attach_parser = _leaf_parser(
        service_subparsers,
        "attach",
        "service attach",
        help_text="ensure the requested Flash Service is attached",
    )
    _add_service_resource_options(service_attach_parser)

    erase_parser = _leaf_parser(
        subparsers,
        "erase",
        "erase",
        help_text="erase Flash sectors",
    )
    _add_service_resource_options(erase_parser)
    erase_selectors = erase_parser.add_mutually_exclusive_group(required=True)
    erase_selectors.add_argument("--image", help="Flash App image path")
    erase_selectors.add_argument(
        "--all-app",
        action="store_true",
        help="erase the active Target's entire application region",
    )
    erase_selectors.add_argument(
        "--sector-mask",
        type=uint32,
        help="explicit Flash sector mask (uint32; accepts 0x notation)",
    )
    erase_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive confirmation",
    )

    program_parser = _leaf_parser(
        subparsers,
        "program",
        "program",
        help_text="program a Flash App image",
    )
    program_parser.add_argument("--image", required=True, help="Flash App image path")
    _add_service_resource_options(program_parser)
    program_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive confirmation",
    )

    verify_parser = _leaf_parser(
        subparsers,
        "verify",
        "verify",
        help_text="verify a Flash App image",
    )
    verify_parser.add_argument("--image", required=True, help="Flash App image path")
    _add_service_resource_options(verify_parser)

    memory_parser = subparsers.add_parser(
        "memory",
        help="memory commands",
        description="Word-addressed memory diagnostics",
    )
    _add_global_options(memory_parser, suppress_defaults=True)
    memory_parser.set_defaults(command_group="memory")
    memory_subparsers = memory_parser.add_subparsers(dest="subcommand", required=True, metavar="COMMAND")
    memory_read_parser = _leaf_parser(
        memory_subparsers,
        "read",
        "memory read",
        help_text="read C28x word-addressed memory",
    )
    memory_read_parser.add_argument(
        "--address",
        type=uint32,
        required=True,
        help="C28x word address (uint32; accepts 0x notation)",
    )
    memory_read_parser.add_argument(
        "--words",
        type=_positive_uint32,
        required=True,
        help="number of 16-bit words (positive uint32)",
    )

    run_parser = _leaf_parser(
        subparsers,
        "run",
        "run",
        help_text="explicitly run the Flash App from current metadata",
    )
    run_parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive confirmation",
    )

    return parser


def parse_cli_args(argv: Sequence[str] | None = None):  # type: ignore[no-untyped-def]
    return build_parser().parse_args(argv)


# Small aliases make the parser convenient to use from tests and integrations.
create_parser = build_parser
parse_args = parse_cli_args


def command_from_argv(argv: Sequence[str]) -> str:
    """Best-effort command label for parser/configuration error envelopes."""

    values = list(argv)
    if "memory" in values and "read" in values:
        return "memory read"
    if "metadata" in values:
        for subcommand in ("status", "image-valid", "boot-attempt", "app-confirmed"):
            if subcommand in values:
                return f"metadata {subcommand}"
    if "service" in values:
        if "attach" in values:
            return "service attach"
        if "status" in values:
            return "service status"
    if "run" in values:
        return "run"
    for command in (
        "status",
        "device-info",
        "protocol-info",
        "last-error",
        "erase",
        "program",
        "verify",
    ):
        if command in values:
            return command
    return "unknown"


def project_version() -> str:
    """Read the installed distribution version, with a source-tree fallback."""

    distribution = "dsp28377d-bootloader-upgrade-tool"
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        pass

    pyproject = Path(__file__).resolve().parents[4] / "pyproject.toml"
    try:
        with pyproject.open("rb") as stream:
            version = tomllib.load(stream)["project"]["version"]
    except (FileNotFoundError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return "unknown"
    return str(version)


__all__ = [
    "COMMANDS",
    "CliArgumentParser",
    "CliUsageError",
    "build_parser",
    "command_from_argv",
    "create_parser",
    "parse_args",
    "parse_cli_args",
    "positive_int",
    "project_version",
    "uint32",
]
