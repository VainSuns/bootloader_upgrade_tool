from __future__ import annotations

import pytest

from bootloader_upgrade_tool.cli.parser import (
    COMMANDS,
    CliUsageError,
    build_parser,
    command_from_argv,
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


def _valid_command_args(command: str) -> list[str]:
    args = command.split()
    if command == "memory read":
        args.extend(["--address", "0", "--words", "1"])
    elif command == "erase":
        args.extend(
            [
                "--flash-service-image",
                "service.out",
                "--flash-service-map",
                "service.map",
                "--all-app",
            ]
        )
    elif command in {"program", "verify", "metadata image-valid"}:
        args.extend(
            [
                "--image",
                "app.out",
                "--flash-service-image",
                "service.out",
                "--flash-service-map",
                "service.map",
            ]
        )
    elif command in {"metadata boot-attempt", "metadata app-confirmed"}:
        args.extend(
            [
                "--flash-service-image",
                "service.out",
                "--flash-service-map",
                "service.map",
            ]
        )
    elif command == "service attach":
        args.extend(
            [
                "--flash-service-image",
                "service.out",
                "--flash-service-map",
                "service.map",
            ]
        )
    elif command in {"ram load", "ram check-crc"}:
        args.extend(["--image", "ram_app.out"])
    elif command == "run-ram":
        args.extend(["--entry-point", "0x8000"])
    elif command == "upgrade":
        args.extend(
            [
                "--image",
                "app.out",
                "--flash-service-image",
                "service.out",
                "--flash-service-map",
                "service.map",
            ]
        )
    return args


@pytest.mark.parametrize("command", COMMANDS)
def test_b04_command_tree_is_exposed(command: str) -> None:
    parsed = parse(_valid_command_args(command))
    assert parsed.command == command


@pytest.mark.parametrize(
    "arguments",
    [
        ["reset"],
        ["ping"],
        ["erase"],
        ["service", "reload"],
        ["ram"],
        ["shell"],
        ["--autobaud-mode", "always", "status"],
        ["--output", "out.json", "status"],
        ["--force-service-attach", "status"],
    ],
)
def test_b04_commands_and_legacy_options_are_rejected(arguments: list[str]) -> None:
    with pytest.raises(CliUsageError):
        parse(arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        ["erase", "--flash-service-image", "service.out", "--flash-service-map", "service.map"],
        [
            "erase",
            "--flash-service-image",
            "service.out",
            "--flash-service-map",
            "service.map",
            "--image",
            "app.out",
            "--all-app",
        ],
        [
            "erase",
            "--flash-service-image",
            "service.out",
            "--flash-service-map",
            "service.map",
            "--all-app",
            "--sector-mask",
            "0x2",
        ],
    ],
)
def test_erase_requires_exactly_one_selector(arguments: list[str]) -> None:
    with pytest.raises(CliUsageError):
        parse(arguments)


def test_yes_is_scoped_to_dangerous_commands() -> None:
    for command in (
        "erase",
        "program",
        "metadata image-valid",
        "metadata boot-attempt",
        "metadata app-confirmed",
        "run",
        "run-ram",
        "upgrade",
    ):
        assert parse(_valid_command_args(command) + ["--yes"]).yes

    for arguments in (
        _valid_command_args("verify") + ["--yes"],
        _valid_command_args("service attach") + ["--yes"],
        _valid_command_args("metadata status") + ["--yes"],
        _valid_command_args("ram load") + ["--yes"],
        _valid_command_args("ram check-crc") + ["--yes"],
        ["--yes", "status"],
    ):
        with pytest.raises(CliUsageError):
            parse(arguments)


@pytest.mark.parametrize(
    "command",
    [
        "erase",
        "program",
        "verify",
        "service attach",
        "metadata image-valid",
        "metadata boot-attempt",
        "metadata app-confirmed",
    ],
)
def test_flash_service_resources_are_required(command: str) -> None:
    args = command.split()
    if command == "erase":
        args.extend(["--all-app"])
    elif command in {"program", "verify", "metadata image-valid"}:
        args.extend(["--image", "app.out"])
    with pytest.raises(CliUsageError):
        parse(args)


def test_metadata_image_valid_requires_its_app_image() -> None:
    with pytest.raises(CliUsageError):
        parse(
            [
                "metadata",
                "image-valid",
                "--flash-service-image",
                "service.out",
                "--flash-service-map",
                "service.map",
            ]
        )


def test_upgrade_requires_only_its_declared_options() -> None:
    args = parse(
        [
            "upgrade",
            "--image",
            "app.out",
            "--flash-service-image",
            "service.out",
            "--flash-service-map",
            "service.map",
            "--no-run",
            "--yes",
        ]
    )

    assert args.command == "upgrade"
    assert args.image == "app.out"
    assert args.flash_service_image == "service.out"
    assert args.flash_service_map == "service.map"
    assert args.no_run and args.yes


@pytest.mark.parametrize(
    "option",
    [
        "--entry-point",
        "--sector-mask",
        "--skip-verify",
        "--skip-erase",
        "--skip-program",
        "--skip-image-valid",
        "--skip-boot-attempt",
        "--force",
        "--retry",
        "--resume",
        "--reconnect",
    ],
)
def test_upgrade_rejects_stage_and_legacy_options(option: str) -> None:
    with pytest.raises(CliUsageError):
        parse(_valid_command_args("upgrade") + [option, "value"])


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "metadata",
            "boot-attempt",
            "--flash-service-image",
            "service.out",
            "--flash-service-map",
            "service.map",
            "--image",
            "app.out",
        ],
        [
            "metadata",
            "app-confirmed",
            "--flash-service-image",
            "service.out",
            "--flash-service-map",
            "service.map",
            "--image",
            "app.out",
        ],
        ["run", "--entry-point", "0x82400"],
        ["run", "--image", "app.out"],
        ["run", "--flash-service-image", "service.out"],
        ["run-ram", "--entry-point", "0x8000", "--image", "ram.out"],
        ["run-ram", "--entry-point", "0x8000", "--flash-service-image", "service.out"],
        ["ram", "load", "--image", "ram.out", "--entry-point", "0x8000"],
        ["ram", "check-crc", "--image", "ram.out", "--load-first"],
    ],
)
def test_b04_forbidden_arguments_are_rejected(arguments: list[str]) -> None:
    with pytest.raises(CliUsageError):
        parse(arguments)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["metadata", "image-valid", "--image"], "metadata image-valid"),
        (["metadata", "boot-attempt", "--image"], "metadata boot-attempt"),
        (["metadata", "app-confirmed", "--image"], "metadata app-confirmed"),
        (["run", "--entry-point"], "run"),
        (["ram", "load", "--image"], "ram load"),
        (["ram", "check-crc", "--image"], "ram check-crc"),
        (["run-ram", "--entry-point"], "run-ram"),
        (["upgrade", "--image"], "upgrade"),
    ],
)
def test_b04_parser_error_labels_are_stable(arguments: list[str], expected: str) -> None:
    assert command_from_argv(arguments) == expected


def test_sector_mask_is_uint32() -> None:
    args = parse(
        [
            "erase",
            "--flash-service-image",
            "service.out",
            "--flash-service-map",
            "service.map",
            "--sector-mask",
            "0xFFFFFFFF",
        ]
    )
    assert args.sector_mask == 0xFFFFFFFF


@pytest.mark.parametrize(
    "option",
    [
        "--descriptor-address",
        "--force",
        "--force-service-attach",
        "--reload",
        "--erase-first",
        "--verify-after",
        "--mark-valid",
        "--skip-verify",
        "--hex2000",
    ],
)
def test_b03_forbidden_options_are_not_formal_cli_options(option: str) -> None:
    with pytest.raises(CliUsageError):
        parse(["status", option, "value"])


def test_help_and_version_keep_standard_text_behavior(capsys) -> None:
    with pytest.raises(SystemExit) as help_exit:
        build_parser().parse_args(["--help"])
    assert help_exit.value.code == 0
    assert "memory" in capsys.readouterr().out

    with pytest.raises(SystemExit) as version_exit:
        build_parser().parse_args(["--version"])
    assert version_exit.value.code == 0
    assert "bootloader-cli" in capsys.readouterr().out
