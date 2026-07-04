import json

import pytest

from bootloader_upgrade_tool.tools import ram_run


SCI8_RAM_IMAGE = """
08AA
0000 0000 0000 0000 0000 0000 0000 0000
0000 8000
0003 0000 8000 1111 2222 3333
0000
"""


def test_serial_transport_without_port_fails() -> None:
    parser = ram_run.build_arg_parser()
    args = parser.parse_args(["--transport", "serial", "--image", "ram.out"])

    with pytest.raises(SystemExit):
        ram_run.validate_args(parser, args)


def test_simulator_ram_run_smoke_passes(tmp_path) -> None:
    image = tmp_path / "ram.sci8.txt"
    image.write_text(SCI8_RAM_IMAGE, encoding="ascii")

    result = ram_run.run(
        ram_run.build_arg_parser().parse_args(
            ["--transport", "simulator", "--image", str(image)]
        )
    )

    assert result.entry_point == 0x008000
    assert result.total_words == 3
    assert result.packet_count == 1
    assert result.crc32 == 0x5E813FB2


def test_json_output_contains_result_fields() -> None:
    text = ram_run.format_text(ram_run.RamRunResult(0x008000, 3, 0x12345678, 1))

    assert "PASS" in text
    assert "0x00008000" in text
    assert json.loads(json.dumps(ram_run.RamRunResult(1, 2, 3, 4).to_dict()))["crc32"] == 3


def test_ram_run_uses_client_open_for_autobaud(monkeypatch, tmp_path) -> None:
    image = tmp_path / "ram.sci8.txt"
    image.write_text(SCI8_RAM_IMAGE, encoding="ascii")
    calls: list[tuple[int, int]] = []

    class FakeClient:
        device_info = type("Info", (), {"max_data_words": 248})()

        def __init__(self, device, **kwargs) -> None:
            pass

        def open(self, *, wait_slave_timeout_ms, device_info_timeout_ms):
            calls.append((wait_slave_timeout_ms, device_info_timeout_ms))
            return self.device_info

        def close(self) -> None:
            pass

    class FakeWorkflow:
        def __init__(self, client) -> None:
            pass

        def run_ram_image(self, image) -> int:
            return 0x12345678

    monkeypatch.setattr(ram_run, "ProtocolClient", FakeClient)
    monkeypatch.setattr(ram_run, "UpgradeWorkflow", FakeWorkflow)

    result = ram_run.run(
        ram_run.build_arg_parser().parse_args(
            ["--transport", "simulator", "--image", str(image), "--timeout-ms", "1234"]
        )
    )

    assert calls == [(1234, 1234)]
    assert result.crc32 == 0x12345678
