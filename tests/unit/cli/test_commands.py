from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import bootloader_upgrade_tool.cli.commands as commands
from bootloader_upgrade_tool.cli.confirmation import ConfirmationDecision
from bootloader_upgrade_tool.cli.parser import build_parser
from bootloader_upgrade_tool.cli.output import ExitCode, json_envelope, outcome_exit_code
from bootloader_upgrade_tool.cli.runtime import CancellationSource
from bootloader_upgrade_tool.operations import ErrorDomain, OperationErrorInfo, OperationResult
from bootloader_upgrade_tool.targets import CPU1_PROFILE


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


def _metadata_summary(runtime, **overrides):
    info = runtime.discovered_target.device_info
    flash = runtime.target.memory_map.flash
    assert flash is not None
    summary = {
        "metadata_valid": 1,
        "state": 1,
        "entry_point": flash.app_ranges[0].start,
        "image_size_words": 16,
        "image_crc32": 0xABCDEF01,
        "target_device_id": info.device_id,
        "target_cpu_id": info.cpu_id,
        "boot_attempt_count": 0,
        "app_confirmed": 0,
        "latest_record_type": 0,
    }
    summary.update(overrides)
    return summary


def test_metadata_image_valid_prepares_app_confirms_then_appends_only_image_valid(
    monkeypatch,
    flash_runtime,
) -> None:
    service = _prepared_service()
    image = _prepared_app()
    events: list[str] = []
    calls: list[object] = []
    metadata_reads: list[object] = []
    attach_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda context: metadata_reads.append(context),
    )
    monkeypatch.setattr(
        commands,
        "attach_flash_service",
        lambda context: attach_calls.append(context),
    )
    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: events.append("service") or service,
    )
    monkeypatch.setattr(
        commands,
        "prepare_flash_app_image",
        lambda *_args, **_kwargs: events.append("app") or image,
    )

    def approve(details, *, assume_yes):
        events.append("confirmation")
        assert assume_yes is False
        assert "without verifying Flash" in details["warning"]
        assert metadata_reads == []
        assert attach_calls == []
        return ConfirmationDecision.APPROVED

    result = success("append_image_valid", {"written": True})
    monkeypatch.setattr(
        commands,
        "append_image_valid",
        lambda context, request: events.append("append") or calls.append((context, request)) or result,
    )
    monkeypatch.setattr(
        commands,
        "verify_flash_image",
        lambda *_args: (_ for _ in ()).throw(AssertionError("IMAGE_VALID does not verify")),
    )
    monkeypatch.setattr(
        commands,
        "append_boot_attempt",
        lambda *_args: (_ for _ in ()).throw(AssertionError("IMAGE_VALID does not append BOOT_ATTEMPT")),
    )
    monkeypatch.setattr(
        commands,
        "append_app_confirmed",
        lambda *_args: (_ for _ in ()).throw(AssertionError("IMAGE_VALID does not append APP_CONFIRMED")),
    )
    monkeypatch.setattr(
        commands,
        "run_flash_app",
        lambda *_args: (_ for _ in ()).throw(AssertionError("IMAGE_VALID does not RUN")),
    )

    outcome = commands.handle_metadata_image_valid(
        flash_runtime,
        _args("metadata image-valid"),
        confirmation_requester=approve,
    )

    assert events == ["service", "app", "confirmation", "append"]
    assert len(calls) == 1
    assert calls[0][0].service is service
    assert calls[0][1].image is image
    assert outcome.operation_result is result
    assert metadata_reads == []
    assert attach_calls == []


@pytest.mark.parametrize(
    ("handler_name", "command", "operation_name", "warning_text"),
    [
        (
            "handle_metadata_boot_attempt",
            "metadata boot-attempt",
            "append_boot_attempt",
            "consumes an attempt slot",
        ),
        (
            "handle_metadata_app_confirmed",
            "metadata app-confirmed",
            "append_app_confirmed",
            "bypasses normal App self-confirmation",
        ),
    ],
)
def test_metadata_mutations_prepare_only_service_and_append_named_record(
    monkeypatch,
    flash_runtime,
    handler_name: str,
    command: str,
    operation_name: str,
    warning_text: str,
) -> None:
    service = _prepared_service()
    events: list[str] = []
    calls: list[object] = []
    metadata_reads: list[object] = []
    attach_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda context: metadata_reads.append(context),
    )
    monkeypatch.setattr(
        commands,
        "attach_flash_service",
        lambda context: attach_calls.append(context),
    )
    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: events.append("service") or service,
    )
    monkeypatch.setattr(
        commands,
        "prepare_flash_app_image",
        lambda *_args: (_ for _ in ()).throw(AssertionError("metadata mutation does not prepare App")),
    )

    def approve(details, *, assume_yes):
        events.append("confirmation")
        assert assume_yes is False
        assert warning_text in details["warning"]
        assert metadata_reads == []
        assert attach_calls == []
        return ConfirmationDecision.APPROVED

    result = success(operation_name, {"written": True})
    monkeypatch.setattr(
        commands,
        operation_name,
        lambda context, request: events.append("append") or calls.append((context, request)) or result,
    )
    other_operations = {
        "append_image_valid",
        "append_boot_attempt",
        "append_app_confirmed",
        "run_flash_app",
    } - {operation_name}
    for other in other_operations:
        monkeypatch.setattr(
            commands,
            other,
            lambda *_args, _other=other: (_ for _ in ()).throw(
                AssertionError(f"unexpected operation: {_other}")
            ),
        )

    outcome = getattr(commands, handler_name)(
        flash_runtime,
        _args(command),
        confirmation_requester=approve,
    )

    assert events == ["service", "confirmation", "append"]
    assert len(calls) == 1
    assert calls[0][0].service is service
    assert outcome.operation_result is result
    assert metadata_reads == []
    assert attach_calls == []


@pytest.mark.parametrize(
    ("handler_name", "command", "operation_name"),
    [
        ("handle_metadata_image_valid", "metadata image-valid", "append_image_valid"),
        ("handle_metadata_boot_attempt", "metadata boot-attempt", "append_boot_attempt"),
        ("handle_metadata_app_confirmed", "metadata app-confirmed", "append_app_confirmed"),
    ],
)
def test_metadata_mutation_cancellation_after_preparation_skips_confirmation_and_operation(
    monkeypatch,
    flash_runtime,
    handler_name: str,
    command: str,
    operation_name: str,
) -> None:
    service = _prepared_service()
    metadata_reads: list[object] = []
    attach_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda context: metadata_reads.append(context),
    )
    monkeypatch.setattr(
        commands,
        "attach_flash_service",
        lambda context: attach_calls.append(context),
    )
    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: flash_runtime.cancellation_source.request() or service,
    )
    monkeypatch.setattr(
        commands,
        "request_confirmation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("confirmation must be skipped")),
    )
    monkeypatch.setattr(
        commands,
        operation_name,
        lambda *_args: (_ for _ in ()).throw(AssertionError("mutation must be skipped")),
    )

    outcome = getattr(commands, handler_name)(flash_runtime, _args(command))

    assert outcome_exit_code(outcome) is ExitCode.CANCELLED
    assert outcome.error is not None and outcome.error.code == "CANCELLED"
    assert metadata_reads == []
    assert attach_calls == []


def test_service_status_calls_get_service_status_without_attach(monkeypatch, command_runtime) -> None:
    calls: list[object] = []
    attach_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_service_status",
        lambda ctx: calls.append(ctx) or success("get_service_status", {"service_state": 2}),
    )
    monkeypatch.setattr(commands, "attach_flash_service", lambda ctx: attach_calls.append(ctx))

    outcome = commands.handle_service_status(command_runtime)

    assert outcome.command == "service status"
    assert outcome.operation_result.summary == {"service_state": 2}
    assert len(calls) == 1
    assert attach_calls == []


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


def _prepared_service() -> object:
    return SimpleNamespace(expected_crc32=0x12345678)


def _prepared_app(*, sector_mask: int = 0x42) -> object:
    return SimpleNamespace(
        identity=SimpleNamespace(
            entry_point=0x082400,
            image_crc32=0xABCDEF01,
            image_size_words=16,
        ),
        sector_mask=sector_mask,
    )


def _args(command: str):
    values = command.split() + [
        "--flash-service-image",
        "service.out",
        "--flash-service-map",
        "service.map",
    ]
    if command in {"program", "verify"}:
        values[1:1] = ["--image", "app.out"]
    elif command == "metadata image-valid":
        values[2:2] = ["--image", "app.out"]
    return build_parser().parse_args(values)


@pytest.fixture
def flash_runtime(command_runtime):
    command_runtime.target = CPU1_PROFILE
    command_runtime.cancellation_source = CancellationSource()
    command_runtime.cancellation = command_runtime.cancellation_source
    command_runtime.flash_contexts = []

    def build_context(service, progress=None):
        context = SimpleNamespace(
            session=command_runtime.session,
            target=command_runtime.target,
            progress=progress,
            cancellation=command_runtime.cancellation,
            service=service,
            force_service_attach=False,
        )
        command_runtime.flash_contexts.append((service, context))
        return context

    command_runtime.flash_operation_context = build_context
    return command_runtime


def test_run_reads_metadata_confirms_and_runs_only_current_valid_image(monkeypatch, flash_runtime) -> None:
    summary = _metadata_summary(flash_runtime, latest_record_type=0, boot_attempt_count=0, app_confirmed=0)
    events: list[str] = []
    run_calls: list[object] = []
    metadata_result = success("get_metadata_summary", summary)
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda context: events.append("metadata") or metadata_result,
    )

    def approve(details, *, assume_yes):
        events.append("confirmation")
        assert assume_yes is False
        assert details["command"] == "run"
        assert details["connected target"] == flash_runtime.target.name
        assert details["entry point"] == summary["entry_point"]
        assert details["image CRC"] == summary["image_crc32"]
        assert details["image size"] == summary["image_size_words"]
        assert "does not write BOOT_ATTEMPT or APP_CONFIRMED" in details["warning"]
        return ConfirmationDecision.APPROVED

    monkeypatch.setattr(
        commands,
        "run_flash_app",
        lambda context, request: events.append("run") or run_calls.append((context, request)) or success(
            "run_flash_app", {"entry_point": request.entry_point}
        ),
    )
    for forbidden in (
        "append_image_valid",
        "append_boot_attempt",
        "append_app_confirmed",
        "attach_flash_service",
        "verify_flash_image",
        "get_last_error",
    ):
        monkeypatch.setattr(
            commands,
            forbidden,
            lambda *_args, _forbidden=forbidden: (_ for _ in ()).throw(
                AssertionError(f"unexpected RUN operation: {_forbidden}")
            ),
        )

    outcome = commands.handle_run(
        flash_runtime,
        build_parser().parse_args(["run"]),
        confirmation_requester=approve,
    )

    assert events == ["metadata", "confirmation", "run"]
    assert len(run_calls) == 1
    assert run_calls[0][0] is flash_runtime.contexts[1]
    assert run_calls[0][1].entry_point == summary["entry_point"]
    assert len(flash_runtime.contexts) == 2
    assert outcome.operation_result is not None and outcome.operation_result.ok


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("metadata_valid", 0),
        ("state", 2),
        ("entry_point", 0),
        ("image_size_words", 0),
        ("image_crc32", 0),
        ("target_device_id", "mismatch"),
        ("target_cpu_id", "mismatch"),
        ("entry_point", "misaligned"),
        ("entry_point", "outside"),
        ("target", "missing_flash"),
    ],
)
def test_run_rejects_invalid_current_image_without_prompt_or_run(
    monkeypatch,
    flash_runtime,
    field: str,
    value: object,
) -> None:
    summary = _metadata_summary(flash_runtime)
    if field == "target_device_id" and value == "mismatch":
        summary[field] = flash_runtime.discovered_target.device_info.device_id + 1
    elif field == "target_cpu_id" and value == "mismatch":
        summary[field] = flash_runtime.discovered_target.device_info.cpu_id + 1
    elif field == "entry_point" and value == "misaligned":
        summary[field] = summary[field] + 1
    elif field == "entry_point" and value == "outside":
        summary[field] = flash_runtime.target.memory_map.flash.app_ranges[0].start - 8
    elif field == "target" and value == "missing_flash":
        flash_runtime.target = replace(
            flash_runtime.target,
            memory_map=replace(flash_runtime.target.memory_map, flash=None),
        )
    elif field != "target":
        summary[field] = value

    metadata_result = success("get_metadata_summary", summary)
    metadata_calls: list[object] = []
    confirmation_calls: list[object] = []
    run_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda context: metadata_calls.append(context) or metadata_result,
    )
    monkeypatch.setattr(
        commands,
        "run_flash_app",
        lambda *args: run_calls.append(args),
    )

    def confirm(*_args, **_kwargs):
        confirmation_calls.append(True)
        return ConfirmationDecision.APPROVED

    outcome = commands.handle_run(
        flash_runtime,
        build_parser().parse_args(["run"]),
        confirmation_requester=confirm,
    )

    assert len(metadata_calls) == 1
    assert run_calls == []
    assert confirmation_calls == []
    assert outcome.operation_result is None
    assert outcome.error is not None
    assert outcome.error.domain == "operation"
    assert outcome.error.code == "IMAGE_VALID_REQUIRED"
    assert outcome_exit_code(outcome) is ExitCode.OPERATION_FAILURE


def test_run_returns_metadata_read_failure_without_prompt_or_run(monkeypatch, flash_runtime) -> None:
    metadata_result = OperationResult(
        False,
        "get_metadata_summary",
        flash_runtime.target.name,
        "GET_METADATA_SUMMARY",
        {},
        error=OperationErrorInfo(
            "PROTOCOL_ERROR",
            "metadata read failed",
            "GET_METADATA_SUMMARY",
            domain=ErrorDomain.COMMUNICATION,
        ),
    )
    calls: list[str] = []
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: metadata_result)
    monkeypatch.setattr(
        commands,
        "run_flash_app",
        lambda *_args: calls.append("run"),
    )

    def confirm(*_args, **_kwargs):
        calls.append("confirmation")
        return ConfirmationDecision.APPROVED

    outcome = commands.handle_run(
        flash_runtime,
        build_parser().parse_args(["run"]),
        confirmation_requester=confirm,
    )

    assert outcome.operation_result is metadata_result
    assert calls == []
    assert outcome_exit_code(outcome) is ExitCode.COMMUNICATION_FAILURE


def test_run_cancellation_after_metadata_read_skips_confirmation_and_run(monkeypatch, flash_runtime) -> None:
    metadata_result = success("get_metadata_summary", _metadata_summary(flash_runtime))
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda _context: flash_runtime.cancellation_source.request() or metadata_result,
    )
    monkeypatch.setattr(
        commands,
        "run_flash_app",
        lambda *_args: (_ for _ in ()).throw(AssertionError("RUN must be skipped")),
    )
    monkeypatch.setattr(
        commands,
        "request_confirmation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("confirmation must be skipped")),
    )

    outcome = commands.handle_run(flash_runtime, build_parser().parse_args(["run"]))

    assert outcome_exit_code(outcome) is ExitCode.CANCELLED
    assert outcome.error is not None and outcome.error.code == "CANCELLED"


def test_run_cancellation_after_approval_skips_run(monkeypatch, flash_runtime) -> None:
    metadata_result = success("get_metadata_summary", _metadata_summary(flash_runtime))
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: metadata_result)
    monkeypatch.setattr(
        commands,
        "run_flash_app",
        lambda *_args: (_ for _ in ()).throw(AssertionError("RUN must be skipped")),
    )

    def approve(*_args, **_kwargs):
        flash_runtime.cancellation_source.request()
        return ConfirmationDecision.APPROVED

    outcome = commands.handle_run(
        flash_runtime,
        build_parser().parse_args(["run"]),
        confirmation_requester=approve,
    )

    assert outcome_exit_code(outcome) is ExitCode.CANCELLED


def test_service_attach_prepares_once_and_calls_only_public_attach(monkeypatch, flash_runtime) -> None:
    service = _prepared_service()
    prepared: list[tuple[object, object, object]] = []
    attached: list[object] = []
    progress = object()

    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda image, service_map, *, target: prepared.append((image, service_map, target)) or service,
    )
    monkeypatch.setattr(
        commands,
        "attach_flash_service",
        lambda context: attached.append(context) or success("attach_flash_service", {"service_action": "REUSED"}),
    )
    monkeypatch.setattr(
        commands,
        "request_confirmation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("attach is not confirmed")),
    )

    outcome = commands.handle_service_attach(flash_runtime, _args("service attach"), progress)

    assert outcome.operation_result is not None
    assert prepared == [("service.out", "service.map", CPU1_PROFILE)]
    assert len(attached) == 1
    assert attached[0].service is service
    assert attached[0].progress is progress
    assert attached[0].cancellation is flash_runtime.cancellation
    assert attached[0].force_service_attach is False


def test_erase_image_prepares_service_then_app_confirms_then_erases(monkeypatch, flash_runtime) -> None:
    service = _prepared_service()
    image = _prepared_app()
    events: list[str] = []
    calls: list[object] = []

    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: events.append("service") or service,
    )
    monkeypatch.setattr(
        commands,
        "prepare_flash_app_image",
        lambda *_args, **_kwargs: events.append("app") or image,
    )

    def approve(details, *, assume_yes):
        events.append("confirmation")
        assert details["sector mask"] == image.sector_mask
        assert assume_yes is False
        return ConfirmationDecision.APPROVED

    monkeypatch.setattr(
        commands,
        "erase_flash_image_area",
        lambda context, request: calls.append((context, request))
        or events.append("erase")
        or success("erase_flash_image_area"),
    )

    args = build_parser().parse_args(
        [
            "erase",
            "--image",
            "app.out",
            "--flash-service-image",
            "service.out",
            "--flash-service-map",
            "service.map",
        ]
    )
    outcome = commands.handle_erase(flash_runtime, args, confirmation_requester=approve)

    assert events == ["service", "app", "confirmation", "erase"]
    assert len(calls) == 1
    assert calls[0][0].service is service
    assert calls[0][1].image is image
    assert outcome.operation_result is not None


def test_erase_all_app_uses_active_profile_mask(monkeypatch, flash_runtime) -> None:
    custom_flash = replace(CPU1_PROFILE.memory_map.flash, allowed_erase_mask=0xA5)
    custom_map = replace(CPU1_PROFILE.memory_map, flash=custom_flash)
    custom_target = replace(CPU1_PROFILE, name="test target", memory_map=custom_map)
    flash_runtime.target = custom_target
    service = _prepared_service()
    masks: list[int] = []

    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: service)
    monkeypatch.setattr(
        commands,
        "erase_sector_mask",
        lambda context, request: masks.append(request.sector_mask) or success("erase_sector_mask"),
    )

    outcome = commands.handle_erase(
        flash_runtime,
        build_parser().parse_args(
            [
                "erase",
                "--all-app",
                "--flash-service-image",
                "service.out",
                "--flash-service-map",
                "service.map",
                "--yes",
            ]
        ),
    )

    assert outcome_exit_code(outcome) is ExitCode.SUCCESS
    assert masks == [0xA5]


def test_erase_sector_mask_passes_user_mask_without_cli_safety_changes(monkeypatch, flash_runtime) -> None:
    service = _prepared_service()
    masks: list[int] = []
    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: service)
    monkeypatch.setattr(
        commands,
        "erase_sector_mask",
        lambda _context, request: masks.append(request.sector_mask)
        or OperationResult(
            False,
            "erase_sector_mask",
            "target",
            "ERASE",
            {},
            error=OperationErrorInfo("FORBIDDEN_SECTOR", "unsafe", "ERASE"),
        ),
    )

    outcome = commands.handle_erase(
        flash_runtime,
        build_parser().parse_args(
            [
                "erase",
                "--sector-mask",
                "0",
                "--flash-service-image",
                "service.out",
                "--flash-service-map",
                "service.map",
                "--yes",
            ]
        ),
    )

    assert masks == [0]
    assert outcome_exit_code(outcome) is ExitCode.OPERATION_FAILURE


def test_program_is_atomic_and_confirmation_precedes_operation(monkeypatch, flash_runtime) -> None:
    service = _prepared_service()
    image = _prepared_app()
    events: list[str] = []
    calls: list[object] = []
    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: events.append("service") or service)
    monkeypatch.setattr(commands, "prepare_flash_app_image", lambda *_args, **_kwargs: events.append("app") or image)

    def approve(_details, *, assume_yes):
        assert assume_yes is False
        events.append("confirmation")
        return ConfirmationDecision.APPROVED

    monkeypatch.setattr(
        commands,
        "program_flash_image",
        lambda context, request: events.append("program") or calls.append(request) or success("program_flash_image"),
    )

    outcome = commands.handle_program(flash_runtime, _args("program"), confirmation_requester=approve)

    assert events == ["service", "app", "confirmation", "program"]
    assert len(calls) == 1 and calls[0].image is image
    assert outcome.operation_result is not None


def test_verify_is_atomic_and_never_confirms(monkeypatch, flash_runtime) -> None:
    service = _prepared_service()
    image = _prepared_app()
    calls: list[object] = []
    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: service)
    monkeypatch.setattr(commands, "prepare_flash_app_image", lambda *_args, **_kwargs: image)
    monkeypatch.setattr(
        commands,
        "request_confirmation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("verify is not confirmed")),
    )
    monkeypatch.setattr(
        commands,
        "verify_flash_image",
        lambda _context, request: calls.append(request) or success("verify_flash_image"),
    )

    outcome = commands.handle_verify(flash_runtime, _args("verify"))

    assert len(calls) == 1 and calls[0].image is image
    assert outcome.operation_result is not None


@pytest.mark.parametrize("exception", [FileNotFoundError("missing"), ValueError("invalid")])
def test_known_preparation_failures_map_to_operation_failure(monkeypatch, flash_runtime, exception) -> None:
    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: (_ for _ in ()).throw(exception))

    outcome = commands.handle_service_attach(flash_runtime, _args("service attach"))

    assert outcome_exit_code(outcome) is ExitCode.OPERATION_FAILURE
    assert outcome.error is not None
    assert outcome.error.code == "RESOURCE_PREPARATION_FAILED"
    assert outcome.error.domain == "operation"


def test_unexpected_preparation_exception_is_not_reclassified(monkeypatch, flash_runtime) -> None:
    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("programming bug")),
    )

    with pytest.raises(RuntimeError, match="programming bug"):
        commands.handle_service_attach(flash_runtime, _args("service attach"))


def test_cancellation_after_preparation_skips_confirmation_and_mutation(monkeypatch, flash_runtime) -> None:
    service = _prepared_service()
    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: flash_runtime.cancellation_source.request() or service,
    )
    monkeypatch.setattr(
        commands,
        "request_confirmation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("confirmation must be skipped")),
    )
    monkeypatch.setattr(
        commands,
        "attach_flash_service",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("mutation must be skipped")),
    )

    outcome = commands.handle_service_attach(flash_runtime, _args("service attach"))

    assert outcome_exit_code(outcome) is ExitCode.CANCELLED


def test_erase_image_cancellation_after_preparation_skips_confirmation_and_flash_mutation(
    monkeypatch,
    flash_runtime,
) -> None:
    service = _prepared_service()
    image = _prepared_app()
    prepared: list[str] = []
    confirmation_calls: list[object] = []
    erase_image_calls: list[object] = []
    erase_mask_calls: list[object] = []
    attach_calls: list[object] = []

    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: prepared.append("service") or service,
    )

    def prepare_app(*_args, **_kwargs):
        prepared.append("app")
        flash_runtime.cancellation_source.request()
        return image

    monkeypatch.setattr(commands, "prepare_flash_app_image", prepare_app)
    monkeypatch.setattr(
        commands,
        "request_confirmation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("default confirmation must be skipped")
        ),
    )
    monkeypatch.setattr(commands, "erase_flash_image_area", lambda *args: erase_image_calls.append(args))
    monkeypatch.setattr(commands, "erase_sector_mask", lambda *args: erase_mask_calls.append(args))
    monkeypatch.setattr(commands, "attach_flash_service", lambda *args: attach_calls.append(args))

    args = build_parser().parse_args(
        [
            "erase",
            "--image",
            "app.out",
            "--flash-service-image",
            "service.out",
            "--flash-service-map",
            "service.map",
        ]
    )

    def request_confirmation(_details, *, assume_yes):
        confirmation_calls.append(assume_yes)
        return ConfirmationDecision.APPROVED

    outcome = commands.handle_erase(
        flash_runtime,
        args,
        confirmation_requester=request_confirmation,
    )

    assert prepared == ["service", "app"]
    assert confirmation_calls == []
    assert erase_image_calls == []
    assert erase_mask_calls == []
    assert attach_calls == []
    assert outcome.error is not None and outcome.error.code == "CANCELLED"
    assert outcome_exit_code(outcome) is ExitCode.CANCELLED


def test_program_cancellation_after_preparation_skips_confirmation_and_flash_mutation(
    monkeypatch,
    flash_runtime,
) -> None:
    service = _prepared_service()
    image = _prepared_app()
    prepared: list[str] = []
    confirmation_calls: list[object] = []
    program_calls: list[object] = []
    erase_image_calls: list[object] = []
    erase_mask_calls: list[object] = []
    verify_calls: list[object] = []
    attach_calls: list[object] = []

    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: prepared.append("service") or service,
    )

    def prepare_app(*_args, **_kwargs):
        prepared.append("app")
        flash_runtime.cancellation_source.request()
        return image

    monkeypatch.setattr(commands, "prepare_flash_app_image", prepare_app)
    monkeypatch.setattr(
        commands,
        "request_confirmation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("default confirmation must be skipped")
        ),
    )
    monkeypatch.setattr(commands, "program_flash_image", lambda *args: program_calls.append(args))
    monkeypatch.setattr(commands, "erase_flash_image_area", lambda *args: erase_image_calls.append(args))
    monkeypatch.setattr(commands, "erase_sector_mask", lambda *args: erase_mask_calls.append(args))
    monkeypatch.setattr(commands, "verify_flash_image", lambda *args: verify_calls.append(args))
    monkeypatch.setattr(commands, "attach_flash_service", lambda *args: attach_calls.append(args))

    def request_confirmation(_details, *, assume_yes):
        confirmation_calls.append(assume_yes)
        return ConfirmationDecision.APPROVED

    outcome = commands.handle_program(
        flash_runtime,
        _args("program"),
        confirmation_requester=request_confirmation,
    )

    assert prepared == ["service", "app"]
    assert confirmation_calls == []
    assert program_calls == []
    assert erase_image_calls == []
    assert erase_mask_calls == []
    assert verify_calls == []
    assert attach_calls == []
    assert outcome.error is not None and outcome.error.code == "CANCELLED"
    assert outcome_exit_code(outcome) is ExitCode.CANCELLED
