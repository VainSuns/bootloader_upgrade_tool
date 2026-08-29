"""B02 command handlers built on the public operation API."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from ..operations import (
    MemoryReadRequest,
    get_last_error,
    get_metadata_summary,
    get_service_status,
    memory_read,
    operation_result_to_dict,
)
from .output import CommandOutcome


def _cached_dataclass(value: Any, name: str) -> dict[str, Any]:
    if not is_dataclass(value) or isinstance(value, type):
        raise RuntimeError(f"discovery cache does not contain typed {name}")
    return asdict(value)


def _client(runtime: Any) -> Any:
    return runtime.session.client


def _target_summary(runtime: Any) -> dict[str, Any]:
    discovered = runtime.discovered_target
    client = _client(runtime)
    device_info = discovered.device_info
    cached_device_info = client.device_info
    if cached_device_info != device_info:
        raise RuntimeError("discovery cache DeviceInfo does not match the discovered target")
    protocol_info = client.protocol_info
    if protocol_info is None:
        raise RuntimeError("discovery cache does not contain typed ProtocolInfo")
    return {
        "target_key": discovered.target_key,
        "profile": discovered.target_profile.name,
        "device_info": _cached_dataclass(device_info, "DeviceInfo"),
        "protocol_info": _cached_dataclass(protocol_info, "ProtocolInfo"),
        "effective_limits": {
            "effective_max_payload_words": client.effective_max_payload_words,
            "effective_max_data_words": client.effective_max_data_words,
            "effective_max_write_data_words": client.effective_max_write_data_words,
        },
    }


def handle_status(runtime: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    result = get_metadata_summary(runtime.operation_context(progress))
    if not result.ok:
        return CommandOutcome("status", operation_result=result)
    return CommandOutcome(
        "status",
        result={"target": _target_summary(runtime), "metadata": operation_result_to_dict(result)},
        operation_result=result,
    )


def handle_device_info(runtime: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    del progress
    info = _client(runtime).device_info
    return CommandOutcome("device-info", result=_cached_dataclass(info, "DeviceInfo"))


def handle_protocol_info(runtime: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    del progress
    client = _client(runtime)
    info = client.protocol_info
    payload = _cached_dataclass(info, "ProtocolInfo")
    payload.update(
        {
            "effective_max_payload_words": client.effective_max_payload_words,
            "effective_max_data_words": client.effective_max_data_words,
            "effective_max_write_data_words": client.effective_max_write_data_words,
        }
    )
    return CommandOutcome("protocol-info", result=payload)


def handle_last_error(runtime: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    return CommandOutcome(
        "last-error",
        operation_result=get_last_error(runtime.operation_context(progress)),
    )


def handle_metadata_status(runtime: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    return CommandOutcome(
        "metadata status",
        operation_result=get_metadata_summary(runtime.operation_context(progress)),
    )


def handle_service_status(runtime: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    return CommandOutcome(
        "service status",
        operation_result=get_service_status(runtime.operation_context(progress)),
    )


def handle_memory_read(runtime: Any, args: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    request = MemoryReadRequest(start_address=args.address, word_count=args.words)
    return CommandOutcome(
        "memory read",
        operation_result=memory_read(runtime.operation_context(progress), request),
    )


def execute_command(runtime: Any, args: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    handlers = {
        "status": lambda: handle_status(runtime, progress),
        "device-info": lambda: handle_device_info(runtime, progress),
        "protocol-info": lambda: handle_protocol_info(runtime, progress),
        "last-error": lambda: handle_last_error(runtime, progress),
        "metadata status": lambda: handle_metadata_status(runtime, progress),
        "service status": lambda: handle_service_status(runtime, progress),
        "memory read": lambda: handle_memory_read(runtime, args, progress),
    }
    try:
        handler = handlers[args.command]
    except KeyError as exc:
        raise RuntimeError(f"unsupported CLI command: {args.command!r}") from exc
    return handler()


run_command = execute_command


__all__ = [
    "execute_command",
    "handle_device_info",
    "handle_last_error",
    "handle_memory_read",
    "handle_metadata_status",
    "handle_protocol_info",
    "handle_service_status",
    "handle_status",
    "run_command",
]
