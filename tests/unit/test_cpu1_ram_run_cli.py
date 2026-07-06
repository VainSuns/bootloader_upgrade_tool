import json

import pytest

from bootloader_upgrade_tool.tools import cpu1_ram_run


SCI8_RAM_IMAGE = """
08AA
0000 0000 0000 0000 0000 0000 0000 0000
0000 8000
0003 0000 8000 1111 2222 3333
0000
"""


def test_arg_defaults_and_aliases() -> None:
    args = cpu1_ram_run.build_arg_parser().parse_args(
        ["--transport", "simulator", "--sci8-txt", "ram.txt", "--json", "--keep-hex"]
    )

    cpu1_ram_run.normalize_output(args)

    assert args.baud == 9600
    assert args.autobaud_mode == "always"
    assert args.output == "json"
    assert args.keep_sci8_txt is True


def test_help_describes_core_options() -> None:
    text = cpu1_ram_run.build_arg_parser().format_help()

    assert "serial baud rate (default: 9600)" in text
    assert "SCI 'A' autobaud" in text
    assert "compatibility alias of --sci8-txt" in text


def test_invalid_autobaud_mode_rejected() -> None:
    with pytest.raises(SystemExit):
        cpu1_ram_run.build_arg_parser().parse_args(
            ["--transport", "simulator", "--image", "ram.txt", "--autobaud-mode", "auto"]
        )


def test_simulator_path_runs_ram_only(tmp_path) -> None:
    image = tmp_path / "ram.sci8.txt"
    image.write_text(SCI8_RAM_IMAGE, encoding="ascii")

    args = cpu1_ram_run.build_arg_parser().parse_args(
        ["--transport", "simulator", "--sci8-txt", str(image)]
    )
    result = cpu1_ram_run.run_cpu1_ram_run(args)

    assert result.entry_point == 0x008000
    assert result.total_words == 3
    assert result.packet_count == 1
    assert result.crc32 == 0x5E813FB2


def test_json_envelope_shape() -> None:
    data = cpu1_ram_run.envelope(
        ok=True,
        tool="cpu1_ram_run",
        command="run",
        stage="DONE",
        result=cpu1_ram_run.ram_run.RamRunResult(1, 2, 3, 4),
    )

    assert json.loads(json.dumps(data))["result"]["crc32"] == 3


def test_out_input_keep_sci8_uses_conversion_path(monkeypatch, tmp_path) -> None:
    calls: list[tuple] = []
    out = tmp_path / "ram.out"
    out.write_text("stub", encoding="ascii")

    def fake_run_hex2000(source, output, *, hex2000_path=None):
        calls.append(("hex2000", source, output, hex2000_path))
        output.write_text(SCI8_RAM_IMAGE, encoding="ascii")

    monkeypatch.setattr(cpu1_ram_run, "run_hex2000", fake_run_hex2000)

    args = cpu1_ram_run.build_arg_parser().parse_args(
        ["--transport", "simulator", "--image", str(out), "--keep-sci8-txt", "--hex2000", "cgroot"]
    )
    result = cpu1_ram_run.run_cpu1_ram_run(args)

    assert result.total_words == 3
    assert calls[0][2] == out.with_suffix(".sci8.txt")
    assert out.with_suffix(".sci8.txt").exists()
