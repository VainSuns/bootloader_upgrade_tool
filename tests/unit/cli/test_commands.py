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
