"""Entry point for the formal ``bootloader-cli`` command."""

from __future__ import annotations

import traceback
import sys
from collections.abc import Mapping
from typing import Callable, Sequence, TextIO

from ..operations import ErrorDomain, classify_exception_domain
from ..transport import TransportOpenStatus
from .commands import execute_command
from .output import CliError, CommandOutcome, ExitCode, outcome_exit_code, render_final
from .parser import CliUsageError, build_parser, command_from_argv
from .progress import ProgressRenderer
from .runtime import (
    CancellationSource,
    CliConfigurationError,
    CliRuntime,
    CliRuntimeConfig,
    RuntimeCommunicationError,
    cancellation_handler,
)


def _usage_outcome(command: str, message: str) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("cli", "CLI_USAGE_ERROR", message),
        exit_code=ExitCode.CLI_USAGE_ERROR,
    )


def _communication_outcome(command: str, message: str) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("communication", "COMMUNICATION_FAILURE", message),
        exit_code=ExitCode.COMMUNICATION_FAILURE,
    )


def _cancelled_outcome(command: str, message: str = "command cancelled cooperatively") -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("cli", "CANCELLED", message),
        exit_code=ExitCode.CANCELLED,
    )


def _internal_outcome(command: str, message: str) -> CommandOutcome:
    return CommandOutcome(
        command,
        error=CliError("internal", "INTERNAL_ERROR", message),
        exit_code=ExitCode.INTERNAL_ERROR,
    )


def _disconnect_outcome(command: str, error: Exception) -> CommandOutcome:
    domain = classify_exception_domain(error)
    if domain is None and error.__cause__ is not None:
        domain = classify_exception_domain(error.__cause__)
    if domain is ErrorDomain.COMMUNICATION:
        return _communication_outcome(command, f"disconnect failed: {error}")
    if domain is ErrorDomain.OPERATION:
        return CommandOutcome(
            command,
            error=CliError("operation", "OPERATION_FAILURE", str(error)),
            exit_code=ExitCode.OPERATION_FAILURE,
        )
    return _internal_outcome(command, f"disconnect failed: {error}")


def _human_status_outcome(outcome: CommandOutcome) -> CommandOutcome:
    if outcome.command != "status" or not isinstance(outcome.result, Mapping):
        return outcome
    metadata = outcome.result.get("metadata")
    if not isinstance(metadata, Mapping) or "summary" not in metadata:
        return outcome
    return CommandOutcome(
        outcome.command,
        result={**outcome.result, "metadata": metadata["summary"]},
        operation_result=outcome.operation_result,
        error=outcome.error,
        exit_code=outcome.exit_code,
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


def _runtime_for(
    config: CliRuntimeConfig,
    source: CancellationSource,
    runtime_factory: Callable[..., CliRuntime] | None,
) -> CliRuntime:
    if runtime_factory is None:
        return CliRuntime(config, cancellation_source=source)
    return runtime_factory(config, cancellation_source=source)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    runtime_factory: Callable[..., CliRuntime] | None = None,
) -> int:
    """Run one command and return its process exit code."""

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    output = sys.stdout if stdout is None else stdout
    diagnostics = sys.stderr if stderr is None else stderr
    json_requested = "--json" in raw_argv
    parser = build_parser()

    try:
        args = parser.parse_args(raw_argv)
    except CliUsageError as error:
        outcome = _parser_error(
            error,
            command=command_from_argv(raw_argv),
            json_mode=json_requested,
            stderr=diagnostics,
        )
        render_final(outcome, json_mode=json_requested, stdout=output)
        return int(ExitCode.CLI_USAGE_ERROR)
    except SystemExit as error:
        # ``--help`` and ``--version`` intentionally retain argparse's text behavior.
        return int(error.code or 0)

    command = args.command
    try:
        config = CliRuntimeConfig(
            transport=args.transport,
            port=args.port,
            baud=args.baud,
            timeout_ms=args.timeout_ms,
        )
        config.require_port()
    except (AttributeError, CliConfigurationError, ValueError) as error:
        outcome = _usage_outcome(command, str(error))
        render_final(outcome, json_mode=args.json, stdout=output)
        return int(ExitCode.CLI_USAGE_ERROR)

    source = CancellationSource()
    runtime: CliRuntime | None = None
    outcome: CommandOutcome | None = None
    cleanup_error: Exception | None = None
    progress = ProgressRenderer(diagnostics)

    try:
        runtime = _runtime_for(config, source, runtime_factory)
        with cancellation_handler(source):
            open_result = runtime.connect(source)
            if open_result.status is TransportOpenStatus.CANCELLED:
                outcome = _cancelled_outcome(command, f"connection cancelled during {open_result.stage}")
            elif open_result.status is TransportOpenStatus.OPENED:
                discovery = runtime.discover()
                if not discovery.result.ok:
                    outcome = CommandOutcome(command, operation_result=discovery.result)
                elif source.is_cancel_requested():
                    outcome = _cancelled_outcome(command, "cancelled after target discovery")
                else:
                    outcome = execute_command(runtime, args, progress)
            else:
                raise RuntimeError(f"unknown transport open status: {open_result.status!r}")
    except RuntimeCommunicationError as error:
        outcome = _communication_outcome(command, str(error))
    except CliConfigurationError as error:
        outcome = _usage_outcome(command, str(error))
    except Exception as error:  # unexpected programming errors remain exit code 7
        if args.verbose:
            traceback.print_exc(file=diagnostics)
        outcome = _internal_outcome(command, str(error))
    finally:
        if runtime is not None:
            try:
                runtime.disconnect()
            except Exception as error:
                cleanup_error = error
        progress.finish()

    if cleanup_error is not None:
        if args.verbose:
            traceback.print_exception(cleanup_error, file=diagnostics)
        if outcome is None or outcome_exit_code(outcome) is ExitCode.SUCCESS:
            outcome = _disconnect_outcome(command, cleanup_error)
        else:
            diagnostics.write(f"warning: disconnect failed: {cleanup_error}\n")

    if outcome is None:
        outcome = _internal_outcome(command, "command produced no outcome")
    if not args.json:
        outcome = _human_status_outcome(outcome)
    render_final(
        outcome,
        json_mode=args.json,
        verbose=args.verbose,
        stdout=output,
    )
    return int(outcome_exit_code(outcome))


__all__ = ["main"]
