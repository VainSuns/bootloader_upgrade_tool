from __future__ import annotations

import importlib
import io
import json
from types import SimpleNamespace

import bootloader_upgrade_tool.cli.commands as commands
from bootloader_upgrade_tool.cli.output import CommandOutcome, ExitCode
from bootloader_upgrade_tool.cli.runtime import CancellationSource
from bootloader_upgrade_tool.operations import (
    DiscoveredTarget,
    ErrorDomain,
    OperationErrorInfo,
    OperationResult,
    TargetDiscoveryOutcome,
    operation_result_to_dict,
)
from bootloader_upgrade_tool.protocol.constants import CpuId, DeviceId
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import CPU1_PROFILE
from bootloader_upgrade_tool.transport import TransportError, TransportOpenResult, TransportOpenStatus


main_module = importlib.import_module("bootloader_upgrade_tool.cli.main")


def _discovery() -> TargetDiscoveryOutcome:
    info = DeviceInfo(int(DeviceId.F28377D), int(CpuId.CPU1), 1, 0, 0, 1, 0, 256, 8, 2, 2)
    return TargetDiscoveryOutcome(
        OperationResult(True, "discover_connected_target", "discovery", "RESOLVE_TARGET", {}),
        DiscoveredTarget(info, CPU1_PROFILE, "cpu1"),
    )


class FakeRuntime:
    def __init__(
        self,
        source: CancellationSource,
        *,
        open_result=None,
        cancel_discovery=False,
        fail_discovery=False,
        disconnect_error=None,
    ):
        self.source = source
        self.open_result = open_result or TransportOpenResult(
            TransportOpenStatus.OPENED, False, "OPEN_COMPLETE"
        )
        self.cancel_discovery = cancel_discovery
        self.fail_discovery = fail_discovery
        self.disconnect_error = disconnect_error
        self.events: list[str] = []

    def connect(self, token):
        self.events.append("connect")
        assert token is self.source
        return self.open_result

    def discover(self):
        self.events.append("discover")
        if self.cancel_discovery:
            self.source.request()
        if self.fail_discovery:
            return TargetDiscoveryOutcome(
                OperationResult(
                    False,
                    "discover_connected_target",
                    "discovery",
                    "GET_DEVICE_INFO",
                    {},
                    error=OperationErrorInfo(
                        "PROTOCOL_ERROR",
                        "wire failed",
                        "GET_DEVICE_INFO",
                        domain=ErrorDomain.COMMUNICATION,
                    ),
                ),
                None,
            )
        return _discovery()

    def disconnect(self):
        self.events.append("disconnect")
        if self.disconnect_error is not None:
            raise self.disconnect_error


def invoke(arguments, runtime_factory, monkeypatch=None, *, stdin=None):
    stdout = io.StringIO()
    stderr = io.StringIO()
    result = main_module.main(
        arguments,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        runtime_factory=runtime_factory,
    )
    return result, stdout, stderr


def test_main_runs_connect_discovery_one_command_disconnect_and_keeps_json_on_stdout(monkeypatch) -> None:
    source_holder: list[CancellationSource] = []
    runtime_holder: list[FakeRuntime] = []

    def factory(_config, *, cancellation_source):
        source_holder.append(cancellation_source)
        runtime = FakeRuntime(cancellation_source)
        runtime_holder.append(runtime)
        return runtime

    called: list[str] = []
    monkeypatch.setattr(
        main_module,
        "execute_command",
        lambda runtime, args, progress: called.append(args.command)
        or CommandOutcome(args.command, result={"ok": True}),
    )

    exit_code, stdout, stderr = invoke(["--json", "--port", "COM1", "status"], factory)

    assert exit_code == 0
    assert runtime_holder[0].events == ["connect", "discover", "disconnect"]
    assert called == ["status"]
    payload = json.loads(stdout.getvalue())
    assert payload["success"] is True and payload["command"] == "status"
    assert stderr.getvalue() == ""


def test_human_status_keeps_metadata_summary_when_machine_result_is_serialized(monkeypatch) -> None:
    metadata_result = OperationResult(
        True,
        "get_metadata_summary",
        "TMS320F28377D CPU1",
        "GET_METADATA_SUMMARY",
        {"metadata_valid": 1},
    )

    def factory(_config, *, cancellation_source):
        return FakeRuntime(cancellation_source)

    monkeypatch.setattr(
        main_module,
        "execute_command",
        lambda runtime, args, progress: CommandOutcome(
            args.command,
            result={
                "target": {"target_key": "cpu1"},
                "metadata": operation_result_to_dict(metadata_result),
            },
            operation_result=metadata_result,
        ),
    )
    exit_code, stdout, _stderr = invoke(["--port", "COM1", "status"], factory)

    assert exit_code == int(ExitCode.SUCCESS)
    assert "metadata_valid: 1" in stdout.getvalue()
    assert "operation:" not in stdout.getvalue()
    assert "completion:" not in stdout.getvalue()


def test_missing_port_is_cli_usage_error_without_constructing_runtime() -> None:
    called = []

    def factory(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("missing --port must not create a runtime")

    exit_code, stdout, _stderr = invoke(["--json", "status"], factory)

    assert exit_code == int(ExitCode.CLI_USAGE_ERROR)
    assert called == []
    payload = json.loads(stdout.getvalue())
    assert payload["success"] is False
    assert payload["exit_code"] == 2
    assert payload["error"]["code"] == "CLI_USAGE_ERROR"


def test_json_parser_error_is_one_valid_stdout_document() -> None:
    exit_code, stdout, _stderr = invoke(["--json", "not-a-command"], lambda *_args, **_kwargs: None)

    assert exit_code == 2
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == 1
    assert payload["exit_code"] == 2
    assert payload["success"] is False


def test_open_cancellation_does_not_discover_or_start_command(monkeypatch) -> None:
    holder: list[FakeRuntime] = []

    def factory(_config, *, cancellation_source):
        runtime = FakeRuntime(
            cancellation_source,
            open_result=TransportOpenResult(
                TransportOpenStatus.CANCELLED,
                True,
                "BEFORE_SERIAL_OPEN",
            ),
        )
        holder.append(runtime)
        return runtime

    monkeypatch.setattr(main_module, "execute_command", lambda *_args: (_ for _ in ()).throw(AssertionError()))
    exit_code, stdout, _stderr = invoke(["--json", "--port", "COM1", "status"], factory)

    assert exit_code == 4
    assert holder[0].events == ["connect", "disconnect"]
    payload = json.loads(stdout.getvalue())
    assert payload["success"] is False and payload["exit_code"] == 4


def test_discovery_failure_stops_before_command_and_disconnects(monkeypatch) -> None:
    holder: list[FakeRuntime] = []

    def factory(_config, *, cancellation_source):
        runtime = FakeRuntime(cancellation_source, fail_discovery=True)
        holder.append(runtime)
        return runtime

    monkeypatch.setattr(main_module, "execute_command", lambda *_args: (_ for _ in ()).throw(AssertionError()))
    exit_code, stdout, _stderr = invoke(["--json", "--port", "COM1", "status"], factory)

    assert exit_code == 3
    assert holder[0].events == ["connect", "discover", "disconnect"]
    payload = json.loads(stdout.getvalue())
    assert payload["error"]["domain"] == "communication"


def test_cancellation_requested_at_discovery_boundary_skips_command(monkeypatch) -> None:
    holder: list[FakeRuntime] = []

    def factory(_config, *, cancellation_source):
        runtime = FakeRuntime(cancellation_source, cancel_discovery=True)
        holder.append(runtime)
        return runtime

    monkeypatch.setattr(main_module, "execute_command", lambda *_args: (_ for _ in ()).throw(AssertionError()))
    exit_code, stdout, _stderr = invoke(["--json", "--port", "COM1", "status"], factory)

    assert exit_code == 4
    assert holder[0].events == ["connect", "discover", "disconnect"]
    assert json.loads(stdout.getvalue())["exit_code"] == 4


def test_unexpected_command_error_is_internal_and_verbose_traceback_stays_on_stderr(monkeypatch) -> None:
    def factory(_config, *, cancellation_source):
        return FakeRuntime(cancellation_source)

    monkeypatch.setattr(main_module, "execute_command", lambda *_args: (_ for _ in ()).throw(RuntimeError("bug")))
    exit_code, stdout, stderr = invoke(
        ["--json", "--verbose", "--port", "COM1", "status"],
        factory,
    )

    assert exit_code == 7
    assert "Traceback" in stderr.getvalue()
    assert "Traceback" not in stdout.getvalue()
    payload = json.loads(stdout.getvalue())
    assert payload["error"]["code"] == "INTERNAL_ERROR"


def test_unknown_disconnect_error_is_internal_exit_7_in_json_and_verbose_traceback_stays_on_stderr(
    monkeypatch,
) -> None:
    def factory(_config, *, cancellation_source):
        return FakeRuntime(cancellation_source, disconnect_error=RuntimeError("bug"))

    monkeypatch.setattr(
        main_module,
        "execute_command",
        lambda runtime, args, progress: CommandOutcome(args.command, result={"ok": True}),
    )
    exit_code, stdout, stderr = invoke(
        ["--json", "--verbose", "--port", "COM1", "status"],
        factory,
    )

    assert exit_code == int(ExitCode.INTERNAL_ERROR)
    payload = json.loads(stdout.getvalue())
    assert payload["success"] is False
    assert payload["exit_code"] == int(ExitCode.INTERNAL_ERROR)
    assert payload["error"]["domain"] == "internal"
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "Traceback" in stderr.getvalue()
    assert "Traceback" not in stdout.getvalue()


def test_known_communication_disconnect_error_remains_exit_3(monkeypatch) -> None:
    def factory(_config, *, cancellation_source):
        return FakeRuntime(cancellation_source, disconnect_error=TransportError("port closed"))

    monkeypatch.setattr(
        main_module,
        "execute_command",
        lambda runtime, args, progress: CommandOutcome(args.command, result={"ok": True}),
    )
    exit_code, stdout, _stderr = invoke(["--json", "--port", "COM1", "status"], factory)

    assert exit_code == int(ExitCode.COMMUNICATION_FAILURE)
    payload = json.loads(stdout.getvalue())
    assert payload["success"] is False
    assert payload["exit_code"] == int(ExitCode.COMMUNICATION_FAILURE)
    assert payload["error"]["domain"] == "communication"
    assert payload["error"]["code"] == "COMMUNICATION_FAILURE"


class TerminalInput(io.StringIO):
    def __init__(self, value: str, *, tty: bool) -> None:
        super().__init__(value)
        self.tty = tty
        self.reads = 0

    def isatty(self) -> bool:
        return self.tty

    def readline(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.reads += 1
        return super().readline(*args, **kwargs)


def _flash_runtime_factory(operation_calls: list[object]):
    def factory(_config, *, cancellation_source):
        runtime = FakeRuntime(cancellation_source)
        runtime.target = CPU1_PROFILE
        runtime.cancellation = cancellation_source

        def flash_context(service, progress=None):
            return SimpleNamespace(
                service=service,
                target=runtime.target,
                progress=progress,
                cancellation=runtime.cancellation,
                force_service_attach=False,
            )

        runtime.flash_operation_context = flash_context
        return runtime

    return factory


def _flash_args(*extra: str) -> list[str]:
    return [
        "--json",
        "--port",
        "COM1",
        "erase",
        "--all-app",
        "--flash-service-image",
        "service.out",
        "--flash-service-map",
        "service.map",
        *extra,
    ]


def _program_args(*extra: str) -> list[str]:
    return [
        "--json",
        "--port",
        "COM1",
        "program",
        "--image",
        "app.out",
        "--flash-service-image",
        "service.out",
        "--flash-service-map",
        "service.map",
        *extra,
    ]


def _patch_program_preparation(monkeypatch):
    prepared: list[str] = []
    service = SimpleNamespace(expected_crc32=0x12345678)
    image = SimpleNamespace(
        identity=SimpleNamespace(
            entry_point=0x082400,
            image_crc32=0xABCDEF01,
            image_size_words=16,
        )
    )
    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: prepared.append("service") or service,
    )
    monkeypatch.setattr(
        commands,
        "prepare_flash_app_image",
        lambda *_args, **_kwargs: prepared.append("app") or image,
    )
    return prepared


def test_noninteractive_dangerous_command_requires_confirmation_before_mutation(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        commands,
        "erase_sector_mask",
        lambda _context, request: calls.append(request),
    )

    stdin = TerminalInput("y\n", tty=False)
    exit_code, stdout, stderr = invoke(
        _flash_args(),
        _flash_runtime_factory(calls),
        stdin=stdin,
    )

    assert exit_code == int(ExitCode.CONFIRMATION_REQUIRED)
    assert calls == []
    assert stdin.reads == 0
    payload = json.loads(stdout.getvalue())
    assert payload["exit_code"] == int(ExitCode.CONFIRMATION_REQUIRED)
    assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert "stdin is not a TTY" in stderr.getvalue()


def test_interactive_decline_is_json_exit_6_and_does_not_mutate(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(commands, "erase_sector_mask", lambda _context, request: calls.append(request))

    exit_code, stdout, stderr = invoke(
        _flash_args(),
        _flash_runtime_factory(calls),
        stdin=TerminalInput("no\n", tty=True),
    )

    assert exit_code == int(ExitCode.USER_DECLINED)
    assert calls == []
    payload = json.loads(stdout.getvalue())
    assert payload["exit_code"] == int(ExitCode.USER_DECLINED)
    assert payload["error"]["code"] == "USER_DECLINED"
    assert "Proceed? [y/N]" in stderr.getvalue()


def test_yes_bypasses_prompt_and_operation_result_remains_authoritative(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        commands,
        "erase_sector_mask",
        lambda _context, request: calls.append(request)
        or OperationResult(True, "erase_sector_mask", "target", "ERASE", {"ok": True}),
    )

    exit_code, stdout, stderr = invoke(
        _flash_args("--yes"),
        _flash_runtime_factory(calls),
        stdin=TerminalInput("no\n", tty=False),
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert len(calls) == 1
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["success"] is True


def test_program_noninteractive_requires_confirmation_before_mutation(monkeypatch) -> None:
    prepared = _patch_program_preparation(monkeypatch)
    program_calls: list[object] = []
    attach_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "program_flash_image",
        lambda _context, request: program_calls.append(request)
        or OperationResult(True, "program_flash_image", "target", "PROGRAM", {"ok": True}),
    )
    monkeypatch.setattr(commands, "attach_flash_service", lambda context: attach_calls.append(context))

    stdin = TerminalInput("y\n", tty=False)
    exit_code, stdout, stderr = invoke(
        _program_args(),
        _flash_runtime_factory(program_calls),
        stdin=stdin,
    )

    assert prepared == ["service", "app"]
    assert exit_code == int(ExitCode.CONFIRMATION_REQUIRED)
    assert program_calls == []
    assert attach_calls == []
    assert stdin.reads == 0
    payload = json.loads(stdout.getvalue())
    assert payload["success"] is False
    assert payload["exit_code"] == int(ExitCode.CONFIRMATION_REQUIRED)
    assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert "stdin is not a TTY" in stderr.getvalue()


def test_program_interactive_decline_is_json_exit_6_and_does_not_mutate(monkeypatch) -> None:
    prepared = _patch_program_preparation(monkeypatch)
    program_calls: list[object] = []
    attach_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "program_flash_image",
        lambda _context, request: program_calls.append(request),
    )
    monkeypatch.setattr(commands, "attach_flash_service", lambda context: attach_calls.append(context))

    exit_code, stdout, stderr = invoke(
        _program_args(),
        _flash_runtime_factory(program_calls),
        stdin=TerminalInput("n\n", tty=True),
    )

    assert prepared == ["service", "app"]
    assert exit_code == int(ExitCode.USER_DECLINED)
    assert program_calls == []
    assert attach_calls == []
    payload = json.loads(stdout.getvalue())
    assert payload["exit_code"] == int(ExitCode.USER_DECLINED)
    assert payload["error"]["code"] == "USER_DECLINED"
    assert "Proceed? [y/N]" in stderr.getvalue()


def test_program_yes_skips_confirmation_input_and_executes_program_once(monkeypatch) -> None:
    prepared = _patch_program_preparation(monkeypatch)
    program_calls: list[object] = []
    attach_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "program_flash_image",
        lambda _context, request: program_calls.append(request)
        or OperationResult(True, "program_flash_image", "target", "PROGRAM", {"ok": True}),
    )
    monkeypatch.setattr(commands, "attach_flash_service", lambda context: attach_calls.append(context))

    stdin = TerminalInput("no\n", tty=False)
    exit_code, stdout, stderr = invoke(
        _program_args("--yes"),
        _flash_runtime_factory(program_calls),
        stdin=stdin,
    )

    assert prepared == ["service", "app"]
    assert exit_code == int(ExitCode.SUCCESS)
    assert stdin.reads == 0
    assert len(program_calls) == 1
    assert attach_calls == []
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["success"] is True
