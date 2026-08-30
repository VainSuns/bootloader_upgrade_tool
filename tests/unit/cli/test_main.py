from __future__ import annotations

import importlib
import io
import json
from types import SimpleNamespace

import pytest

import bootloader_upgrade_tool.cli.commands as commands
from bootloader_upgrade_tool.cli.output import CommandOutcome, ExitCode
from bootloader_upgrade_tool.cli.runtime import CancellationSource
from bootloader_upgrade_tool.operations import (
    DiscoveredTarget,
    ErrorDomain,
    OperationCancellationInfo,
    OperationCompletion,
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


def _metadata_args(subcommand: str, *extra: str) -> list[str]:
    arguments = ["--json", "--port", "COM1", "metadata", subcommand]
    if subcommand == "image-valid":
        arguments.extend(["--image", "app.out"])
    arguments.extend(
        [
            "--flash-service-image",
            "service.out",
            "--flash-service-map",
            "service.map",
            *extra,
        ]
    )
    return arguments


def _patch_metadata_main(monkeypatch, subcommand: str, operation_result: OperationResult):
    prepared: list[str] = []
    append_calls: list[object] = []
    metadata_reads: list[object] = []
    attach_calls: list[object] = []
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
    if subcommand == "image-valid":
        monkeypatch.setattr(
            commands,
            "prepare_flash_app_image",
            lambda *_args, **_kwargs: prepared.append("app") or image,
        )
    else:
        monkeypatch.setattr(
            commands,
            "prepare_flash_app_image",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("metadata mutation must not prepare the Flash App")
            ),
        )

    def forbidden_metadata_read(*args, **kwargs):  # type: ignore[no-untyped-def]
        metadata_reads.append((args, kwargs))
        raise AssertionError("metadata mutation must not pre-read metadata")

    def forbidden_service_attach(*args, **kwargs):  # type: ignore[no-untyped-def]
        attach_calls.append((args, kwargs))
        raise AssertionError("metadata mutation must not attach the service")

    monkeypatch.setattr(commands, "get_metadata_summary", forbidden_metadata_read)
    monkeypatch.setattr(commands, "attach_flash_service", forbidden_service_attach)
    append_name = {
        "image-valid": "append_image_valid",
        "boot-attempt": "append_boot_attempt",
        "app-confirmed": "append_app_confirmed",
    }[subcommand]

    def append(*args, **kwargs):  # type: ignore[no-untyped-def]
        append_calls.append((args, kwargs))
        prepared.append("append")
        return operation_result

    monkeypatch.setattr(commands, append_name, append)
    return prepared, append_calls, metadata_reads, attach_calls


@pytest.mark.parametrize("subcommand", ["image-valid", "boot-attempt", "app-confirmed"])
@pytest.mark.parametrize("mode", ["non_tty", "decline", "yes"])
def test_metadata_main_confirmation_matrix_has_one_json_document_and_no_metadata_preread(
    monkeypatch,
    subcommand: str,
    mode: str,
) -> None:
    operation_result = OperationResult(
        True,
        f"append_{subcommand.replace('-', '_')}",
        CPU1_PROFILE.name,
        "METADATA_APPEND_RECORD",
        {"written": True},
    )
    prepared, append_calls, metadata_reads, attach_calls = _patch_metadata_main(
        monkeypatch,
        subcommand,
        operation_result,
    )
    stdin = TerminalInput(
        "n\n" if mode == "decline" else "y\n",
        tty=mode == "decline",
    )
    arguments = _metadata_args(subcommand, "--yes") if mode == "yes" else _metadata_args(subcommand)

    exit_code, stdout, stderr = invoke(
        arguments,
        _flash_runtime_factory(append_calls),
        stdin=stdin,
    )

    payload = json.loads(stdout.getvalue())
    assert payload["command"] == f"metadata {subcommand}"
    assert metadata_reads == []
    assert attach_calls == []
    assert prepared.count("service") == 1
    assert prepared.count("app") == (1 if subcommand == "image-valid" else 0)

    if mode == "non_tty":
        assert exit_code == int(ExitCode.CONFIRMATION_REQUIRED)
        assert payload["success"] is False
        assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"
        assert append_calls == []
        assert stdin.reads == 0
        assert "stdin is not a TTY" in stderr.getvalue()
    elif mode == "decline":
        assert exit_code == int(ExitCode.USER_DECLINED)
        assert payload["success"] is False
        assert payload["error"]["code"] == "USER_DECLINED"
        assert append_calls == []
        assert stdin.reads == 1
        assert "Proceed? [y/N]" in stderr.getvalue()
    else:
        assert exit_code == int(ExitCode.SUCCESS)
        assert payload["success"] is True
        assert len(append_calls) == 1
        assert prepared.count("append") == 1
        assert stdin.reads == 0
        assert stderr.getvalue() == ""


@pytest.mark.parametrize(
    ("subcommand", "expected_exit", "operation_result"),
    [
        (
            "image-valid",
            ExitCode.OPERATION_FAILURE,
            OperationResult(
                False,
                "append_image_valid",
                CPU1_PROFILE.name,
                "METADATA_APPEND_RECORD",
                {},
                error=OperationErrorInfo(
                    "WRITE_FAILED",
                    "metadata write failed",
                    "METADATA_APPEND_RECORD",
                    domain=ErrorDomain.OPERATION,
                ),
            ),
        ),
        (
            "boot-attempt",
            ExitCode.COMMUNICATION_FAILURE,
            OperationResult(
                False,
                "append_boot_attempt",
                CPU1_PROFILE.name,
                "METADATA_APPEND_RECORD",
                {},
                error=OperationErrorInfo(
                    "PROTOCOL_ERROR",
                    "metadata response was not received",
                    "METADATA_APPEND_RECORD",
                    domain=ErrorDomain.COMMUNICATION,
                ),
            ),
        ),
        (
            "app-confirmed",
            ExitCode.CANCELLED,
            OperationResult(
                False,
                "append_app_confirmed",
                CPU1_PROFILE.name,
                "METADATA_APPEND_RECORD",
                {},
                completion=OperationCompletion.CANCELLED,
                cancellation=OperationCancellationInfo(
                    "METADATA_APPEND_RECORD",
                    0,
                    0,
                    True,
                    False,
                    False,
                    service_attached=True,
                ),
            ),
        ),
    ],
)
def test_metadata_main_operation_results_preserve_exit_domains(
    monkeypatch,
    subcommand: str,
    expected_exit: ExitCode,
    operation_result: OperationResult,
) -> None:
    prepared, append_calls, metadata_reads, attach_calls = _patch_metadata_main(
        monkeypatch,
        subcommand,
        operation_result,
    )

    exit_code, stdout, _stderr = invoke(
        _metadata_args(subcommand, "--yes"),
        _flash_runtime_factory(append_calls),
        stdin=TerminalInput("no\n", tty=False),
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == int(expected_exit)
    assert payload["success"] is False
    assert payload["exit_code"] == int(expected_exit)
    assert len(append_calls) == 1
    assert prepared.count("service") == 1
    assert prepared.count("app") == (1 if subcommand == "image-valid" else 0)
    assert metadata_reads == []
    assert attach_calls == []


def _run_runtime_factory(holder: list[FakeRuntime] | None = None):
    def factory(_config, *, cancellation_source):
        runtime = FakeRuntime(cancellation_source)
        discovery = _discovery()
        runtime.discovered_target = discovery.discovered_target
        runtime.target = CPU1_PROFILE
        runtime.cancellation = cancellation_source
        runtime.session = SimpleNamespace(client=SimpleNamespace())
        runtime.contexts = []

        def operation_context(progress=None):
            context = SimpleNamespace(
                session=runtime.session,
                target=runtime.target,
                progress=progress,
                cancellation=runtime.cancellation,
            )
            runtime.contexts.append(context)
            return context

        runtime.operation_context = operation_context
        if holder is not None:
            holder.append(runtime)
        return runtime

    return factory


def _run_metadata_summary() -> dict[str, int]:
    info = _discovery().discovered_target.device_info
    flash = CPU1_PROFILE.memory_map.flash
    assert flash is not None
    return {
        "metadata_valid": 1,
        "state": 1,
        "entry_point": flash.app_ranges[0].start,
        "image_size_words": 16,
        "image_crc32": 0xABCDEF01,
        "target_device_id": info.device_id,
        "target_cpu_id": info.cpu_id,
        "boot_attempt_count": 0,
        "app_confirmed": 0,
    }


def _run_success() -> OperationResult:
    summary = _run_metadata_summary()
    return OperationResult(
        True,
        "run_flash_app",
        CPU1_PROFILE.name,
        "RUN",
        {"entry_point": summary["entry_point"]},
    )


def test_run_non_tty_without_yes_requires_confirmation_and_does_not_run(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    metadata_calls: list[object] = []
    run_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda context: metadata_calls.append(context)
        or OperationResult(
            True,
            "get_metadata_summary",
            CPU1_PROFILE.name,
            "GET_METADATA_SUMMARY",
            _run_metadata_summary(),
        ),
    )
    monkeypatch.setattr(commands, "run_flash_app", lambda *args: run_calls.append(args))

    stdin = TerminalInput("y\n", tty=False)
    exit_code, stdout, stderr = invoke(
        ["--json", "--port", "COM1", "run"],
        _run_runtime_factory(runtimes),
        stdin=stdin,
    )

    assert exit_code == int(ExitCode.CONFIRMATION_REQUIRED)
    assert len(metadata_calls) == 1
    assert run_calls == []
    assert stdin.reads == 0
    assert runtimes[0].events == ["connect", "discover", "disconnect"]
    payload = json.loads(stdout.getvalue())
    assert payload["command"] == "run"
    assert payload["exit_code"] == int(ExitCode.CONFIRMATION_REQUIRED)
    assert "stdin is not a TTY" in stderr.getvalue()


def test_run_interactive_decline_does_not_run(monkeypatch) -> None:
    run_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda _context: OperationResult(
            True,
            "get_metadata_summary",
            CPU1_PROFILE.name,
            "GET_METADATA_SUMMARY",
            _run_metadata_summary(),
        ),
    )
    monkeypatch.setattr(commands, "run_flash_app", lambda *args: run_calls.append(args))

    exit_code, stdout, stderr = invoke(
        ["--json", "--port", "COM1", "run"],
        _run_runtime_factory(),
        stdin=TerminalInput("no\n", tty=True),
    )

    assert exit_code == int(ExitCode.USER_DECLINED)
    assert run_calls == []
    payload = json.loads(stdout.getvalue())
    assert payload["exit_code"] == int(ExitCode.USER_DECLINED)
    assert payload["error"]["code"] == "USER_DECLINED"
    assert "Proceed? [y/N]" in stderr.getvalue()


def test_run_yes_runs_once_disconnects_once_and_makes_no_health_claim(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    metadata_calls: list[object] = []
    run_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda context: metadata_calls.append(context)
        or OperationResult(
            True,
            "get_metadata_summary",
            CPU1_PROFILE.name,
            "GET_METADATA_SUMMARY",
            _run_metadata_summary(),
        ),
    )
    monkeypatch.setattr(
        commands,
        "run_flash_app",
        lambda context, request: run_calls.append((context, request)) or _run_success(),
    )

    stdin = TerminalInput("no\n", tty=False)
    exit_code, stdout, stderr = invoke(
        ["--port", "COM1", "run", "--yes"],
        _run_runtime_factory(runtimes),
        stdin=stdin,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert len(metadata_calls) == 1
    assert len(run_calls) == 1
    assert run_calls[0][1].entry_point == _run_metadata_summary()["entry_point"]
    assert runtimes[0].events == ["connect", "discover", "disconnect"]
    assert stdin.reads == 0
    assert stderr.getvalue() == ""
    rendered = stdout.getvalue().lower()
    assert "healthy" not in rendered
    assert "confirmed" not in rendered
    assert "started successfully" not in rendered
    assert "run: pass" in rendered


def test_run_communication_failure_is_not_retried_and_disconnects_once(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    run_calls: list[object] = []
    metadata_calls: list[object] = []
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda context: metadata_calls.append(context)
        or OperationResult(
            True,
            "get_metadata_summary",
            CPU1_PROFILE.name,
            "GET_METADATA_SUMMARY",
            _run_metadata_summary(),
        ),
    )
    run_failure = OperationResult(
        False,
        "run_flash_app",
        CPU1_PROFILE.name,
        "RUN",
        {},
        error=OperationErrorInfo(
            "PROTOCOL_ERROR",
            "RUN response was not received",
            "RUN",
            domain=ErrorDomain.COMMUNICATION,
        ),
    )
    monkeypatch.setattr(
        commands,
        "run_flash_app",
        lambda *args: run_calls.append(args) or run_failure,
    )

    exit_code, stdout, _stderr = invoke(
        ["--json", "--port", "COM1", "run", "--yes"],
        _run_runtime_factory(runtimes),
    )

    assert exit_code == int(ExitCode.COMMUNICATION_FAILURE)
    assert len(metadata_calls) == 1
    assert len(run_calls) == 1
    assert runtimes[0].events == ["connect", "discover", "disconnect"]
    payload = json.loads(stdout.getvalue())
    assert payload["exit_code"] == int(ExitCode.COMMUNICATION_FAILURE)
    assert payload["error"]["domain"] == "communication"


@pytest.mark.parametrize(
    ("arguments", "command"),
    [
        (["metadata", "image-valid", "--image"], "metadata image-valid"),
        (["metadata", "boot-attempt", "--image"], "metadata boot-attempt"),
        (["metadata", "app-confirmed", "--image"], "metadata app-confirmed"),
        (["run", "--entry-point"], "run"),
    ],
)
def test_b04_json_parser_errors_keep_command_label(arguments: list[str], command: str) -> None:
    exit_code, stdout, _stderr = invoke(
        ["--json", *arguments],
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("runtime must not start")),
    )

    assert exit_code == int(ExitCode.CLI_USAGE_ERROR)
    payload = json.loads(stdout.getvalue())
    assert payload["command"] == command
    assert payload["exit_code"] == int(ExitCode.CLI_USAGE_ERROR)


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
