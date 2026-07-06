"""Small shared helpers for productized CPU1 CLI tools."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from ..core import ProtocolClient
from ..io import SerialIoDevice, SimulatorIoDevice


class CliToolError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        stage: str,
        device_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.stage = stage
        self.device_reason = device_reason


def parse_u32(value: str) -> int:
    result = int(value, 0)
    if result < 0 or result > 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("value must fit uint32")
    return result


def add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="output format for humans or automation (default: text)",
    )
    parser.add_argument("--json", action="store_true", help="alias of --output json")


def normalize_output(args: argparse.Namespace) -> None:
    if getattr(args, "json", False):
        args.output = "json"


def envelope(
    *,
    ok: bool,
    tool: str,
    command: str,
    stage: str,
    result: Any = None,
    error_code: str | None = None,
    message: str | None = None,
    device_reason: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"ok": ok, "tool": tool, "command": command, "stage": stage}
    if ok:
        data["result"] = to_jsonable(result)
    else:
        data.update({"error_code": error_code, "message": message})
        if device_reason is not None:
            data["device_reason"] = device_reason
    return data


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def print_envelope(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def make_client(args: argparse.Namespace, *, simulator: bool = False) -> ProtocolClient:
    device = (
        SimulatorIoDevice()
        if simulator
        else SerialIoDevice(args.port, baudrate=args.baud)
    )
    return ProtocolClient(device, default_timeout_ms=args.timeout_ms, clear_input_before_request=False)


def connect_client(client: ProtocolClient, args: argparse.Namespace) -> None:
    if args.autobaud_mode == "always":
        client.open(wait_slave_timeout_ms=args.timeout_ms, device_info_timeout_ms=args.timeout_ms)
    else:
        client.device.open()
        client.get_device_info(timeout_ms=args.timeout_ms)
