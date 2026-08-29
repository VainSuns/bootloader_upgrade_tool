from __future__ import annotations

import io
import json

from bootloader_upgrade_tool.cli.output import (
    CliError,
    CommandOutcome,
    ExitCode,
    json_envelope,
    outcome_exit_code,
    render_final,
    render_human,
)
from bootloader_upgrade_tool.operations import (
    ErrorDomain,
    OperationCancellationInfo,
    OperationCompletion,
    OperationErrorInfo,
    OperationResult,
)


def operation(
    *,
    ok: bool = True,
    error: OperationErrorInfo | None = None,
    completion: OperationCompletion | None = None,
    summary: dict | None = None,
    details: dict | None = None,
    cancellation: OperationCancellationInfo | None = None,
) -> OperationResult:
    return OperationResult(
        ok,
        "memory_read",
        "TMS320F28377D CPU1",
        "MEMORY_READ",
        summary or {},
        details or {},
        error=error,
        completion=completion,
        cancellation=cancellation,
    )


def test_json_success_has_single_stable_envelope() -> None:
    result = operation(summary={"word_count": 2}, details={"words": (1, 2)})
    payload = json_envelope(CommandOutcome("memory read", operation_result=result))

    assert payload["schema_version"] == 1
    assert payload["command"] == "memory read"
    assert payload["success"] is True
    assert payload["exit_code"] == 0
    assert payload["result"]["operation"] == "memory_read"
    assert payload["result"]["details"]["words"] == [1, 2]


def test_json_maps_operation_and_communication_failures() -> None:
    operation_failure = operation(
        ok=False,
        error=OperationErrorInfo("BAD_STATE", "bad state", "MEMORY_READ"),
    )
    communication_failure = operation(
        ok=False,
        error=OperationErrorInfo(
            "PROTOCOL_ERROR",
            "wire failed",
            "MEMORY_READ",
            domain=ErrorDomain.COMMUNICATION,
        ),
    )

    assert outcome_exit_code(CommandOutcome("memory read", operation_result=operation_failure)) == ExitCode.OPERATION_FAILURE
    assert outcome_exit_code(CommandOutcome("memory read", operation_result=communication_failure)) == ExitCode.COMMUNICATION_FAILURE
    assert json_envelope(CommandOutcome("memory read", operation_result=communication_failure))["error"]["domain"] == "communication"


def test_completed_after_cancel_is_not_a_successful_cli_command() -> None:
    cancellation = OperationCancellationInfo("MEMORY_READ", 2, 2, True, False, False)
    result = operation(
        completion=OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        cancellation=cancellation,
        summary={"word_count": 2},
    )

    payload = json_envelope(CommandOutcome("memory read", operation_result=result))

    assert payload["success"] is False
    assert payload["exit_code"] == 4
    assert outcome_exit_code(CommandOutcome("memory read", operation_result=result)) is ExitCode.CANCELLED


def test_json_cancellation_cli_usage_and_internal_errors_are_valid_documents() -> None:
    cancellation = CommandOutcome(
        "status",
        error=CliError("cli", "CANCELLED", "cancelled"),
        exit_code=ExitCode.CANCELLED,
    )
    usage = CommandOutcome(
        "status",
        error=CliError("cli", "CLI_USAGE_ERROR", "missing --port"),
        exit_code=ExitCode.CLI_USAGE_ERROR,
    )
    internal = CommandOutcome(
        "status",
        error=CliError("internal", "INTERNAL_ERROR", "bug"),
        exit_code=ExitCode.INTERNAL_ERROR,
    )

    for outcome in (cancellation, usage, internal):
        stream = io.StringIO()
        render_final(outcome, json_mode=True, stdout=stream)
        parsed = json.loads(stream.getvalue())
        assert parsed["schema_version"] == 1
        assert parsed["success"] is False
        assert parsed["error"]["code"]


def test_human_memory_dump_uses_eight_words_and_c28x_word_addresses() -> None:
    result = operation(
        summary={"start_address": 0x82400, "word_count": 10},
        details={"words": tuple(range(10))},
    )

    text = render_human(CommandOutcome("memory read", operation_result=result))

    assert "Memory Read: PASS" in text
    assert "Start: 0x00082400" in text
    assert "Words: 10" in text
    assert "00082400: 0000 0001 0002 0003 0004 0005 0006 0007" in text
    assert "00082408: 0008 0009" in text
    assert "00082400: 0000" in text
    assert "00082408" in text
    assert "00082410" not in text


def test_human_last_error_title_is_unambiguous() -> None:
    result = OperationResult(True, "get_last_error", "CPU1", "GET_LAST_ERROR", {"operation": 2})

    assert render_human(CommandOutcome("last-error", operation_result=result)).startswith(
        "Last Operation Error: PASS"
    )


def test_human_status_includes_target_limits_and_metadata() -> None:
    payload = {
        "target": {
            "target_key": "cpu1",
            "profile": "TMS320F28377D CPU1",
            "device_info": {"cpu_id": 1},
            "effective_limits": {"effective_max_payload_words": 128},
        },
        "metadata": {"metadata_valid": 1},
    }

    text = render_human(CommandOutcome("status", result=payload))

    assert "target: cpu1" in text
    assert "cpu_id: 1" in text
    assert "effective_max_payload_words: 128" in text
    assert "metadata_valid: 1" in text
