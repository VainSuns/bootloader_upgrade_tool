from __future__ import annotations

import bootloader_upgrade_tool.cli.commands as commands
from bootloader_upgrade_tool.cli.parser import build_parser
from bootloader_upgrade_tool.cli.output import json_envelope
from bootloader_upgrade_tool.operations import OperationResult


def success(operation: str, summary: dict | None = None, details: dict | None = None) -> OperationResult:
    return OperationResult(
        True,
        operation,
        "TMS320F28377D CPU1",
        operation.upper(),
        summary or {},
        details or {},
    )


def test_status_reads_metadata_once_and_aggregates_cached_discovery(monkeypatch, command_runtime) -> None:
    calls: list[object] = []
    forbidden: list[str] = []

    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda ctx: calls.append(ctx) or success("get_metadata_summary", {"metadata_valid": 1}),
    )
    monkeypatch.setattr(commands, "get_last_error", lambda _ctx: forbidden.append("last-error"))
    monkeypatch.setattr(commands, "get_service_status", lambda _ctx: forbidden.append("service"))
    monkeypatch.setattr(commands, "memory_read", lambda *_args: forbidden.append("memory"))

    outcome = commands.handle_status(command_runtime)

    assert outcome.command == "status"
    assert outcome.operation_result is not None
    assert len(calls) == 1
    assert forbidden == []
    assert outcome.result["target"]["target_key"] == "cpu1"
    metadata = json_envelope(outcome)["result"]["metadata"]
    assert metadata["operation"] == "get_metadata_summary"
    assert metadata["target"] == "TMS320F28377D CPU1"
    assert metadata["stage"] == "GET_METADATA_SUMMARY"
    assert metadata["summary"] == {"metadata_valid": 1}
    assert metadata["completion"] == "succeeded"
    assert metadata["error"] is None
    assert metadata["summary"] != metadata


def test_device_info_uses_discovery_cache_without_a_second_operation(monkeypatch, command_runtime) -> None:
    outcome = commands.handle_device_info(command_runtime)

    assert outcome.result["device_id"] == 0x377D
    assert outcome.result["cpu_id"] == 1
    assert len(command_runtime.contexts) == 0
    assert not hasattr(commands, "get_device_info")


def test_protocol_info_uses_cached_info_and_effective_limits(command_runtime) -> None:
    outcome = commands.handle_protocol_info(command_runtime)

    assert outcome.result["protocol_ver"] == 1
    assert outcome.result["effective_max_payload_words"] == 128
    assert outcome.result["effective_max_data_words"] == 8
    assert outcome.result["effective_max_write_data_words"] == 8
    assert len(command_runtime.contexts) == 0
    assert not hasattr(commands, "get_protocol_info")


def test_last_error_calls_only_the_explicit_public_operation(monkeypatch, command_runtime) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_last_error",
        lambda ctx: calls.append(ctx) or success("get_last_error", {"operation": 3}),
    )

    outcome = commands.handle_last_error(command_runtime)

    assert outcome.operation_result is not None
    assert outcome.operation_result.summary == {"operation": 3}
    assert len(calls) == 1


def test_metadata_status_calls_get_metadata_summary_once(monkeypatch, command_runtime) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda ctx: calls.append(ctx) or success("get_metadata_summary"),
    )

    outcome = commands.handle_metadata_status(command_runtime)

    assert outcome.command == "metadata status"
    assert len(calls) == 1


def test_service_status_calls_get_service_status_without_attach(monkeypatch, command_runtime) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_service_status",
        lambda ctx: calls.append(ctx) or success("get_service_status", {"service_state": 2}),
    )

    outcome = commands.handle_service_status(command_runtime)

    assert outcome.command == "service status"
    assert outcome.operation_result.summary == {"service_state": 2}
    assert len(calls) == 1
    assert not hasattr(commands, "attach_flash_service")


def test_memory_read_builds_the_public_request_and_never_frames_it(monkeypatch, command_runtime) -> None:
    calls: list[tuple[object, object]] = []
    monkeypatch.setattr(
        commands,
        "memory_read",
        lambda ctx, request: calls.append((ctx, request))
        or success(
            "memory_read",
            {"start_address": request.start_address, "word_count": request.word_count},
            {"words": (0x1234, 0x5678)},
        ),
    )
    args = build_parser().parse_args(
        ["memory", "read", "--address", "0x82400", "--words", "2"]
    )

    outcome = commands.execute_command(command_runtime, args)

    assert len(calls) == 1
    context, request = calls[0]
    assert context is command_runtime.contexts[0]
    assert (request.start_address, request.word_count) == (0x82400, 2)
    assert outcome.operation_result is not None
