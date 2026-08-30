"""CLI command handlers built on image preparation and public operations."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from collections.abc import Callable, Mapping
from typing import Any

from ..firmware import Hex2000Error
from ..images import prepare_flash_app_image, prepare_service_image
from ..operations import (
    EraseFlashImageAreaRequest,
    EraseSectorMaskRequest,
    MemoryReadRequest,
    ProgramFlashImageRequest,
    VerifyFlashImageRequest,
    attach_flash_service,
    erase_flash_image_area,
    erase_sector_mask,
    get_last_error,
    get_metadata_summary,
    get_service_status,
    memory_read,
    operation_result_to_dict,
    program_flash_image,
    verify_flash_image,
)
from .confirmation import ConfirmationDecision, request_confirmation
from .output import CliError, CommandOutcome, ExitCode


_PREPARATION_ERRORS = (OSError, ValueError, Hex2000Error)


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


def _cancelled_outcome(command: str, message: str = "command cancelled cooperatively") -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("cli", "CANCELLED", message),
        exit_code=ExitCode.CANCELLED,
    )


def _preparation_failure(command: str, exc: Exception) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError(
            "operation",
            "RESOURCE_PREPARATION_FAILED",
            str(exc),
            details={"exception_type": type(exc).__name__},
        ),
        exit_code=ExitCode.OPERATION_FAILURE,
    )


def _unsupported(command: str, message: str) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("operation", "UNSUPPORTED_OPERATION", message),
        exit_code=ExitCode.OPERATION_FAILURE,
    )


def _cancel_requested(runtime: Any) -> bool:
    token = getattr(runtime, "cancellation", None)
    return token is not None and token.is_cancel_requested()


def _prepare_service(runtime: Any, args: Any, command: str):
    try:
        return prepare_service_image(
            args.flash_service_image,
            args.flash_service_map,
            target=runtime.target,
        ), None
    except _PREPARATION_ERRORS as exc:
        return None, _preparation_failure(command, exc)


def _prepare_app(runtime: Any, args: Any, command: str):
    try:
        return prepare_flash_app_image(args.image, target=runtime.target), None
    except _PREPARATION_ERRORS as exc:
        return None, _preparation_failure(command, exc)


def _confirmation_outcome(
    command: str,
    details: Mapping[str, Any],
    *,
    assume_yes: bool,
    requester: Callable[..., ConfirmationDecision] | None,
) -> CommandOutcome | None:
    if assume_yes:
        return None
    confirm = requester or request_confirmation
    decision = confirm(details, assume_yes=assume_yes)
    if decision is ConfirmationDecision.APPROVED:
        return None
    if decision is ConfirmationDecision.CONFIRMATION_REQUIRED:
        return CommandOutcome(
            command,
            error=CliError(
                "cli",
                "CONFIRMATION_REQUIRED",
                "interactive confirmation is required; pass --yes",
            ),
            exit_code=ExitCode.CONFIRMATION_REQUIRED,
        )
    return CommandOutcome(
        command,
        error=CliError("cli", "USER_DECLINED", "user declined the operation"),
        exit_code=ExitCode.USER_DECLINED,
    )


def _service_details(runtime: Any, args: Any, command: str) -> dict[str, Any]:
    return {
        "command": command,
        "connected target": runtime.target.name,
        "Flash Service image path": args.flash_service_image,
        "Flash Service map path": args.flash_service_map,
    }


def _app_details(details: dict[str, Any], args: Any, image: Any) -> None:
    details.update(
        {
            "App path": args.image,
            "entry point": image.identity.entry_point,
            "image CRC": image.identity.image_crc32,
            "image size": image.identity.image_size_words,
        }
    )


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


def handle_service_attach(
    runtime: Any,
    args: Any,
    progress=None,
) -> CommandOutcome:  # type: ignore[no-untyped-def]
    command = "service attach"
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled before Flash Service preparation")
    service, failure = _prepare_service(runtime, args, command)
    if failure is not None:
        return failure
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled after Flash Service preparation")
    context = runtime.flash_operation_context(service, progress)
    return CommandOutcome(command, operation_result=attach_flash_service(context))


def handle_erase(
    runtime: Any,
    args: Any,
    progress=None,
    *,
    confirmation_requester: Callable[..., ConfirmationDecision] | None = None,
) -> CommandOutcome:  # type: ignore[no-untyped-def]
    command = "erase"
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled before Flash preparation")

    if args.image is not None:
        service, failure = _prepare_service(runtime, args, command)
        if failure is not None:
            return failure
        if _cancel_requested(runtime):
            return _cancelled_outcome(command, "cancelled after Flash Service preparation")
        image, failure = _prepare_app(runtime, args, command)
        if failure is not None:
            return failure
        if _cancel_requested(runtime):
            return _cancelled_outcome(command, "cancelled after Flash App preparation")
        details = _service_details(runtime, args, command)
        _app_details(details, args, image)
        details["sector mask"] = image.sector_mask
        request = EraseFlashImageAreaRequest(image)
    elif args.all_app:
        flash = runtime.target.memory_map.flash
        if flash is None:
            return _unsupported(command, "active target does not define a Flash layout")
        service, failure = _prepare_service(runtime, args, command)
        if failure is not None:
            return failure
        if _cancel_requested(runtime):
            return _cancelled_outcome(command, "cancelled after Flash Service preparation")
        details = _service_details(runtime, args, command)
        details["sector mask"] = flash.allowed_erase_mask
        request = EraseSectorMaskRequest(flash.allowed_erase_mask)
    else:
        service, failure = _prepare_service(runtime, args, command)
        if failure is not None:
            return failure
        if _cancel_requested(runtime):
            return _cancelled_outcome(command, "cancelled after Flash Service preparation")
        details = _service_details(runtime, args, command)
        details["sector mask"] = args.sector_mask
        request = EraseSectorMaskRequest(args.sector_mask)

    confirmation_failure = _confirmation_outcome(
        command,
        details,
        assume_yes=getattr(args, "yes", False),
        requester=confirmation_requester,
    )
    if confirmation_failure is not None:
        return confirmation_failure
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled before Flash mutation")

    context = runtime.flash_operation_context(service, progress)
    if args.image is not None:
        operation = erase_flash_image_area(context, request)
    else:
        operation = erase_sector_mask(context, request)
    return CommandOutcome(command, operation_result=operation)


def handle_program(
    runtime: Any,
    args: Any,
    progress=None,
    *,
    confirmation_requester: Callable[..., ConfirmationDecision] | None = None,
) -> CommandOutcome:  # type: ignore[no-untyped-def]
    command = "program"
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled before Flash preparation")
    service, failure = _prepare_service(runtime, args, command)
    if failure is not None:
        return failure
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled after Flash Service preparation")
    image, failure = _prepare_app(runtime, args, command)
    if failure is not None:
        return failure
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled after Flash App preparation")

    details = _service_details(runtime, args, command)
    _app_details(details, args, image)
    details["semantics"] = "PROGRAM only"
    confirmation_failure = _confirmation_outcome(
        command,
        details,
        assume_yes=getattr(args, "yes", False),
        requester=confirmation_requester,
    )
    if confirmation_failure is not None:
        return confirmation_failure
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled before Flash mutation")

    context = runtime.flash_operation_context(service, progress)
    return CommandOutcome(
        command,
        operation_result=program_flash_image(context, ProgramFlashImageRequest(image)),
    )


def handle_verify(runtime: Any, args: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    command = "verify"
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled before Flash preparation")
    service, failure = _prepare_service(runtime, args, command)
    if failure is not None:
        return failure
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled after Flash Service preparation")
    image, failure = _prepare_app(runtime, args, command)
    if failure is not None:
        return failure
    if _cancel_requested(runtime):
        return _cancelled_outcome(command, "cancelled after Flash App preparation")
    context = runtime.flash_operation_context(service, progress)
    return CommandOutcome(
        command,
        operation_result=verify_flash_image(context, VerifyFlashImageRequest(image)),
    )


def handle_memory_read(runtime: Any, args: Any, progress=None) -> CommandOutcome:  # type: ignore[no-untyped-def]
    request = MemoryReadRequest(start_address=args.address, word_count=args.words)
    return CommandOutcome(
        "memory read",
        operation_result=memory_read(runtime.operation_context(progress), request),
    )


def execute_command(
    runtime: Any,
    args: Any,
    progress=None,
    *,
    confirmation_requester: Callable[..., ConfirmationDecision] | None = None,
) -> CommandOutcome:  # type: ignore[no-untyped-def]
    handlers = {
        "status": lambda: handle_status(runtime, progress),
        "device-info": lambda: handle_device_info(runtime, progress),
        "protocol-info": lambda: handle_protocol_info(runtime, progress),
        "last-error": lambda: handle_last_error(runtime, progress),
        "metadata status": lambda: handle_metadata_status(runtime, progress),
        "service status": lambda: handle_service_status(runtime, progress),
        "service attach": lambda: handle_service_attach(runtime, args, progress),
        "erase": lambda: handle_erase(
            runtime,
            args,
            progress,
            confirmation_requester=confirmation_requester
            or getattr(runtime, "confirmation_requester", None),
        ),
        "program": lambda: handle_program(
            runtime,
            args,
            progress,
            confirmation_requester=confirmation_requester
            or getattr(runtime, "confirmation_requester", None),
        ),
        "verify": lambda: handle_verify(runtime, args, progress),
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
    "handle_erase",
    "handle_device_info",
    "handle_last_error",
    "handle_memory_read",
    "handle_metadata_status",
    "handle_protocol_info",
    "handle_program",
    "handle_service_attach",
    "handle_service_status",
    "handle_status",
    "handle_verify",
    "run_command",
]
