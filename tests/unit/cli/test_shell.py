from __future__ import annotations

import io
import importlib
import json
import signal
from types import SimpleNamespace

import pytest

import bootloader_upgrade_tool.cli.commands as commands
import bootloader_upgrade_tool.cli.shell as shell_module
from bootloader_upgrade_tool.cli.output import CliError, CommandOutcome, ExitCode
from bootloader_upgrade_tool.operations import (
    DiscoveredTarget,
    ErrorDomain,
    OperationErrorInfo,
    OperationResult,
    TargetDiscoveryOutcome,
)
from bootloader_upgrade_tool.protocol.boot_protocol_client import ProtocolInfo
from bootloader_upgrade_tool.protocol.boot_protocol_client import BootProtocolClient
from bootloader_upgrade_tool.protocol.constants import Command, CpuId, DeviceId, PacketType
from bootloader_upgrade_tool.protocol.frame import Frame
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.targets import CPU1_PROFILE
from bootloader_upgrade_tool.transport import TransportError, TransportOpenResult, TransportOpenStatus


main_module = importlib.import_module("bootloader_upgrade_tool.cli.main")


class TerminalInput(io.StringIO):
    def __init__(self, value: str, *, tty: bool = False) -> None:
        super().__init__(value)
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


class SignalInterruptingInput(TerminalInput):
    def __init__(self, value: str, *, prompt_handler, tty: bool = False) -> None:
        super().__init__(value, tty=tty)
        self.prompt_handler = prompt_handler
        self.interrupts = 0
        self.installed_handlers: list[object] = []

    def readline(self, *args, **kwargs) -> str:
        if self.interrupts == 0:
            self.interrupts += 1
            handler = signal.getsignal(signal.SIGINT)
            self.installed_handlers.append(handler)
            assert handler is self.prompt_handler
            handler(signal.SIGINT, None)
        return super().readline(*args, **kwargs)


def _device_info() -> DeviceInfo:
    return DeviceInfo(int(DeviceId.F28377D), int(CpuId.CPU1), 1, 0, 0, 1, 0, 256, 8, 2, 2)


class FakeRuntime:
    def __init__(
        self,
        source,
        *,
        fail_discoveries: set[int] | None = None,
        cancel_connects: set[int] | None = None,
        client_factory=None,
    ) -> None:
        self.source = source
        self.sources: list[object] = []
        self.cancellation = source
        self.config = None
        self.events: list[str] = []
        self.connect_calls = 0
        self.discover_calls = 0
        self.disconnect_calls = 0
        self.fail_discoveries = fail_discoveries or set()
        self.cancel_connects = cancel_connects or set()
        self.client_factory = client_factory
        self.is_connected = False
        self.generation = 0
        self.session = None
        self.target = None
        self.discovered_target = None

    def connect(self, token):
        self.sources.append(token)
        self.source = token
        self.cancellation = token
        self.connect_calls += 1
        self.generation = self.connect_calls
        self.events.append(f"connect{self.generation}")
        if self.client_factory is not None:
            client = self.client_factory()
        else:
            client = SimpleNamespace(
                device_info=_device_info(),
                protocol_info=ProtocolInfo(1, 1, 1, 10, 1, 1, 128, 0),
                effective_max_payload_words=128,
                effective_max_data_words=8,
                effective_max_write_data_words=8,
            )
        self.session = SimpleNamespace(client=client)
        if self.connect_calls in self.cancel_connects:
            self.is_connected = False
            self.session = None
            return TransportOpenResult(
                TransportOpenStatus.CANCELLED,
                True,
                "BEFORE_SERIAL_OPEN",
            )
        self.is_connected = True
        return TransportOpenResult(TransportOpenStatus.OPENED, False, "OPEN_COMPLETE")

    def discover(self):
        self.discover_calls += 1
        self.events.append(f"discover{self.generation}")
        if self.discover_calls in self.fail_discoveries:
            return TargetDiscoveryOutcome(
                OperationResult(
                    False,
                    "discover_connected_target",
                    "discovery",
                    "GET_DEVICE_INFO",
                    {},
                    error=OperationErrorInfo(
                        "PROTOCOL_ERROR",
                        "discovery failed",
                        "GET_DEVICE_INFO",
                        domain=ErrorDomain.COMMUNICATION,
                    ),
                ),
                None,
            )
        info = self.session.client.device_info
        self.discovered_target = DiscoveredTarget(info, CPU1_PROFILE, "cpu1")
        self.target = CPU1_PROFILE
        return TargetDiscoveryOutcome(
            OperationResult(
                True,
                "discover_connected_target",
                "discovery",
                "RESOLVE_TARGET",
                {"target_key": "cpu1"},
            ),
            self.discovered_target,
        )

    def operation_context(self, progress=None):
        return SimpleNamespace(
            session=self.session,
            target=self.target,
            progress=progress,
            cancellation=self.cancellation,
        )

    def flash_operation_context(self, service, progress=None):
        return SimpleNamespace(
            session=self.session,
            target=self.target,
            progress=progress,
            cancellation=self.cancellation,
            service=service,
            force_service_attach=False,
        )

    def disconnect(self):
        self.disconnect_calls += 1
        self.events.append(f"disconnect{self.generation}")
        self.is_connected = False
        self.session = None
        self.target = None
        self.discovered_target = None


def _factory(
    holder: list[FakeRuntime],
    *,
    fail_discoveries: set[int] | None = None,
    cancel_connects: set[int] | None = None,
    client_factory=None,
):
    def factory(config, *, cancellation_source):
        runtime = FakeRuntime(
            cancellation_source,
            fail_discoveries=fail_discoveries,
            cancel_connects=cancel_connects,
            client_factory=client_factory,
        )
        runtime.config = config
        holder.append(runtime)
        return runtime

    return factory


class BoundaryFrameReader:
    def __init__(self, transport: "BoundaryTransport") -> None:
        self.transport = transport

    def read_frame(self, **_kwargs):
        if self.transport.read_error is not None:
            raise self.transport.read_error
        if self.transport.response is None:
            raise AssertionError("a response frame was not prepared")
        return self.transport.response


class BoundaryTransport:
    def __init__(self, *, write_error: Exception | None = None, read_error: Exception | None = None) -> None:
        self.write_error = write_error
        self.read_error = read_error
        self.response = None
        self.writes: list[bytes] = []

    def open(self, cancellation=None):
        del cancellation
        return TransportOpenResult(TransportOpenStatus.OPENED, False, "OPEN_COMPLETE")

    def close(self) -> None:
        pass

    def write_all(self, data: bytes) -> None:
        self.writes.append(data)
        words = tuple(data[index] | (data[index + 1] << 8) for index in range(0, len(data), 2))
        if self.write_error is not None:
            raise self.write_error
        self.response = Frame(PacketType.RESPONSE, words[4], words[5])

    def read_some(self, max_bytes: int) -> bytes:
        del max_bytes
        return b""


def _boundary_client(
    transports: list[BoundaryTransport],
    *,
    write_error: Exception | None = None,
    read_error: Exception | None = None,
) -> BootProtocolClient:
    transport = BoundaryTransport(write_error=write_error, read_error=read_error)
    transports.append(transport)
    client = BootProtocolClient(transport, BoundaryFrameReader(transport))  # type: ignore[arg-type]
    client._device_info = _device_info()
    client._protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, 128, 0)
    return client


def _invoke(
    script: str,
    runtime_factory,
    *,
    outer: list[str] | None = None,
    tty: bool = False,
    input_stream: TerminalInput | None = None,
):
    stdout = io.StringIO()
    stderr = io.StringIO()
    stdin = input_stream if input_stream is not None else TerminalInput(script, tty=tty)
    argv = ["--json", "--port", "COM1", "shell", *(outer or [])]
    exit_code = main_module.main(
        argv,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        runtime_factory=runtime_factory,
    )
    return exit_code, stdout, stderr, stdin


def _documents(stdout: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def _success(command: str, result=None) -> CommandOutcome:
    return CommandOutcome(command, result={"ok": True} if result is None else result)


def _operation(
    name: str,
    *,
    ok: bool = True,
    domain: ErrorDomain | None = None,
    error_code: str = "PROTOCOL_ERROR",
) -> OperationResult:
    error = None
    if not ok:
        error = OperationErrorInfo(
            error_code,
            "operation failed",
            "RUN" if name == "run_flash_app" else "RUN_RAM",
            domain=domain or ErrorDomain.OPERATION,
        )
    return OperationResult(
        ok,
        name,
        CPU1_PROFILE.name,
        "RUN" if name == "run_flash_app" else "RUN_RAM",
        {},
        error=error,
    )


def _metadata_result(*, valid: bool = True) -> OperationResult:
    return OperationResult(
        True,
        "get_metadata_summary",
        CPU1_PROFILE.name,
        "GET_METADATA_SUMMARY",
        {
            "metadata_valid": 1 if valid else 0,
            "state": 1 if valid else 0,
            "entry_point": 0x082400,
            "image_crc32": 1,
            "image_size_words": 8,
            "target_device_id": int(DeviceId.F28377D),
            "target_cpu_id": int(CpuId.CPU1),
        },
    )


def test_initial_success_enters_one_connection_and_reuses_it(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[str] = []
    monkeypatch.setattr(
        shell_module,
        "execute_command",
        lambda runtime, args, progress, **_kwargs: calls.append(args.command) or _success(args.command),
    )

    exit_code, stdout, stderr, _stdin = _invoke("status\nexit\n", _factory(runtimes))

    assert exit_code == 0
    assert calls == ["status"]
    assert runtimes[0].events == ["connect1", "discover1", "disconnect1"]
    assert len(_documents(stdout)) == 1
    assert stderr.getvalue() == ""


@pytest.mark.parametrize("script", ["quit\n", ""])
def test_quit_and_eof_exit_zero_and_release_connection(script: str) -> None:
    runtimes: list[FakeRuntime] = []

    exit_code, _stdout, _stderr, _stdin = _invoke(script, _factory(runtimes))

    assert exit_code == 0
    assert runtimes[0].events == ["connect1", "discover1", "disconnect1"]


def test_initial_discovery_failure_stays_alive_for_explicit_connect(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[str] = []
    monkeypatch.setattr(
        shell_module,
        "execute_command",
        lambda runtime, args, progress, **_kwargs: calls.append(args.command) or _success(args.command),
    )

    exit_code, stdout, _stderr, _stdin = _invoke(
        "connect\nstatus\nexit\n",
        _factory(runtimes, fail_discoveries={1}),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == ["status"]
    assert documents[0]["command"] == "connect"
    assert documents[0]["success"] is False
    assert documents[1]["command"] == "connect"
    assert documents[1]["success"] is True
    assert runtimes[0].events == [
        "connect1",
        "discover1",
        "disconnect1",
        "connect2",
        "discover2",
        "disconnect2",
    ]


def test_disconnected_target_command_is_gated_without_auto_reconnect(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[str] = []
    monkeypatch.setattr(
        shell_module,
        "execute_command",
            lambda runtime, args, progress, **_kwargs: calls.append(args.command) or _success(args.command),
    )

    exit_code, stdout, _stderr, _stdin = _invoke(
        "disconnect\nping\nprogram --image app.out --yes\nexit\n",
        _factory(runtimes),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == []
    assert documents[0]["command"] == "disconnect"
    assert [item["error"]["code"] for item in documents[1:]] == [
        "NOT_CONNECTED",
        "NOT_CONNECTED",
    ]
    assert runtimes[0].connect_calls == 1
    assert runtimes[0].events == ["connect1", "discover1", "disconnect1"]


def test_initial_open_cancellation_stays_alive_for_explicit_connect(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[str] = []
    monkeypatch.setattr(
        shell_module,
        "execute_command",
        lambda runtime, args, progress, **_kwargs: calls.append(args.command) or _success(args.command),
    )

    exit_code, stdout, _stderr, _stdin = _invoke(
        "connect\nstatus\nexit\n",
        _factory(runtimes, cancel_connects={1}),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == ["status"]
    assert documents[0]["command"] == "connect"
    assert documents[0]["error"]["code"] == "CANCELLED"
    assert documents[1]["success"] is True
    assert documents[2]["success"] is True
    assert runtimes[0].events == [
        "connect1",
        "connect2",
        "discover2",
        "disconnect2",
    ]


def test_prompt_ctrl_c_restores_prompt_handler_and_keeps_generation_clean(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[str] = []
    monkeypatch.setattr(
        shell_module,
        "execute_command",
        lambda runtime, args, progress, **_kwargs: calls.append(args.command) or _success(args.command),
    )
    prompt_interrupts = 0

    def prompt_handler(_signum, _frame):
        nonlocal prompt_interrupts
        prompt_interrupts += 1
        raise KeyboardInterrupt

    previous_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, prompt_handler)
    stdin = SignalInterruptingInput("status\nexit\n", prompt_handler=prompt_handler)
    try:
        exit_code, _stdout, _stderr, _stdin = _invoke(
            "",
            _factory(runtimes),
            input_stream=stdin,
        )
    finally:
        signal.signal(signal.SIGINT, previous_handler)

    assert exit_code == 0
    assert stdin.interrupts == 1
    assert prompt_interrupts == 1
    assert stdin.installed_handlers == [prompt_handler]
    assert calls == ["status"]
    assert not runtimes[0].sources[0].is_cancel_requested()
    assert runtimes[0].events == ["connect1", "discover1", "disconnect1"]


def test_operation_ctrl_c_uses_cooperative_generation_handler(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    observed_cancellation: list[bool] = []
    observed_handlers: list[object] = []

    def execute(runtime, args, progress, **_kwargs):
        handler = signal.getsignal(signal.SIGINT)
        observed_handlers.append(handler)
        handler(signal.SIGINT, None)
        observed_cancellation.append(runtime.cancellation.is_cancel_requested())
        return _success(args.command)

    monkeypatch.setattr(shell_module, "execute_command", execute)
    exit_code, _stdout, _stderr, _stdin = _invoke(
        "status\nexit\n",
        _factory(runtimes),
    )

    assert exit_code == 0
    assert len(observed_handlers) == 1
    assert observed_handlers[0] is not signal.default_int_handler
    assert observed_cancellation == [True]
    assert not runtimes[0].sources[0].is_cancel_requested()


def test_reconnect_creates_a_new_connection_generation(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    generations: list[int] = []

    def execute(runtime, args, progress, **_kwargs):
        generations.append(runtime.generation)
        return _success(args.command)

    monkeypatch.setattr(shell_module, "execute_command", execute)

    exit_code, _stdout, _stderr, _stdin = _invoke(
        "reconnect\nstatus\nexit\n",
        _factory(runtimes),
    )

    assert exit_code == 0
    assert generations == [2]
    assert runtimes[0].sources[0] is not runtimes[0].sources[1]
    assert runtimes[0].events == [
        "connect1",
        "discover1",
        "disconnect1",
        "connect2",
        "discover2",
        "disconnect2",
    ]


def test_service_sources_are_retained_across_reconnect(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    service_args: list[tuple[str, str]] = []

    def execute(runtime, args, progress, **_kwargs):
        service_args.append((args.flash_service_image, args.flash_service_map))
        return _success(args.command)

    monkeypatch.setattr(shell_module, "execute_command", execute)
    exit_code, _stdout, _stderr, _stdin = _invoke(
        "disconnect\nconnect\nprogram --image app.out --yes\nexit\n",
        _factory(runtimes),
        outer=[
            "--flash-service-image",
            "A.out",
            "--flash-service-map",
            "A.map",
        ],
    )

    assert exit_code == 0
    assert service_args == [("A.out", "A.map")]
    assert runtimes[0].events == [
        "connect1",
        "discover1",
        "disconnect1",
        "connect2",
        "discover2",
        "disconnect2",
    ]


def test_service_use_replaces_sources_without_a_target_operation(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[tuple[str, str, str]] = []

    def execute(runtime, args, progress, **_kwargs):
        calls.append((args.command, args.flash_service_image, args.flash_service_map))
        return _success(args.command)

    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: pytest.fail("service use must not prepare a service"),
    )
    monkeypatch.setattr(
        commands,
        "attach_flash_service",
        lambda *_args, **_kwargs: pytest.fail("service use must not attach a service"),
    )
    monkeypatch.setattr(shell_module, "execute_command", execute)
    exit_code, stdout, _stderr, _stdin = _invoke(
        "disconnect\n"
        "service use --flash-service-image B.out --flash-service-map B.map\n"
        "connect\n"
        "program --image app.out --yes\nexit\n",
        _factory(runtimes),
        outer=["--flash-service-image", "A.out", "--flash-service-map", "A.map"],
    )

    assert exit_code == 0
    assert calls == [("program", "B.out", "B.map")]
    assert [item["command"] for item in _documents(stdout)] == [
        "disconnect",
        "service use",
        "connect",
        "program",
    ]
    assert runtimes[0].events == [
        "connect1",
        "discover1",
        "disconnect1",
        "connect2",
        "discover2",
        "disconnect2",
    ]


def test_invalid_service_use_preserves_old_pair_and_touches_no_target(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[tuple[str, str, str]] = []

    def execute(runtime, args, progress, **_kwargs):
        calls.append((args.command, args.flash_service_image, args.flash_service_map))
        return _success(args.command)

    monkeypatch.setattr(
        commands,
        "prepare_service_image",
        lambda *_args, **_kwargs: pytest.fail("invalid service use must not prepare a service"),
    )
    monkeypatch.setattr(
        commands,
        "attach_flash_service",
        lambda *_args, **_kwargs: pytest.fail("invalid service use must not attach a service"),
    )
    monkeypatch.setattr(shell_module, "execute_command", execute)
    exit_code, stdout, _stderr, _stdin = _invoke(
        "service use --flash-service-image new.out\nprogram --image app.out --yes\nexit\n",
        _factory(runtimes),
        outer=["--flash-service-image", "old.out", "--flash-service-map", "old.map"],
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["error"]["code"] == "CLI_USAGE_ERROR"
    assert calls == [("program", "old.out", "old.map")]
    assert runtimes[0].connect_calls == 1
    assert runtimes[0].discover_calls == 1


def test_missing_service_sources_fail_before_execute(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[str] = []
    monkeypatch.setattr(
        shell_module,
        "execute_command",
        lambda runtime, args, progress, **_kwargs: calls.append(args.command) or _success(args.command),
    )

    exit_code, stdout, _stderr, _stdin = _invoke(
        "program --image app.out --yes\nexit\n",
        _factory(runtimes),
    )

    assert exit_code == 0
    assert calls == []
    assert _documents(stdout)[0]["error"]["code"] == "SERVICE_RESOURCE_REQUIRED"


def test_shell_uses_shlex_for_quoted_windows_paths(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    images: list[str] = []

    def execute(runtime, args, progress, **_kwargs):
        images.append(args.image)
        return _success(args.command)

    monkeypatch.setattr(shell_module, "execute_command", execute)
    exit_code, _stdout, _stderr, _stdin = _invoke(
        'verify --image "D:\\Images\\app build.out"\nexit\n',
        _factory(runtimes),
        outer=["--flash-service-image", "service.out", "--flash-service-map", "service.map"],
    )

    assert exit_code == 0
    assert images == [r"D:\Images\app build.out"]


def test_unterminated_shell_quote_is_a_command_error_and_loop_continues(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[str] = []
    monkeypatch.setattr(
        shell_module,
        "execute_command",
        lambda runtime, args, progress, **_kwargs: calls.append(args.command) or _success(args.command),
    )

    exit_code, stdout, _stderr, _stdin = _invoke(
        'status --image "unterminated\nstatus\nexit\n',
        _factory(runtimes),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["success"] is False
    assert documents[1]["success"] is True
    assert calls == ["status"]


def test_shell_fixed_options_are_rejected_without_reconnect(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[str] = []
    monkeypatch.setattr(
        shell_module,
        "execute_command",
        lambda runtime, args, progress, **_kwargs: calls.append(args.command) or _success(args.command),
    )

    exit_code, stdout, _stderr, _stdin = _invoke(
        "status --port COM99\nstatus --baud 115200\nstatus --json\nexit\n",
        _factory(runtimes),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == []
    assert [item["error"]["code"] for item in documents] == [
        "CLI_USAGE_ERROR",
        "CLI_USAGE_ERROR",
        "CLI_USAGE_ERROR",
    ]
    assert runtimes[0].config.port == "COM1"
    assert runtimes[0].connect_calls == 1


def test_ping_uses_the_public_operation_and_keeps_connection(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    ping_contexts: list[object] = []

    def fake_ping(context):
        ping_contexts.append(context)
        return OperationResult(True, "ping", CPU1_PROFILE.name, "PING", {})

    monkeypatch.setattr(commands, "ping", fake_ping)
    exit_code, stdout, _stderr, _stdin = _invoke("ping\nexit\n", _factory(runtimes))

    assert exit_code == 0
    assert len(ping_contexts) == 1
    assert runtimes[0].events == ["connect1", "discover1", "disconnect1"]
    assert _documents(stdout)[0]["command"] == "ping"
    assert _documents(stdout)[0]["success"] is True


def test_per_command_failure_does_not_stop_later_commands(monkeypatch) -> None:
    calls: list[str] = []
    runtimes: list[FakeRuntime] = []
    failure = CommandOutcome(
        "ping",
        error=CliError("operation", "OPERATION_FAILURE", "failed"),
        exit_code=ExitCode.OPERATION_FAILURE,
    )
    monkeypatch.setattr(shell_module, "handle_ping", lambda runtime, progress: failure)
    monkeypatch.setattr(
        shell_module,
        "execute_command",
        lambda runtime, args, progress, **_kwargs: calls.append(args.command) or _success(args.command),
    )

    exit_code, stdout, _stderr, _stdin = _invoke("ping\nstatus\nexit\n", _factory(runtimes))
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["success"] is False
    assert documents[1]["success"] is True
    assert calls == ["status"]


def test_cancelled_command_does_not_poison_the_next_command(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    cancellation_states: list[bool] = []
    calls = 0

    def execute(runtime, args, progress, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            runtime.source.request()
            return CommandOutcome(
                args.command,
                error=CliError("cli", "CANCELLED", "cancelled"),
                exit_code=ExitCode.CANCELLED,
            )
        cancellation_states.append(runtime.cancellation.is_cancel_requested())
        return _success(args.command)

    monkeypatch.setattr(shell_module, "execute_command", execute)
    exit_code, _stdout, _stderr, _stdin = _invoke(
        "status\nstatus\nexit\n",
        _factory(runtimes),
    )

    assert exit_code == 0
    assert cancellation_states == [False]


def _success_operation(name: str, stage: str) -> OperationResult:
    return OperationResult(True, name, CPU1_PROFILE.name, stage, {})


def _failure_operation(
    name: str,
    stage: str,
    *,
    code: str = "DSP_STATUS_ERROR",
    domain: ErrorDomain = ErrorDomain.OPERATION,
) -> OperationResult:
    return OperationResult(
        False,
        name,
        CPU1_PROFILE.name,
        stage,
        {},
        error=OperationErrorInfo(code, "operation failed", stage, domain=domain),
    )


def _install_real_flash_run(
    monkeypatch,
    *,
    run_result: OperationResult | None = None,
    run_exception: Exception | None = None,
    metadata: OperationResult | None = None,
    wire_attempted: bool = True,
) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: metadata or _metadata_result())

    def fake_run(_context, request, *, wire_attempt_observer=None):
        calls.append(request.entry_point)
        if wire_attempted:
            assert wire_attempt_observer is not None
            wire_attempt_observer(int(Command.RUN))
        if run_exception is not None:
            raise run_exception
        return run_result or _operation("run_flash_app")

    monkeypatch.setattr(commands, "run_flash_app", fake_run)
    return calls


@pytest.mark.parametrize(
    ("case", "expected_connected"),
    [
        ("success", False),
        ("communication", False),
        ("dsp_status", False),
        ("unsupported", True),
        ("payload_limit", True),
        ("unknown", False),
    ],
)
def test_flash_run_real_handler_observes_actual_release_boundary(
    monkeypatch,
    case: str,
    expected_connected: bool,
) -> None:
    runtimes: list[FakeRuntime] = []
    result = _operation("run_flash_app")
    run_exception = RuntimeError("run crashed") if case == "unknown" else None
    if case not in {"success", "unknown"}:
        result = _operation(
            "run_flash_app",
            ok=False,
            domain=ErrorDomain.COMMUNICATION if case == "communication" else ErrorDomain.OPERATION,
            error_code={
                "communication": "PROTOCOL_ERROR",
                "dsp_status": "DSP_STATUS_ERROR",
                "unsupported": "UNSUPPORTED_OPERATION",
                "payload_limit": "PAYLOAD_LIMIT_EXCEEDED",
            }[case],
        )
    calls = _install_real_flash_run(
        monkeypatch,
        run_result=result,
        run_exception=run_exception,
        wire_attempted=case not in {"unsupported", "payload_limit"},
    )

    follow_up = "status\n" if expected_connected else "ping\nlast-error\nstatus\n"
    exit_code, stdout, _stderr, _stdin = _invoke(
        f"run --yes\n{follow_up}exit\n",
        _factory(runtimes),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == [0x082400]
    assert runtimes[0].disconnect_calls == 1
    if expected_connected:
        assert documents[1]["success"] is True
    else:
        assert [item["error"]["code"] for item in documents[1:]] == [
            "NOT_CONNECTED",
            "NOT_CONNECTED",
            "NOT_CONNECTED",
        ]


def test_flash_run_real_handler_unknown_exception_releases_connection(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls = _install_real_flash_run(monkeypatch, run_exception=RuntimeError("run crashed"))

    exit_code, stdout, _stderr, _stdin = _invoke(
        "run --yes\nstatus\nexit\n",
        _factory(runtimes),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == [0x082400]
    assert documents[0]["error"]["code"] == "INTERNAL_ERROR"
    assert documents[1]["error"]["code"] == "NOT_CONNECTED"
    assert runtimes[0].disconnect_calls == 1


def test_flash_run_admission_failure_stays_connected(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls = _install_real_flash_run(monkeypatch, metadata=_metadata_result(valid=False))

    exit_code, stdout, _stderr, _stdin = _invoke(
        "run --yes\nstatus\nexit\n",
        _factory(runtimes),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == []
    assert documents[0]["error"]["code"] == "IMAGE_VALID_REQUIRED"
    assert documents[1]["success"] is True
    assert runtimes[0].disconnect_calls == 1


def test_flash_run_confirmation_failure_stays_connected(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls = _install_real_flash_run(monkeypatch)

    exit_code, stdout, _stderr, _stdin = _invoke(
        "run\nstatus\nexit\n",
        _factory(runtimes),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == []
    assert documents[0]["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert documents[1]["success"] is True
    assert runtimes[0].disconnect_calls == 1


def test_flash_run_releases_after_actual_client_wire_attempt(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    transports: list[BoundaryTransport] = []
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: _metadata_result())

    exit_code, stdout, _stderr, _stdin = _invoke(
        "run --yes\nstatus\nexit\n",
        _factory(runtimes, client_factory=lambda: _boundary_client(transports)),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["success"] is True
    assert documents[1]["error"]["code"] == "NOT_CONNECTED"
    assert runtimes[0].disconnect_calls == 1
    assert len(transports) == 1
    assert len(transports[0].writes) == 1


def test_flash_run_unknown_pre_wire_failure_stays_connected(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    transports: list[BoundaryTransport] = []
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: _metadata_result())
    original_encode = Frame.encode_bytes
    failed = False

    def fail_once(frame):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("encode failed")
        return original_encode(frame)

    monkeypatch.setattr(Frame, "encode_bytes", fail_once)
    exit_code, stdout, _stderr, _stdin = _invoke(
        "run --yes\nping\nexit\n",
        _factory(runtimes, client_factory=lambda: _boundary_client(transports)),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["error"]["code"] == "INTERNAL_ERROR"
    assert documents[1]["success"] is True
    assert runtimes[0].disconnect_calls == 1
    assert len(transports) == 1
    assert len(transports[0].writes) == 1


def test_flash_run_unknown_post_attempt_failure_releases_connection(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    transports: list[BoundaryTransport] = []
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: _metadata_result())
    exit_code, stdout, _stderr, _stdin = _invoke(
        "run --yes\nstatus\nexit\n",
        _factory(
            runtimes,
            client_factory=lambda: _boundary_client(
                transports,
                write_error=RuntimeError("write crashed"),
            ),
        ),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["error"]["code"] == "INTERNAL_ERROR"
    assert documents[1]["error"]["code"] == "NOT_CONNECTED"
    assert runtimes[0].disconnect_calls == 1
    assert len(transports[0].writes) == 1


def test_flash_run_response_failure_after_write_releases_connection(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    transports: list[BoundaryTransport] = []
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: _metadata_result())
    exit_code, stdout, _stderr, _stdin = _invoke(
        "run --yes\nstatus\nexit\n",
        _factory(
            runtimes,
            client_factory=lambda: _boundary_client(
                transports,
                read_error=TransportError("response failed"),
            ),
        ),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["error"]["code"] == "PROTOCOL_ERROR"
    assert documents[1]["error"]["code"] == "NOT_CONNECTED"
    assert runtimes[0].disconnect_calls == 1
    assert len(transports[0].writes) == 1


@pytest.mark.parametrize(
    ("case", "expected_connected"),
    [
        ("success", False),
        ("communication", False),
        ("dsp_status", False),
        ("unsupported", True),
        ("payload_limit", True),
        ("unknown", False),
    ],
)
def test_ram_run_real_handler_observes_release_boundary(
    monkeypatch,
    case: str,
    expected_connected: bool,
) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[int] = []
    result = _operation("run_ram_image")
    run_exception = RuntimeError("run-ram crashed") if case == "unknown" else None
    if case not in {"success", "unknown"}:
        result = _operation(
            "run_ram_image",
            ok=False,
            domain=ErrorDomain.COMMUNICATION if case == "communication" else ErrorDomain.OPERATION,
            error_code={
                "communication": "PROTOCOL_ERROR",
                "dsp_status": "DSP_STATUS_ERROR",
                "unsupported": "UNSUPPORTED_OPERATION",
                "payload_limit": "PAYLOAD_LIMIT_EXCEEDED",
            }[case],
        )

    def fake_run(_context, request, *, wire_attempt_observer=None):
        calls.append(request.entry_point)
        if case not in {"unsupported", "payload_limit"}:
            assert wire_attempt_observer is not None
            wire_attempt_observer(int(Command.RUN_RAM))
        if run_exception is not None:
            raise run_exception
        return result

    monkeypatch.setattr(commands, "run_ram_image", fake_run)
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: _metadata_result())
    exit_code, stdout, _stderr, _stdin = _invoke(
        "run-ram --entry-point 0x8000 --yes\nstatus\nexit\n",
        _factory(runtimes),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == [0x8000]
    if expected_connected:
        assert documents[1]["success"] is True
    else:
        assert documents[1]["error"]["code"] == "NOT_CONNECTED"
    assert runtimes[0].disconnect_calls == 1


def test_ram_run_admission_failure_stays_connected(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls: list[int] = []
    monkeypatch.setattr(commands, "run_ram_image", lambda _context, request: calls.append(request.entry_point))
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: _metadata_result())

    exit_code, stdout, _stderr, _stdin = _invoke(
        "run-ram --entry-point 0x2 --yes\nstatus\nexit\n",
        _factory(runtimes),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == []
    assert documents[0]["error"]["code"] == "INVALID_RAM_ENTRY_POINT"
    assert documents[1]["success"] is True
    assert runtimes[0].disconnect_calls == 1


def test_ram_run_releases_after_actual_client_wire_attempt(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    transports: list[BoundaryTransport] = []

    exit_code, stdout, _stderr, _stdin = _invoke(
        "run-ram --entry-point 0x8000 --yes\nstatus\nexit\n",
        _factory(runtimes, client_factory=lambda: _boundary_client(transports)),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["success"] is True
    assert documents[1]["error"]["code"] == "NOT_CONNECTED"
    assert runtimes[0].disconnect_calls == 1
    assert len(transports) == 1
    assert len(transports[0].writes) == 1


def test_ram_run_payload_pre_wire_failure_stays_connected(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    transports: list[BoundaryTransport] = []

    def client_factory():
        client = _boundary_client(transports)
        client._protocol_info = ProtocolInfo(1, 1, 1, 10, 1, 1, 2, 0)
        return client

    exit_code, stdout, _stderr, _stdin = _invoke(
        "run-ram --entry-point 0x8000 --yes\nping\nexit\n",
        _factory(runtimes, client_factory=client_factory),
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["error"]["code"] == "PAYLOAD_LIMIT_EXCEEDED"
    assert documents[1]["success"] is True
    assert runtimes[0].disconnect_calls == 1
    assert len(transports[0].writes) == 1


def _install_upgrade_operations(
    monkeypatch,
    *,
    run_result: OperationResult | None = None,
    run_exception: Exception | None = None,
    failure_stage: str | None = None,
    run_operation=None,
    wire_attempted: bool = True,
) -> list[str]:
    calls: list[str] = []
    app = SimpleNamespace(
        identity=SimpleNamespace(entry_point=0x082400, image_crc32=1, image_size_words=8)
    )
    monkeypatch.setattr(commands, "get_metadata_summary", lambda _context: _metadata_result())
    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(commands, "prepare_flash_app_image", lambda *_args, **_kwargs: app)

    operations = {
        "ERASE": ("erase_flash_image_area", "ERASE_FLASH_IMAGE_AREA"),
        "PROGRAM": ("program_flash_image", "PROGRAM"),
        "VERIFY": ("verify_flash_image", "VERIFY"),
        "IMAGE_VALID": ("append_image_valid", "METADATA_APPEND_RECORD"),
        "BOOT_ATTEMPT": ("append_boot_attempt", "METADATA_APPEND_RECORD"),
    }
    for stage, (attribute, operation_name) in operations.items():
        result = (
            _failure_operation(operation_name, stage)
            if stage == failure_stage
            else _success_operation(operation_name, stage)
        )
        monkeypatch.setattr(
            commands,
            attribute,
            lambda *_args, _stage=stage, _result=result: calls.append(_stage) or _result,
        )

    def fake_run(_context, request, *, wire_attempt_observer=None):
        calls.append("RUN")
        if wire_attempted:
            assert wire_attempt_observer is not None
            wire_attempt_observer(int(Command.RUN))
        if run_exception is not None:
            raise run_exception
        return run_result or _operation("run_flash_app")

    monkeypatch.setattr(commands, "run_flash_app", run_operation or fake_run)
    return calls


def test_upgrade_no_run_real_handler_stays_connected(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls = _install_upgrade_operations(monkeypatch)

    exit_code, stdout, _stderr, _stdin = _invoke(
        "upgrade --image app.out --no-run --yes\nstatus\nexit\n",
        _factory(runtimes),
        outer=["--flash-service-image", "service.out", "--flash-service-map", "service.map"],
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == ["ERASE", "PROGRAM", "VERIFY", "IMAGE_VALID"]
    assert documents[1]["success"] is True
    assert runtimes[0].disconnect_calls == 1


def test_upgrade_pre_run_failure_stays_connected(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls = _install_upgrade_operations(monkeypatch, failure_stage="VERIFY")

    exit_code, stdout, _stderr, _stdin = _invoke(
        "upgrade --image app.out --yes\nstatus\nexit\n",
        _factory(runtimes),
        outer=["--flash-service-image", "service.out", "--flash-service-map", "service.map"],
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == ["ERASE", "PROGRAM", "VERIFY"]
    assert documents[0]["success"] is False
    assert documents[1]["success"] is True
    assert runtimes[0].disconnect_calls == 1


@pytest.mark.parametrize(
    ("case", "expected_connected"),
    [
        ("success", False),
        ("communication", False),
        ("dsp_status", False),
        ("unsupported", True),
    ],
)
def test_upgrade_real_handler_observes_run_release_boundary(
    monkeypatch,
    case: str,
    expected_connected: bool,
) -> None:
    runtimes: list[FakeRuntime] = []
    result = _operation("run_flash_app")
    if case != "success":
        result = _operation(
            "run_flash_app",
            ok=False,
            domain=ErrorDomain.COMMUNICATION if case == "communication" else ErrorDomain.OPERATION,
            error_code={
                "communication": "PROTOCOL_ERROR",
                "dsp_status": "DSP_STATUS_ERROR",
                "unsupported": "UNSUPPORTED_OPERATION",
            }[case],
        )
    calls = _install_upgrade_operations(
        monkeypatch,
        run_result=result,
        wire_attempted=case != "unsupported",
    )

    follow_up = "status\n" if expected_connected else "ping\nstatus\n"
    exit_code, stdout, _stderr, _stdin = _invoke(
        f"upgrade --image app.out --yes\n{follow_up}exit\n",
        _factory(runtimes),
        outer=["--flash-service-image", "service.out", "--flash-service-map", "service.map"],
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == ["ERASE", "PROGRAM", "VERIFY", "IMAGE_VALID", "BOOT_ATTEMPT", "RUN"]
    assert runtimes[0].disconnect_calls == 1
    if expected_connected:
        assert documents[1]["success"] is True
    else:
        assert [documents[1]["error"]["code"], documents[2]["error"]["code"]] == [
            "NOT_CONNECTED",
            "NOT_CONNECTED",
        ]


def test_upgrade_unknown_run_exception_releases_connection(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    calls = _install_upgrade_operations(monkeypatch, run_exception=RuntimeError("run crashed"))

    exit_code, stdout, _stderr, _stdin = _invoke(
        "upgrade --image app.out --yes\nstatus\nexit\n",
        _factory(runtimes),
        outer=["--flash-service-image", "service.out", "--flash-service-map", "service.map"],
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls[-1] == "RUN"
    assert documents[0]["error"]["code"] == "INTERNAL_ERROR"
    assert documents[1]["error"]["code"] == "NOT_CONNECTED"
    assert runtimes[0].disconnect_calls == 1


def test_upgrade_reaches_actual_run_client_before_releasing_connection(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    transports: list[BoundaryTransport] = []
    real_run = commands.run_flash_app

    def run_operation(context, request, *, wire_attempt_observer=None):
        calls.append("RUN")
        assert context.cancellation is None
        return real_run(
            context,
            request,
            wire_attempt_observer=wire_attempt_observer,
        )

    calls = _install_upgrade_operations(monkeypatch, run_operation=run_operation)
    exit_code, stdout, _stderr, _stdin = _invoke(
        "upgrade --image app.out --yes\nstatus\nexit\n",
        _factory(runtimes, client_factory=lambda: _boundary_client(transports)),
        outer=["--flash-service-image", "service.out", "--flash-service-map", "service.map"],
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == ["ERASE", "PROGRAM", "VERIFY", "IMAGE_VALID", "BOOT_ATTEMPT", "RUN"]
    assert documents[0]["success"] is True
    assert documents[1]["error"]["code"] == "NOT_CONNECTED"
    assert len(transports) == 1
    assert len(transports[0].writes) == 1
    assert runtimes[0].disconnect_calls == 1


def test_upgrade_no_run_has_no_actual_run_wire_attempt(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    transports: list[BoundaryTransport] = []
    real_run = commands.run_flash_app

    def run_operation(context, request, *, wire_attempt_observer=None):
        return real_run(
            context,
            request,
            wire_attempt_observer=wire_attempt_observer,
        )

    calls = _install_upgrade_operations(monkeypatch, run_operation=run_operation)
    exit_code, stdout, _stderr, _stdin = _invoke(
        "upgrade --image app.out --no-run --yes\nstatus\nexit\n",
        _factory(runtimes, client_factory=lambda: _boundary_client(transports)),
        outer=["--flash-service-image", "service.out", "--flash-service-map", "service.map"],
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert calls == ["ERASE", "PROGRAM", "VERIFY", "IMAGE_VALID"]
    assert documents[1]["success"] is True
    assert transports[0].writes == []
    assert runtimes[0].disconnect_calls == 1


def test_shell_help_lists_shell_and_stable_target_command_forms() -> None:
    runtimes: list[FakeRuntime] = []

    exit_code, stdout, _stderr, _stdin = _invoke("help\nexit\n", _factory(runtimes))
    document = _documents(stdout)[0]
    result = document["result"]
    reference = "\n".join(str(value) for value in result.values())

    assert exit_code == 0
    assert document["success"] is True
    for form in (
        "connect",
        "disconnect",
        "reconnect",
        "ping",
        "help",
        "exit",
        "quit",
        "status",
        "metadata image-valid",
        "service attach",
        "ram load",
        "memory read",
        "run",
        "run-ram",
        "upgrade",
    ):
        assert form in reference
    assert "service use --flash-service-image <path> --flash-service-map <path>" in reference
    assert "does not connect" in reference


def test_json_shell_has_one_document_per_non_exit_command_and_no_prompt() -> None:
    runtimes: list[FakeRuntime] = []
    exit_code, stdout, stderr, _stdin = _invoke(
        "help\nservice use --flash-service-image A.out --flash-service-map A.map\nexit\n",
        _factory(runtimes),
    )

    assert exit_code == 0
    assert [item["command"] for item in _documents(stdout)] == ["help", "service use"]
    assert "bootloader[" not in stderr.getvalue()


def test_shell_dangerous_command_reuses_confirmation_requester(monkeypatch) -> None:
    runtimes: list[FakeRuntime] = []
    prepared_image = SimpleNamespace(
        identity=SimpleNamespace(entry_point=0x082400, image_crc32=1, image_size_words=8)
    )
    program_calls: list[object] = []
    monkeypatch.setattr(commands, "prepare_service_image", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(commands, "prepare_flash_app_image", lambda *_args, **_kwargs: prepared_image)
    monkeypatch.setattr(
        commands,
        "program_flash_image",
        lambda _context, request: program_calls.append(request) or _operation("program_flash_image"),
    )
    monkeypatch.setattr(
        commands,
        "get_metadata_summary",
        lambda _context: OperationResult(
            True,
            "get_metadata_summary",
            CPU1_PROFILE.name,
            "GET_METADATA_SUMMARY",
            {},
        ),
    )

    exit_code, stdout, stderr, _stdin = _invoke(
        "program --image app.out\nstatus\nexit\n",
        _factory(runtimes),
        outer=["--flash-service-image", "service.out", "--flash-service-map", "service.map"],
    )
    documents = _documents(stdout)

    assert exit_code == 0
    assert documents[0]["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert documents[1]["success"] is True
    assert program_calls == []
    assert "stdin is not a TTY" in stderr.getvalue()
