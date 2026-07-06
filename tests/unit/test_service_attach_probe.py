from bootloader_upgrade_tool.tools import service_attach_probe


def test_arg_parser_autobaud_mode() -> None:
    args = service_attach_probe.build_arg_parser().parse_args(
        [
            "--transport",
            "simulator",
            "--image",
            "service.out",
            "--map",
            "service.map",
            "--autobaud-mode",
            "skip",
        ]
    )
    assert args.autobaud_mode == "skip"
