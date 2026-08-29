from __future__ import annotations

import pytest

from bootloader_upgrade_tool.cli.parser import (
    COMMANDS,
    CliUsageError,
    build_parser,
)


def parse(arguments: list[str]):
    return build_parser().parse_args(arguments)


def test_defaults_and_presentation_options() -> None:
    args = parse(["status"])

    assert args.transport == "serial"
    assert args.port is None
    assert args.baud == 9600
    assert args.timeout_ms is None
    assert not args.json
    assert not args.verbose

    args = parse(["--json", "--verbose", "status"])
    assert args.json and args.verbose


def test_global_options_are_accepted_after_a_command_too() -> None:
    args = parse(["memory", "read", "--address", "0x82400", "--words", "16", "--json"])
    assert args.json and args.address == 0x82400 and args.words == 16


@pytest.mark.parametrize("option", ["--baud", "--timeout-ms"])
@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_positive_integer_options_reject_invalid_values(option: str, value: str) -> None:
    with pytest.raises(CliUsageError):
        parse([option, value, "status"])


def test_memory_read_parses_c28x_word_address_and_positive_uint32_count() -> None:
    args = parse(["memory", "read", "--address", "0x82400", "--words", "16"])

    assert args.command == "memory read"
    assert args.address == 0x82400
    assert args.words == 16


@pytest.mark.parametrize(
    "arguments",
    [
        ["memory", "read", "--address", "-1", "--words", "1"],
        ["memory", "read", "--address", "0x100000000", "--words", "1"],
        ["memory", "read", "--address", "0", "--words", "0"],
        ["memory", "read", "--address", "0", "--words", "0x100000000"],
        ["memory", "read", "--address", "0xFFFFFFFF", "--words", "2"],
    ],
)
def test_memory_read_rejects_invalid_uint32_ranges(arguments: list[str]) -> None:
    with pytest.raises(CliUsageError):
        parse(arguments)


@pytest.mark.parametrize("command", COMMANDS)
def test_only_b02_commands_are_exposed(command: str) -> None:
    args = command.split()
    if command == "memory read":
        args.extend(["--address", "0", "--words", "1"])
    parsed = parse(args)
    assert parsed.command == command


@pytest.mark.parametrize(
    "arguments",
    [
        ["reset"],
        ["ping"],
        ["erase"],
        ["program"],
        ["verify"],
        ["service", "attach"],
        ["metadata", "image-valid"],
        ["run"],
        ["run-ram"],
        ["ram", "load"],
        ["upgrade"],
        ["shell"],
        ["--autobaud-mode", "always", "status"],
        ["--output", "out.json", "status"],
        ["--force-service-attach", "status"],
    ],
)
def test_b03_commands_and_legacy_options_are_rejected(arguments: list[str]) -> None:
    with pytest.raises(CliUsageError):
        parse(arguments)


def test_help_and_version_keep_standard_text_behavior(capsys) -> None:
    with pytest.raises(SystemExit) as help_exit:
        build_parser().parse_args(["--help"])
    assert help_exit.value.code == 0
    assert "memory" in capsys.readouterr().out

    with pytest.raises(SystemExit) as version_exit:
        build_parser().parse_args(["--version"])
    assert version_exit.value.code == 0
    assert "bootloader-cli" in capsys.readouterr().out
