"""Human and machine-readable final output for the formal CLI."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, IntEnum
import json
import sys
from typing import Any, Mapping, TextIO

from ..operations import ErrorDomain, OperationCompletion, OperationResult, operation_result_to_dict


class ExitCode(IntEnum):
    SUCCESS = 0
    OPERATION_FAILURE = 1
    CLI_USAGE_ERROR = 2
    COMMUNICATION_FAILURE = 3
    CANCELLED = 4
    CONFIRMATION_REQUIRED = 5
    USER_DECLINED = 6
    INTERNAL_ERROR = 7


@dataclass(frozen=True, slots=True)
class CliError:
    domain: str
    code: str
    message: str
    details: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    command: str
    result: Any = None
    operation_result: OperationResult | None = None
    error: CliError | None = None
    exit_code: ExitCode | None = None


def operation_exit_code(result: OperationResult) -> ExitCode:
    if result.completion in (
        OperationCompletion.CANCELLED,
        OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
    ):
        return ExitCode.CANCELLED
    if result.ok and result.completion is OperationCompletion.SUCCEEDED:
        return ExitCode.SUCCESS
    if result.error is not None and result.error.domain is ErrorDomain.COMMUNICATION:
        return ExitCode.COMMUNICATION_FAILURE
    return ExitCode.OPERATION_FAILURE


def outcome_exit_code(outcome: CommandOutcome) -> ExitCode:
    if outcome.exit_code is not None:
        return ExitCode(outcome.exit_code)
    if outcome.operation_result is not None:
        return operation_exit_code(outcome.operation_result)
    if outcome.error is not None:
        return ExitCode.INTERNAL_ERROR
    return ExitCode.SUCCESS


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def json_envelope(outcome: CommandOutcome) -> dict[str, Any]:
    code = outcome_exit_code(outcome)
    operation = outcome.operation_result
    success = code is ExitCode.SUCCESS

    result = outcome.result
    if result is None and operation is not None:
        result = operation_result_to_dict(operation)

    envelope: dict[str, Any] = {
        "schema_version": 1,
        "command": outcome.command,
        "success": success,
        "exit_code": int(code),
    }
    if result is not None:
        envelope["result"] = _plain(result)

    if not success:
        if outcome.error is not None:
            error = {
                "domain": outcome.error.domain,
                "code": outcome.error.code,
                "message": outcome.error.message,
            }
            if outcome.error.details is not None:
                error["details"] = _plain(outcome.error.details)
            envelope["error"] = error
        elif operation is not None and operation.error is not None:
            envelope["error"] = _plain(operation.error)
        elif operation is not None and operation.completion in (
            OperationCompletion.CANCELLED,
            OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        ):
            envelope["error"] = {
                "domain": "cli",
                "code": "CANCELLED",
                "message": "command cancelled cooperatively",
            }
        else:
            envelope["error"] = {
                "domain": "internal",
                "code": "INTERNAL_ERROR",
                "message": "command failed without error details",
            }
    return envelope


def render_json(outcome: CommandOutcome, stream: TextIO | None = None) -> None:
    stream = sys.stdout if stream is None else stream
    json.dump(json_envelope(outcome), stream, ensure_ascii=False)
    stream.write("\n")
    stream.flush()


def _format_value(key: str, value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        lowered = key.lower()
        if lowered in {"device_id", "latest_record_type", "service_state"}:
            return f"0x{value:04X}"
        if lowered.endswith("address") or lowered.endswith("_address"):
            return f"0x{value:08X}"
        if "crc32" in lowered or lowered in {"uid_unique", "revision_id"}:
            return f"0x{value:08X}"
        return str(value)
    if isinstance(value, (list, tuple)):
        return " ".join(_format_value(key, item) for item in value)
    return str(value)


def _render_mapping(data: Mapping[str, Any], *, indent: str = "") -> list[str]:
    lines: list[str] = []
    for key, value in data.items():
        label = str(key)
        if isinstance(value, Mapping):
            lines.append(f"{indent}{label}:")
            lines.extend(_render_mapping(value, indent=indent + "  "))
        else:
            lines.append(f"{indent}{label}: {_format_value(label, value)}")
    return lines


def _label(command: str) -> str:
    return " ".join(part.replace("-", " ").capitalize() for part in command.split())


def _render_operation_failure(outcome: CommandOutcome, *, verbose: bool) -> list[str]:
    operation = outcome.operation_result
    code = outcome_exit_code(outcome)
    title = "Last Operation Error" if outcome.command == "last-error" else _label(outcome.command)
    if code is ExitCode.CANCELLED:
        lines = [f"{title}: CANCELLED"]
        if operation is not None and operation.cancellation is not None:
            lines.append(f"stage: {operation.cancellation.stage}")
        elif outcome.error is not None:
            lines.append(f"error: {outcome.error.message}")
        return lines

    lines = [f"{title}: FAIL"]
    if outcome.error is not None:
        lines.extend(
            [f"error: {outcome.error.code}", f"message: {outcome.error.message}"]
        )
    elif operation is not None and operation.error is not None:
        lines.extend(
            [
                f"error: {operation.error.code}",
                f"message: {operation.error.message}",
                f"domain: {operation.error.domain.value}",
            ]
        )
    else:
        lines.append("error: internal failure without details")
    if verbose and operation is not None:
        lines.append(f"stage: {operation.stage}")
    return lines


def _render_memory(outcome: CommandOutcome) -> list[str]:
    operation = outcome.operation_result
    data = outcome.result
    if data is None and operation is not None:
        data = operation_result_to_dict(operation)
    if not isinstance(data, Mapping):
        return [f"Memory Read: PASS"]

    summary = operation.summary if operation is not None else data
    start = int(summary.get("start_address", 0))
    words = int(summary.get("word_count", 0))
    raw_words = operation.details.get("words", ()) if operation is not None else data.get("words", ())
    values = [int(word) for word in raw_words]
    lines = ["Memory Read: PASS", f"Start: 0x{start:08X}", f"Words: {words}", ""]
    for offset in range(0, len(values), 8):
        address = start + offset
        chunk = values[offset : offset + 8]
        lines.append(f"{address:08X}: " + " ".join(f"{word & 0xFFFF:04X}" for word in chunk))
    return lines


def _render_status(outcome: CommandOutcome) -> list[str]:
    payload = outcome.result
    if not isinstance(payload, Mapping):
        return ["Status: PASS"]
    target = payload.get("target", {})
    metadata = payload.get("metadata", {})
    lines = ["Status: PASS"]
    if isinstance(target, Mapping):
        lines.append(f"target: {_format_value('target', target.get('target_key'))}")
        lines.append(f"device: {_format_value('profile', target.get('profile'))}")
        device = target.get("device_info", {})
        if isinstance(device, Mapping):
            lines.append(f"cpu_id: {_format_value('cpu_id', device.get('cpu_id'))}")
        limits = target.get("effective_limits", {})
        if isinstance(limits, Mapping):
            lines.append("effective protocol limits:")
            lines.extend(_render_mapping(limits, indent="  "))
    lines.append("metadata:")
    if isinstance(metadata, Mapping):
        lines.extend(_render_mapping(metadata, indent="  "))
    return lines


def render_human(outcome: CommandOutcome, *, verbose: bool = False) -> str:
    if outcome_exit_code(outcome) is not ExitCode.SUCCESS:
        return "\n".join(_render_operation_failure(outcome, verbose=verbose)) + "\n"

    if outcome.command == "memory read":
        lines = _render_memory(outcome)
    elif outcome.command == "status":
        lines = _render_status(outcome)
    else:
        label = "Last Operation Error" if outcome.command == "last-error" else _label(outcome.command)
        lines = [f"{label}: PASS"]
        payload = outcome.result
        if payload is None and outcome.operation_result is not None:
            payload = outcome.operation_result.summary
        if isinstance(payload, Mapping):
            lines.extend(_render_mapping(payload))
        if verbose and outcome.operation_result is not None:
            lines.append(f"stage: {outcome.operation_result.stage}")
    return "\n".join(lines) + "\n"


def render_final(
    outcome: CommandOutcome,
    *,
    json_mode: bool,
    verbose: bool = False,
    stdout: TextIO | None = None,
) -> None:
    if json_mode:
        render_json(outcome, stdout)
    else:
        stream = sys.stdout if stdout is None else stdout
        stream.write(render_human(outcome, verbose=verbose))
        stream.flush()


__all__ = [
    "CliError",
    "CommandOutcome",
    "ExitCode",
    "json_envelope",
    "operation_exit_code",
    "outcome_exit_code",
    "render_final",
    "render_human",
    "render_json",
]
