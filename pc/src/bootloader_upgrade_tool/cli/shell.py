"""Interactive shell for the formal CLI."""

from __future__ import annotations

import shlex
import sys
import traceback
from typing import Any, Callable, TextIO

from ..transport import TransportOpenStatus
from .commands import execute_command, handle_ping
from .confirmation import request_confirmation
from .output import CliError, CommandOutcome, ExitCode, outcome_exit_code, render_final
from .parser import CliArgumentParser, CliUsageError, build_parser, command_from_argv
from .progress import ProgressRenderer
from .runtime import (
    CancellationSource,
    CliConfigurationError,
    CliRuntime,
    RuntimeCommunicationError,
    cancellation_handler,
)


_SERVICE_COMMANDS = frozenset(
    {
        "erase",
        "program",
        "verify",
        "metadata image-valid",
        "metadata boot-attempt",
        "metadata app-confirmed",
        "service attach",
        "upgrade",
    }
)
_FIXED_OPTIONS = frozenset(
    {
        "--transport",
        "--port",
        "--baud",
        "--timeout-ms",
        "--json",
        "--verbose",
        "--version",
        "--help",
    }
)
_SERVICE_OPTIONS = frozenset({"--flash-service-image", "--flash-service-map"})


def _usage_outcome(command: str, message: str) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("cli", "CLI_USAGE_ERROR", message),
        exit_code=ExitCode.CLI_USAGE_ERROR,
    )


def _not_connected(command: str) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("cli", "NOT_CONNECTED", "connect to a target before running this command"),
        exit_code=ExitCode.OPERATION_FAILURE,
    )


def _service_required(command: str) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError(
            "cli",
            "SERVICE_RESOURCE_REQUIRED",
            "configure both Flash Service sources with service use before this command",
        ),
        exit_code=ExitCode.CLI_USAGE_ERROR,
    )


def _cancelled(command: str, message: str = "command cancelled cooperatively") -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("cli", "CANCELLED", message),
        exit_code=ExitCode.CANCELLED,
    )


def _communication(command: str, message: str) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("communication", "COMMUNICATION_FAILURE", message),
        exit_code=ExitCode.COMMUNICATION_FAILURE,
    )


def _internal(command: str, message: str) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("internal", "INTERNAL_ERROR", message),
        exit_code=ExitCode.INTERNAL_ERROR,
    )


def _parser_error(
    error: CliUsageError,
    *,
    command: str,
    json_mode: bool,
    stderr: TextIO,
) -> CommandOutcome:
    if not json_mode:
        stderr.write(error.parser.format_usage())
        stderr.write(f"{error.parser.prog}: error: {error.message}\n")
    return _usage_outcome(command, error.message)


def _option_name(token: str) -> str:
    if token == "-h":
        return "--help"
    return token.split("=", 1)[0] if token.startswith("--") else ""


def _fixed_option_error(tokens: list[str]) -> str | None:
    for token in tokens:
        option = _option_name(token)
        if option in _FIXED_OPTIONS:
            return f"{option} is fixed for this shell; restart the shell to change it"
    return None


def _service_option_error(tokens: list[str]) -> str | None:
    for token in tokens:
        if _option_name(token) in _SERVICE_OPTIONS:
            return "Flash Service sources are retained; use service use to replace them"
    return None


def _no_argument_command(tokens: list[str], command: str) -> CommandOutcome | None:
    if len(tokens) != 1:
        return _usage_outcome(command, f"{command} does not accept arguments")
    return None


def _help_outcome() -> CommandOutcome:
    return CommandOutcome(
        "help",
        result={
            "shell commands": (
                "connect\n"
                "disconnect\n"
                "reconnect\n"
                "ping\n"
                "service use --flash-service-image <path> --flash-service-map <path>\n"
                "help\n"
                "exit | quit"
            ),
            "target commands": (
                "status\n"
                "device-info\n"
                "protocol-info\n"
                "last-error\n"
                "erase ...\n"
                "program ...\n"
                "verify ...\n"
                "metadata status\n"
                "metadata image-valid ...\n"
                "metadata boot-attempt ...\n"
                "metadata app-confirmed ...\n"
                "service status\n"
                "service attach ...\n"
                "ram load ...\n"
                "ram check-crc ...\n"
                "memory read ...\n"
                "run ...\n"
                "run-ram ...\n"
                "upgrade ..."
            ),
            "service source": (
                "service use only stores/replaces retained Flash Service paths; "
                "it does not connect, attach, or touch the target"
            ),
            "configuration": (
                "normal target commands use the one-shot syntax; connection and "
                "global presentation options are fixed for this shell"
            ),
        },
    )


def _service_use(
    tokens: list[str],
    *,
    json_mode: bool,
    stderr: TextIO,
) -> tuple[CommandOutcome, tuple[str, str] | None]:
    parser = CliArgumentParser(prog="bootloader-cli shell service use", add_help=False)
    parser.add_argument("--flash-service-image", required=True)
    parser.add_argument("--flash-service-map", required=True)
    try:
        args = parser.parse_args(tokens[2:])
    except CliUsageError as error:
        return _parser_error(error, command="service use", json_mode=json_mode, stderr=stderr), None
    paths = (args.flash_service_image, args.flash_service_map)
    return CommandOutcome(
        "service use",
        result={
            "flash_service_image": paths[0],
            "flash_service_map": paths[1],
        },
    ), paths


def _disconnect_quiet(runtime: CliRuntime, stderr: TextIO) -> None:
    try:
        runtime.disconnect()
    except Exception as error:
        stderr.write(f"warning: disconnect failed: {error}\n")
        stderr.flush()


def _connect_and_discover(
    runtime: CliRuntime,
    source: CancellationSource,
    *,
    command: str,
    stderr: TextIO,
) -> tuple[bool, CommandOutcome]:
    try:
        opened = runtime.connect(source)
        if opened.status is TransportOpenStatus.CANCELLED:
            return False, _cancelled(command, f"connection cancelled during {opened.stage}")
        if opened.status is not TransportOpenStatus.OPENED:
            raise RuntimeError(f"unknown transport open status: {opened.status!r}")
        discovery = runtime.discover()
        if not discovery.result.ok:
            _disconnect_quiet(runtime, stderr)
            return False, CommandOutcome(command, operation_result=discovery.result)
        if source.is_cancel_requested():
            _disconnect_quiet(runtime, stderr)
            return False, _cancelled(command, "cancelled after target discovery")
        return True, CommandOutcome(command, operation_result=discovery.result)
    except RuntimeCommunicationError as error:
        _disconnect_quiet(runtime, stderr)
        return False, _communication(command, str(error))
    except CliConfigurationError as error:
        _disconnect_quiet(runtime, stderr)
        return False, _usage_outcome(command, str(error))
    except Exception as error:
        _disconnect_quiet(runtime, stderr)
        return False, _internal(command, str(error))


def _disconnect_command(runtime: CliRuntime, *, connected: bool) -> tuple[bool, CommandOutcome]:
    if not connected:
        return False, CommandOutcome("disconnect", result={"state": "disconnected"})
    try:
        runtime.disconnect()
    except RuntimeCommunicationError as error:
        return False, _communication("disconnect", str(error))
    except CliConfigurationError as error:
        return False, _usage_outcome("disconnect", str(error))
    except Exception as error:
        return False, _internal("disconnect", str(error))
    return False, CommandOutcome("disconnect", result={"state": "disconnected"})


def _reconnect(
    runtime: CliRuntime,
    source: CancellationSource,
    *,
    connected: bool,
    stderr: TextIO,
) -> tuple[bool, CommandOutcome]:
    if connected:
        try:
            runtime.disconnect()
        except RuntimeCommunicationError as error:
            return False, _communication("reconnect", str(error))
        except Exception as error:
            return False, _internal("reconnect", str(error))
    return _connect_and_discover(runtime, source, command="reconnect", stderr=stderr)


def _command_exception(
    command: str,
    error: Exception,
    *,
    verbose: bool,
    stderr: TextIO,
) -> CommandOutcome:
    if verbose:
        traceback.print_exc(file=stderr)
    if isinstance(error, RuntimeCommunicationError):
        return _communication(command, str(error))
    if isinstance(error, CliConfigurationError):
        return _usage_outcome(command, str(error))
    return _internal(command, str(error))


def _target_command(
    runtime: CliRuntime,
    tokens: list[str],
    *,
    connected: bool,
    service_paths: tuple[str, str] | None,
    progress: ProgressRenderer,
    json_mode: bool,
    verbose: bool,
    stderr: TextIO,
    run_attempt_observer: Callable[[int], None],
) -> CommandOutcome:
    command = command_from_argv(tokens)
    fixed_error = _fixed_option_error(tokens)
    if fixed_error is not None:
        return _usage_outcome(command, fixed_error)
    service_error = _service_option_error(tokens)
    if service_error is not None:
        return _usage_outcome(command, service_error)
    if tokens and tokens[0] == "shell":
        return _usage_outcome("shell", "nested shell is not allowed")

    parse_tokens = list(tokens)
    if command in _SERVICE_COMMANDS:
        image, map_path = service_paths or ("__missing_flash_service_image__", "__missing_flash_service_map__")
        parse_tokens.extend(
            [
                "--flash-service-image",
                image,
                "--flash-service-map",
                map_path,
            ]
        )
    try:
        args = build_parser(prog="bootloader-cli shell").parse_args(parse_tokens)
    except CliUsageError as error:
        return _parser_error(
            error,
            command=command,
            json_mode=json_mode,
            stderr=stderr,
        )
    except SystemExit as error:
        return _usage_outcome(command, f"shell command exited during parsing ({error.code})")

    command = args.command
    if not connected:
        return _not_connected(command)
    if command in _SERVICE_COMMANDS and service_paths is None:
        return _service_required(command)
    try:
        outcome = execute_command(
            runtime,
            args,
            progress,
            run_attempt_observer=run_attempt_observer,
        )
    except Exception as error:
        return _command_exception(command, error, verbose=verbose, stderr=stderr)
    if not isinstance(outcome, CommandOutcome):
        return _internal(command, "command handler returned an invalid outcome")
    return outcome


def _prompt(stdin: TextIO, stderr: TextIO, connected: bool) -> None:
    if getattr(stdin, "isatty", lambda: False)():
        state = "connected" if connected else "disconnected"
        stderr.write(f"bootloader[{state}]> ")
        stderr.flush()


def run_shell(
    runtime: CliRuntime,
    args: Any,
    *,
    source: CancellationSource,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run a fixed-configuration interactive shell until exit or EOF."""

    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    diagnostics = sys.stderr if stderr is None else stderr
    json_mode = bool(args.json)
    verbose = bool(args.verbose)
    service_paths: tuple[str, str] | None = None
    if args.flash_service_image is not None and args.flash_service_map is not None:
        service_paths = (args.flash_service_image, args.flash_service_map)
    progress = ProgressRenderer(diagnostics)
    connected = False
    run_attempted = False

    def mark_run_attempt(_command_id: int) -> None:
        nonlocal run_attempted
        run_attempted = True

    def confirm(details, *, assume_yes: bool = False):  # type: ignore[no-untyped-def]
        return request_confirmation(
            details,
            assume_yes=assume_yes,
            stdin=input_stream,
            stderr=diagnostics,
        )

    runtime.confirmation_requester = confirm
    generation_source = source
    try:
        generation_source = CancellationSource()
        with cancellation_handler(generation_source):
            connected, startup = _connect_and_discover(
                runtime,
                generation_source,
                command="connect",
                stderr=diagnostics,
            )
        if outcome_exit_code(startup) is not ExitCode.SUCCESS:
            render_final(startup, json_mode=json_mode, verbose=verbose, stdout=output_stream)

        while True:
            if connected:
                generation_source.reset()
            _prompt(input_stream, diagnostics, connected)
            try:
                line = input_stream.readline()
            except KeyboardInterrupt:
                continue
            if line == "":
                break
            try:
                tokens = shlex.split(line)
            except ValueError as error:
                outcome = _usage_outcome("unknown", f"invalid shell quoting: {error}")
                render_final(outcome, json_mode=json_mode, verbose=verbose, stdout=output_stream)
                continue
            if not tokens:
                continue

            run_attempted = False
            command = tokens[0]
            if command in {"exit", "quit"}:
                invalid = _no_argument_command(tokens, command)
                if invalid is not None:
                    render_final(invalid, json_mode=json_mode, verbose=verbose, stdout=output_stream)
                    continue
                break

            if command == "help":
                invalid = _no_argument_command(tokens, command)
                outcome = invalid or _help_outcome()
            elif command == "service" and len(tokens) >= 2 and tokens[1] == "use":
                fixed_error = _fixed_option_error(tokens)
                if fixed_error is not None:
                    outcome = _usage_outcome("service use", fixed_error)
                else:
                    outcome, replacement = _service_use(
                        tokens,
                        json_mode=json_mode,
                        stderr=diagnostics,
                    )
                    if replacement is not None:
                        service_paths = replacement
            elif command == "connect":
                invalid = _no_argument_command(tokens, command)
                if invalid is not None:
                    outcome = invalid
                elif connected:
                    outcome = CommandOutcome(
                        "connect",
                        error=CliError("cli", "ALREADY_CONNECTED", "the shell is already connected"),
                        exit_code=ExitCode.OPERATION_FAILURE,
                    )
                else:
                    generation_source = CancellationSource()
                    with cancellation_handler(generation_source):
                        connected, outcome = _connect_and_discover(
                            runtime,
                            generation_source,
                            command="connect",
                            stderr=diagnostics,
                        )
            elif command == "disconnect":
                invalid = _no_argument_command(tokens, command)
                if invalid is not None:
                    outcome = invalid
                else:
                    connected, outcome = _disconnect_command(runtime, connected=connected)
            elif command == "reconnect":
                invalid = _no_argument_command(tokens, command)
                if invalid is not None:
                    outcome = invalid
                else:
                    generation_source = CancellationSource()
                    with cancellation_handler(generation_source):
                        connected, outcome = _reconnect(
                            runtime,
                            generation_source,
                            connected=connected,
                            stderr=diagnostics,
                        )
            elif command == "ping":
                invalid = _no_argument_command(tokens, command)
                if invalid is not None:
                    outcome = invalid
                elif not connected:
                    outcome = _not_connected("ping")
                else:
                    try:
                        with cancellation_handler(generation_source):
                            outcome = handle_ping(runtime, progress)
                    except Exception as error:
                        outcome = _command_exception(
                            "ping",
                            error,
                            verbose=verbose,
                            stderr=diagnostics,
                        )
            else:
                try:
                    with cancellation_handler(generation_source):
                        outcome = _target_command(
                            runtime,
                            tokens,
                            connected=connected,
                            service_paths=service_paths,
                            progress=progress,
                            json_mode=json_mode,
                            verbose=verbose,
                            stderr=diagnostics,
                            run_attempt_observer=mark_run_attempt,
                        )
                finally:
                    if run_attempted:
                        _disconnect_quiet(runtime, diagnostics)
                        connected = False
            progress.finish()
            render_final(outcome, json_mode=json_mode, verbose=verbose, stdout=output_stream)
    finally:
        if connected:
            _disconnect_quiet(runtime, diagnostics)
        progress.finish()
    return int(ExitCode.SUCCESS)


__all__ = ["run_shell"]
